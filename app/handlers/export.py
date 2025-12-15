"""
Обработчики экспорта расписания
"""
import asyncio
import datetime
import hashlib
import logging
from io import BytesIO
from typing import Optional, Tuple
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ..constants import (
    CTX_SELECTED_DATE, CTX_SCHEDULE_PAGES, CTX_CURRENT_PAGE_INDEX, CTX_LAST_QUERY,
    CALLBACK_DATA_EXPORT_MENU, CALLBACK_DATA_EXPORT_WEEK_IMAGE, CALLBACK_DATA_EXPORT_WEEK_FILE,
    CALLBACK_DATA_EXPORT_DAYS_IMAGES, CALLBACK_DATA_EXPORT_SEMESTER,
    CALLBACK_DATA_BACK_TO_START, CallbackData,
    MODE_STUDENT, MODE_TEACHER, API_TYPE_GROUP, API_TYPE_TEACHER,
    ENTITY_GROUP_GENITIVE, ENTITY_TEACHER_GENITIVE,
)
from ..utils import escape_html
from ..state_manager import is_user_busy, clear_user_busy_state
from .utils import (
    safe_edit_message_text, safe_answer_callback_query, ExportProgress, user_busy_context
)


def sanitize_filename(value: str) -> str:
    """Удаляет недопустимые символы из имени файла"""
    import re
    cleaned = re.sub(r'[\\/*?:"<>|]', "_", value).strip()
    return cleaned or "export"
from excel_export.export_semester import (
    resolve_semester_bounds,
    fetch_semester_schedule,
    build_excel_workbook,
    build_group_archive_bytes,
)

logger = logging.getLogger(__name__)


def parse_export_callback_data(data: str, prefix: str) -> Tuple[Optional[str], Optional[str]]:
    """Парсит callback data для экспорта: возвращает (mode, query_hash)"""
    # data format: "{prefix}_{mode}_{query_hash}"
    try:
        parts = data.replace(prefix + "_", "", 1).split("_", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return None, None
    except Exception as e:
        logger.debug(f"Ошибка при парсинге callback data: {e}", exc_info=True)
        return None, None


def parse_semester_callback_data(data: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Парсит callback data семестрового экспорта: (mode, query_hash, option)"""
    try:
        payload = data.replace(f"{CALLBACK_DATA_EXPORT_SEMESTER}_", "", 1)
        parts = payload.split("_")
        if len(parts) >= 2:
            mode = parts[0]
            query_hash = parts[1]
            semester_option = "_".join(parts[2:]) if len(parts) > 2 else None
            return mode, query_hash, semester_option
        return None, None, None
    except Exception as e:
        logger.debug(f"Ошибка при парсинге semester callback data: {e}", exc_info=True)
        return None, None, None


async def setup_export_process(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    data: str,
    prefix: str,
    progress_text: str = "Генерирую...",
    parse_weeks: bool = False
) -> Tuple[Optional[str], Optional[str], Optional[str], int, bool]:
    """
    Вспомогательная функция для настройки процесса экспорта.
    Парсит данные, проверяет busy-статус, наличие данных в кэше.
    НЕ устанавливает блокировку - это делается через user_busy_context в вызывающем коде.

    Args:
        update: Update объект
        context: Context объект
        data: Callback data строка
        prefix: Префикс callback data (например, CALLBACK_DATA_EXPORT_WEEK_IMAGE)
        progress_text: Текст для ответа на callback query
        parse_weeks: Если True, парсит _week0/_week1 из конца data

    Returns:
        Tuple[Optional[str], Optional[str], Optional[str], int, bool]:
        - mode: режим работы (MODE_STUDENT или MODE_TEACHER)
        - query_hash: хеш запроса
        - entity_name: название группы/преподавателя
        - week_offset: смещение недели (0 или 1)
        - success: успешность операции
    """
    if not update.callback_query:
        return None, None, None, 0, False

    user_data = context.user_data
    week_offset = 0
    clean_data = data

    # Встроенный парсинг недели
    if parse_weeks:
        if data.endswith("_week0"):
            week_offset = 0
            clean_data = data[:-6]  # Убираем "_week0"
        elif data.endswith("_week1"):
            week_offset = 1
            clean_data = data[:-6]  # Убираем "_week1"

    # 1. Парсинг данных
    mode, query_hash = parse_export_callback_data(clean_data, prefix)
    logger.debug(f"setup_export_process: data={data}, clean_data={clean_data}, prefix={prefix}, mode={mode}, query_hash={query_hash}")
    if not mode or not query_hash:
        logger.error(f"setup_export_process: Ошибка парсинга данных - mode={mode}, query_hash={query_hash}")
        await safe_answer_callback_query(update.callback_query, "Ошибка данных", show_alert=True)
        return None, None, None, 0, False

    # 2. Получение имени сущности
    export_key = f"export_{mode}_{query_hash}"
    entity_name = user_data.get(export_key)
    logger.debug(f"setup_export_process: Ищу ключ '{export_key}', найдено: {entity_name}")
    logger.debug(f"setup_export_process: Доступные ключи export_*: {[k for k in user_data.keys() if k.startswith('export_')]}")
    if not entity_name:
        logger.error(f"setup_export_process: Entity name не найден для ключа '{export_key}'. Доступные ключи: {[k for k in user_data.keys() if 'export' in k.lower()]}")
        await safe_answer_callback_query(update.callback_query, "Ошибка: данные не найдены. Попробуйте открыть расписание снова.", show_alert=True)
        return None, None, None, 0, False

    # 3. Проверка блокировки
    if is_user_busy(user_data):
        logger.warning(f"setup_export_process: Пользователь занят, но продолжаю (возможно, флаг не сбросился)")
        # Принудительно сбрасываем busy флаг, если он остался установленным
        # Это защита от "зависших" флагов после ошибок
        clear_user_busy_state(user_data)
        logger.debug(f"setup_export_process: Busy флаг сброшен, продолжаю экспорт")

    # 4. Ответ на callback (блокировку ставим через context manager в вызывающем коде)
    await safe_answer_callback_query(update.callback_query, progress_text)
    logger.debug(f"setup_export_process: Успешно настроен экспорт для {entity_name} (mode={mode}, week_offset={week_offset})")

    return mode, query_hash, entity_name, week_offset, True


async def show_export_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Показать меню экспорта"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    logger.info(f"📤 [{user_id}] @{username} → Открыл меню экспорта, data: {data}")

    # data format: "export_menu_{mode}_{query_hash}"
    mode, query_hash = parse_export_callback_data(data, CALLBACK_DATA_EXPORT_MENU)
    logger.info(f"show_export_menu: mode={mode}, query_hash={query_hash}")
    if not mode or not query_hash:
        logger.error(f"show_export_menu: Ошибка парсинга данных")
        await update.callback_query.answer("Ошибка данных", show_alert=True)
        return

    user_data = context.user_data
    export_key = f"export_{mode}_{query_hash}"
    entity_name = user_data.get(export_key)

    # Если данные не найдены, пытаемся восстановить из сохраненного запроса
    if not entity_name:
        logger.warning(f"show_export_menu: Данные не найдены для ключа '{export_key}', пытаюсь восстановить из CTX_LAST_QUERY")
        entity_name = user_data.get(CTX_LAST_QUERY)
        if entity_name:
            logger.info(f"show_export_menu: Восстановлено из CTX_LAST_QUERY: {entity_name}")
            user_data[export_key] = entity_name
        else:
            logger.error(f"show_export_menu: Не удалось восстановить данные. Доступные ключи: {list(user_data.keys())}")
            await update.callback_query.answer("Ошибка: данные не найдены. Попробуйте открыть расписание снова.", show_alert=True)
            return

    # Сохраняем состояние для возврата к расписанию
    user_data["export_back_mode"] = mode
    user_data["export_back_query"] = entity_name
    export_date = user_data.get(CTX_SELECTED_DATE)
    if not export_date:
        export_date = datetime.date.today().strftime("%Y-%m-%d")
    user_data["export_back_date"] = export_date
    if user_data.get(CTX_SCHEDULE_PAGES):
        user_data["export_back_pages"] = user_data[CTX_SCHEDULE_PAGES]
        user_data["export_back_page_index"] = user_data.get(CTX_CURRENT_PAGE_INDEX, 0)

    entity_label = ENTITY_TEACHER_GENITIVE if mode == MODE_TEACHER else ENTITY_GROUP_GENITIVE

    text = f"📤 <b>Экспорт расписания для {entity_label}:</b>\n<code>{escape_html(entity_name)}</code>\n\nВыберите формат экспорта:"

    kbd_rows = []

    if mode == MODE_STUDENT:
        # Для студентов: неделя картинкой, неделя файлом (PDF), по дням картинками
        kbd_rows.extend([
            [InlineKeyboardButton("🖼 Неделя (картинка)", callback_data=f"{CALLBACK_DATA_EXPORT_WEEK_IMAGE}_{mode}_{query_hash}")],
            [InlineKeyboardButton("📄 Неделя (PDF)", callback_data=f"{CALLBACK_DATA_EXPORT_WEEK_FILE}_{mode}_{query_hash}")],
            [InlineKeyboardButton("📸 По дням (картинки)", callback_data=f"{CALLBACK_DATA_EXPORT_DAYS_IMAGES}_{mode}_{query_hash}")],
            [InlineKeyboardButton("📊 Семестр (Excel)", callback_data=f"{CALLBACK_DATA_EXPORT_SEMESTER}_{mode}_{query_hash}")],
        ])
    else:
        # Для преподавателей: неделя картинкой, неделя файлом (PDF)
        kbd_rows.extend([
            [InlineKeyboardButton("🖼 Неделя (картинка)", callback_data=f"{CALLBACK_DATA_EXPORT_WEEK_IMAGE}_{mode}_{query_hash}")],
            [InlineKeyboardButton("📄 Неделя (PDF)", callback_data=f"{CALLBACK_DATA_EXPORT_WEEK_FILE}_{mode}_{query_hash}")],
            [InlineKeyboardButton("📊 Семестр (Excel)", callback_data=f"{CALLBACK_DATA_EXPORT_SEMESTER}_{mode}_{query_hash}")],
        ])

    # Кнопка "Назад" должна возвращать к расписанию, а не в начало
    kbd_rows.append([InlineKeyboardButton("⬅️ Назад к расписанию", callback_data="back_to_schedule_from_export")])

    kbd = InlineKeyboardMarkup(kbd_rows)
    if not await safe_edit_message_text(update.callback_query, text, reply_markup=kbd, parse_mode=ParseMode.HTML):
        try:
            await update.callback_query.message.reply_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.debug(f"Ошибка при обновлении прогресса: {e}", exc_info=True)


async def export_week_schedule_image(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Экспорт расписания на неделю картинкой"""
    if not update.callback_query:
        logger.error("export_week_schedule_image вызван без callback_query")
        return

    user_id = update.effective_user.id if update.effective_user else "unknown"
    username = update.effective_user.username or "без username" if update.effective_user else "unknown"
    logger.debug(f"📤 [{user_id}] @{username} → Экспорт расписания: неделя (картинка), data: {data[:50]}")

    # Используем setup_export_process с парсингом недели
    mode, query_hash, entity_name, week_offset, success = await setup_export_process(
        update, context, data, CALLBACK_DATA_EXPORT_WEEK_IMAGE, "Генерирую картинку...", parse_weeks=True
    )
    if not success:
        logger.error(f"export_week_schedule_image: setup_export_process вернул success=False")
        return

    logger.debug(f"export_week_schedule_image: Начинаю экспорт для {entity_name} (mode={mode}, week_offset={week_offset})")

    # Используем контекстный менеджер для гарантированного снятия блокировки
    user_data = context.user_data
    with user_busy_context(user_data):
        progress = ExportProgress(update.callback_query.message)
        await progress.start("⏳ Подготавливаю расписание...")

        try:
            entity_type = API_TYPE_TEACHER if mode == MODE_TEACHER else API_TYPE_GROUP
            from ..export import get_week_schedule_structured, generate_schedule_image

            # Получаем расписание для выбранной недели
            logger.debug(f"export_week_schedule_image: Запрашиваю расписание для {entity_name} (тип: {entity_type}, неделя: {week_offset})")
            week_schedule = await get_week_schedule_structured(entity_name, entity_type, week_offset=week_offset)
            logger.debug(f"export_week_schedule_image: Получено расписание: {len(week_schedule) if week_schedule else 0} дней")

            # Если week_offset не был указан (0) и на текущей неделе нет пар, проверяем следующую неделю
            if week_offset == 0 and not week_schedule:
                next_week_schedule = await get_week_schedule_structured(entity_name, entity_type, week_offset=1)
                if next_week_schedule:
                    # На следующей неделе есть пары - спрашиваем у пользователя
                    today = datetime.date.today()
                    days_since_monday = today.weekday()
                    if days_since_monday == 6:
                        current_monday = today + datetime.timedelta(days=1)
                    else:
                        current_monday = today - datetime.timedelta(days=days_since_monday)
                    next_monday = current_monday + datetime.timedelta(days=7)

                    text = (
                        f"📅 На текущей неделе ({current_monday.strftime('%d.%m.%Y')} - {(current_monday + datetime.timedelta(days=5)).strftime('%d.%m.%Y')}) "
                        f"нет занятий.\n\n"
                        f"На следующей неделе ({next_monday.strftime('%d.%m.%Y')} - {(next_monday + datetime.timedelta(days=5)).strftime('%d.%m.%Y')}) "
                        f"есть занятия.\n\n"
                        f"Какую неделю экспортировать?"
                    )
                    kbd = InlineKeyboardMarkup([
                        [InlineKeyboardButton("📅 Текущая неделя", callback_data=f"{CALLBACK_DATA_EXPORT_WEEK_IMAGE}_{mode}_{query_hash}_week0")],
                        [InlineKeyboardButton("📅 Следующая неделя", callback_data=f"{CALLBACK_DATA_EXPORT_WEEK_IMAGE}_{mode}_{query_hash}_week1")],
                        [InlineKeyboardButton("⬅️ Назад", callback_data=f"{CALLBACK_DATA_EXPORT_MENU}_{mode}_{query_hash}")]
                    ])
                    await update.callback_query.message.edit_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
                    await progress.finish("ℹ️ Выберите неделю.", delete_after=0)
                    return

            # Если нет расписания для выбранной недели
            if not week_schedule:
                await progress.finish("⚠️ На выбранной неделе нет занятий.", delete_after=0)
                return

            await progress.update(60, "🖼 Рисую изображение...")
            logger.debug(f"export_week_schedule_image: Начинаю генерацию изображения")
            # Генерируем картинку (это может занять время)
            img_bytes = await generate_schedule_image(week_schedule, entity_name, entity_type)
            logger.debug(f"export_week_schedule_image: Изображение сгенерировано: {img_bytes is not None}")

            if img_bytes:
                entity_label = ENTITY_TEACHER_GENITIVE if mode == MODE_TEACHER else ENTITY_GROUP_GENITIVE
                # Сохраняем состояние для возврата (используем текущую дату из расписания)
                user_data["export_back_mode"] = mode
                user_data["export_back_query"] = entity_name
                # Сохраняем текущую дату из расписания, если она есть
                export_date = user_data.get(CTX_SELECTED_DATE)
                if not export_date:
                    export_date = datetime.date.today().strftime("%Y-%m-%d")
                user_data["export_back_date"] = export_date
                # Также сохраняем страницы расписания для быстрого возврата
                if user_data.get(CTX_SCHEDULE_PAGES):
                    user_data["export_back_pages"] = user_data[CTX_SCHEDULE_PAGES]
                    user_data["export_back_page_index"] = user_data.get(CTX_CURRENT_PAGE_INDEX, 0)

                back_kbd = InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Назад к расписанию", callback_data=CallbackData.BACK_TO_SCHEDULE.value)],
                    [InlineKeyboardButton("🏠 В начало", callback_data=CALLBACK_DATA_BACK_TO_START)]
                ])

                logger.debug(f"export_week_schedule_image: Отправляю изображение пользователю")
                try:
                    await update.callback_query.message.reply_photo(
                        photo=img_bytes,
                        caption=f"📅 Расписание на неделю для {entity_label}: {escape_html(entity_name)}",
                        reply_markup=back_kbd
                    )
                    logger.debug(f"export_week_schedule_image: Изображение успешно отправлено")
                except Exception as send_error:
                    logger.error(f"export_week_schedule_image: Ошибка при отправке изображения: {send_error}", exc_info=True)
                    try:
                        await update.callback_query.message.reply_text(
                            f"❌ Ошибка при отправке изображения. Попробуйте позже.",
                            reply_markup=back_kbd
                        )
                    except Exception as e:
                        logger.debug(f"Ошибка при отправке сообщения: {e}", exc_info=True)

                try:
                    await progress.finish("✅ Экспорт готов!")
                except Exception as progress_error:
                    logger.error(f"export_week_schedule_image: Ошибка при завершении прогресса: {progress_error}")
            else:
                from ..export import format_week_schedule_text
                text = format_week_schedule_text(week_schedule, entity_name, entity_type)
                await update.callback_query.message.reply_text(text, parse_mode=ParseMode.HTML)
                await progress.finish("ℹ️ Отправил текст вместо картинки.", delete_after=0)
        except Exception as e:
            logger.error(f"❌ Ошибка при генерации картинки недели: {e}", exc_info=True)
            try:
                await update.callback_query.message.reply_text(
                    "❌ Произошла ошибка при генерации картинки. Попробуйте позже."
                )
            except Exception as reply_error:
                logger.error(f"Ошибка при отправке сообщения об ошибке: {reply_error}")
            try:
                await progress.finish("❌ Ошибка при экспорте.", delete_after=0)
            except Exception as progress_error:
                logger.error(f"Ошибка при завершении прогресса: {progress_error}")
        # Блокировка снимется автоматически через context manager


async def export_week_schedule_file(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Экспорт расписания на неделю файлом"""
    if not update.callback_query:
        logger.error("export_week_schedule_file вызван без callback_query")
        return

    user_id = update.effective_user.id if update.effective_user else "unknown"
    username = update.effective_user.username or "без username" if update.effective_user else "unknown"
    logger.info(f"📤 [{user_id}] @{username} → Экспорт расписания: неделя (PDF), data: {data[:50]}")

    # Используем setup_export_process с парсингом недели
    mode, query_hash, entity_name, week_offset, success = await setup_export_process(
        update, context, data, CALLBACK_DATA_EXPORT_WEEK_FILE, "Генерирую файл...", parse_weeks=True
    )
    if not success:
        return

    # Используем контекстный менеджер для гарантированного снятия блокировки
    user_data = context.user_data
    with user_busy_context(user_data):
        progress = ExportProgress(update.callback_query.message)
        await progress.start("⏳ Подготавливаю расписание...")

        try:
            entity_type = API_TYPE_TEACHER if mode == MODE_TEACHER else API_TYPE_GROUP
            from ..export import get_week_schedule_structured, generate_week_schedule_file

            # Получаем расписание для выбранной недели
            week_schedule = await get_week_schedule_structured(entity_name, entity_type, week_offset=week_offset)

            # Если week_offset не был указан (0) и на текущей неделе нет пар, проверяем следующую неделю
            if week_offset == 0 and not week_schedule:
                next_week_schedule = await get_week_schedule_structured(entity_name, entity_type, week_offset=1)
                if next_week_schedule:
                    # На следующей неделе есть пары - спрашиваем у пользователя
                    today = datetime.date.today()
                    days_since_monday = today.weekday()
                    if days_since_monday == 6:
                        current_monday = today + datetime.timedelta(days=1)
                    else:
                        current_monday = today - datetime.timedelta(days=days_since_monday)
                    next_monday = current_monday + datetime.timedelta(days=7)

                    text = (
                        f"📅 На текущей неделе ({current_monday.strftime('%d.%m.%Y')} - {(current_monday + datetime.timedelta(days=5)).strftime('%d.%m.%Y')}) "
                        f"нет занятий.\n\n"
                        f"На следующей неделе ({next_monday.strftime('%d.%m.%Y')} - {(next_monday + datetime.timedelta(days=5)).strftime('%d.%m.%Y')}) "
                        f"есть занятия.\n\n"
                        f"Какую неделю экспортировать?"
                    )
                    kbd = InlineKeyboardMarkup([
                        [InlineKeyboardButton("📅 Текущая неделя", callback_data=f"{CALLBACK_DATA_EXPORT_WEEK_FILE}_{mode}_{query_hash}_week0")],
                        [InlineKeyboardButton("📅 Следующая неделя", callback_data=f"{CALLBACK_DATA_EXPORT_WEEK_FILE}_{mode}_{query_hash}_week1")],
                        [InlineKeyboardButton("⬅️ Назад", callback_data=f"{CALLBACK_DATA_EXPORT_MENU}_{mode}_{query_hash}")]
                    ])
                    await update.callback_query.message.edit_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
                    await progress.finish("ℹ️ Выберите неделю.", delete_after=0)
                    return

            # Если нет расписания для выбранной недели
            if not week_schedule:
                await update.callback_query.message.reply_text(
                    "❌ На выбранной неделе нет занятий."
                )
                await progress.finish("⚠️ На выбранной неделе нет занятий.", delete_after=0)
                return
            await progress.update(60, "📄 Формирую PDF...")
            file_bytes = await generate_week_schedule_file(week_schedule, entity_name, entity_type)

            if file_bytes:
                entity_label = ENTITY_TEACHER_GENITIVE if mode == MODE_TEACHER else ENTITY_GROUP_GENITIVE
                filename = f"raspisanie_{entity_name.replace(' ', '_')[:30]}.pdf"
                # Сохраняем состояние для возврата (используем текущую дату из расписания)
                user_data["export_back_mode"] = mode
                user_data["export_back_query"] = entity_name
                # Сохраняем текущую дату из расписания, если она есть
                export_date = user_data.get(CTX_SELECTED_DATE)
                if not export_date:
                    export_date = datetime.date.today().strftime("%Y-%m-%d")
                user_data["export_back_date"] = export_date
                # Также сохраняем страницы расписания для быстрого возврата
                if user_data.get(CTX_SCHEDULE_PAGES):
                    user_data["export_back_pages"] = user_data[CTX_SCHEDULE_PAGES]
                    user_data["export_back_page_index"] = user_data.get(CTX_CURRENT_PAGE_INDEX, 0)

                back_kbd = InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Назад к расписанию", callback_data=CallbackData.BACK_TO_SCHEDULE.value)],
                    [InlineKeyboardButton("🏠 В начало", callback_data=CALLBACK_DATA_BACK_TO_START)]
                ])
                await update.callback_query.message.reply_document(
                    document=file_bytes,
                    filename=filename,
                    caption=f"📄 Расписание на неделю для {entity_label}: {escape_html(entity_name)}",
                    reply_markup=back_kbd
                )
                await progress.finish()
            else:
                try:
                    await update.callback_query.message.reply_text("❌ Ошибка при генерации файла. Попробуйте позже.")
                except Exception as e:
                    logger.debug(f"Ошибка при отправке сообщения: {e}", exc_info=True)
                await progress.finish("❌ Ошибка при экспорте.", delete_after=0)
        except Exception as e:
            logger.error(f"❌ Ошибка при генерации файла недели: {e}", exc_info=True)
            try:
                await update.callback_query.message.reply_text("❌ Произошла ошибка при генерации файла. Попробуйте позже.")
            except Exception as reply_error:
                logger.error(f"Ошибка при отправке сообщения об ошибке: {reply_error}")
            try:
                await progress.finish("❌ Ошибка при экспорте.", delete_after=0)
            except Exception as progress_error:
                logger.error(f"Ошибка при завершении прогресса: {progress_error}")
        # Блокировка снимется автоматически через context manager


async def export_days_images(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Экспорт расписания по дням (отдельные картинки для каждого дня)"""
    if not update.callback_query:
        return

    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    logger.info(f"📤 [{user_id}] @{username} → Экспорт расписания: по дням (картинки)")

    # Парсим callback data: "export_days_images_{mode}_{query_hash}"
    try:
        # Убираем префикс "export_days_images_"
        prefix = CALLBACK_DATA_EXPORT_DAYS_IMAGES + "_"
        if not data.startswith(prefix):
            logger.error(f"Callback data не начинается с префикса: {prefix}, data={data}")
            await safe_answer_callback_query(update.callback_query, "Ошибка данных", show_alert=True)
            return
        parts = data[len(prefix):].split("_", 1)
        if len(parts) == 2:
            mode, query_hash = parts[0], parts[1]
        else:
            logger.error(f"Неверный формат callback data: {data}")
            await safe_answer_callback_query(update.callback_query, "Ошибка данных", show_alert=True)
            return
    except Exception as e:
        logger.error(f"Ошибка парсинга callback data: {e}", exc_info=True)
        await safe_answer_callback_query(update.callback_query, "Ошибка данных", show_alert=True)
        return
    logger.info(f"Экспорт по дням: mode = {mode}, query_hash = {query_hash}")

    if not mode or not query_hash:
        logger.error(f"Ошибка парсинга callback_data: mode={mode}, query_hash={query_hash}")
        await safe_answer_callback_query(update.callback_query, "Ошибка данных", show_alert=True)
        return

    user_data = context.user_data
    entity_name = user_data.get(f"export_{mode}_{query_hash}")
    logger.info(f"Экспорт по дням: entity_name = {entity_name}")

    if not entity_name:
        logger.error(f"Entity name не найден для ключа: export_{mode}_{query_hash}")
        await safe_answer_callback_query(update.callback_query, "Ошибка: данные не найдены", show_alert=True)
        return

    if is_user_busy(user_data):
        await safe_answer_callback_query(update.callback_query, "⏳ Уже генерирую другой экспорт, подождите...")
        return

    # Отвечаем на callback сразу
    await safe_answer_callback_query(update.callback_query, "Генерирую картинки по дням...")

    # Используем context manager для гарантированного снятия блокировки
    progress = ExportProgress(update.callback_query.message)
    logger.info(f"Создан ExportProgress, начинаю start...")
    try:
        await progress.start("⏳ Подготавливаю изображения по дням...")
        logger.info(f"progress.start завершен успешно")
    except Exception as progress_error:
        logger.error(f"Ошибка при progress.start: {progress_error}", exc_info=True)
        # Продолжаем выполнение даже если прогресс не запустился

    logger.info(f"Вхожу в user_busy_context...")
    with user_busy_context(user_data):
        logger.info(f"Внутри user_busy_context, начинаю обработку...")
        try:
            entity_type = API_TYPE_TEACHER if mode == MODE_TEACHER else API_TYPE_GROUP
            from ..export import get_week_schedule_structured, generate_day_schedule_image
            from ..schedule import get_schedule_structured

            # Используем ту же логику, что и в get_week_schedule_structured
            today = datetime.date.today()
            days_since_monday = today.weekday()
            if days_since_monday == 6:  # Воскресенье
                monday = today + datetime.timedelta(days=1)
            else:
                monday = today - datetime.timedelta(days=days_since_monday)

            logger.info(f"Запрашиваю расписание на неделю для {entity_name} (тип: {entity_type}, неделя с {monday.strftime('%d.%m.%Y')})")
            try:
                week_schedule = await get_week_schedule_structured(entity_name, entity_type, start_date=today)
                if not week_schedule:
                    logger.warning(f"get_week_schedule_structured вернул пустой результат для {entity_name}")
                    week_schedule = {}
            except Exception as e:
                logger.error(f"Ошибка при получении расписания на неделю: {e}", exc_info=True)
                week_schedule = {}

            logger.info(f"Получено расписание на неделю: {len(week_schedule)} дней с парами (неделя с {monday.strftime('%d.%m.%Y')})")

            weekdays = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]
            entity_label = ENTITY_TEACHER_GENITIVE if mode == MODE_TEACHER else ENTITY_GROUP_GENITIVE

            # Сначала определяем, сколько дней с парами будет
            # Но мы будем проверять каждый день индивидуально через get_schedule_structured
            # так как week_schedule может быть неполным
            logger.info(f"Начинаю генерацию картинок для недели с {monday.strftime('%d.%m.%Y')}")

            # Собираем все картинки и подписи
            media_group = []
            generated_count = 0
            total_days_to_check = 6  # Пн-Сб

            logger.info(f"Начинаю обработку {total_days_to_check} дней недели")
            for day_offset in range(total_days_to_check):  # Пн-Сб
                current_date = monday + datetime.timedelta(days=day_offset)
                date_str = current_date.strftime("%Y-%m-%d")
                weekday_name = weekdays[day_offset]

                logger.info(f"Обрабатываю день {date_str} ({weekday_name})")
                await progress.update(int((day_offset / total_days_to_check) * 50), f"📅 Проверяю {weekday_name}...")

                # Получаем структурированное расписание для дня
                try:
                    day_schedule, err = await get_schedule_structured(date_str, entity_name, entity_type)
                    if err:
                        logger.warning(f"Не удалось получить расписание для {date_str}: {err}")
                        continue
                    if not day_schedule:
                        logger.debug(f"День {date_str}: пустое расписание, пропускаем")
                        continue
                except Exception as schedule_error:
                    logger.error(f"Ошибка при получении расписания для {date_str}: {schedule_error}", exc_info=True)
                    continue

                # Проверяем, есть ли пары в структурированном расписании
                day_pairs = day_schedule.get("pairs", [])
                if not day_pairs:
                    logger.debug(f"День {date_str}: нет пар в структурированном расписании, пропускаем")
                    continue

                logger.info(f"День {date_str}: найдено {len(day_pairs)} пар, генерирую картинку...")
                try:
                    img_bytes = await generate_day_schedule_image(day_schedule, entity_name, entity_type)
                    if img_bytes:
                        logger.info(f"✅ Картинка для {date_str} успешно сгенерирована")
                    else:
                        logger.warning(f"generate_day_schedule_image вернул None для {date_str}")
                except Exception as img_error:
                    logger.error(f"Ошибка при генерации картинки для {date_str}: {img_error}", exc_info=True)
                    img_bytes = None

                if img_bytes:
                    # Добавляем в медиагруппу (подпись только у первой картинки)
                    if len(media_group) == 0:
                        caption = (
                            f"📅 Расписание на неделю для {entity_label}: {escape_html(entity_name)}\n"
                            f"📆 Неделя: {monday.strftime('%d.%m.%Y')} - {(monday + datetime.timedelta(days=5)).strftime('%d.%m.%Y')}"
                        )
                        media_group.append(InputMediaPhoto(media=img_bytes, caption=caption))
                    else:
                        media_group.append(InputMediaPhoto(media=img_bytes))
                    generated_count += 1
                    percent = 50 + int((generated_count / total_days_to_check) * 50)
                    await progress.update(min(95, percent), f"📅 {weekday_name} готов")

                    # Небольшая задержка между генерацией картинок
                    await asyncio.sleep(0.3)
                else:
                    logger.warning(f"Не удалось сгенерировать картинку для {date_str}")

            logger.info(f"Генерация завершена: создано {len(media_group)} картинок из {total_days_to_check} проверенных дней")

            # Отправляем все картинки одним MediaGroup
            logger.info(f"Сгенерировано {len(media_group)} картинок для отправки")
            if media_group:
                # Сохраняем состояние для возврата
                user_data["export_back_mode"] = mode
                user_data["export_back_query"] = entity_name
                user_data["export_back_date"] = (monday + datetime.timedelta(days=5)).strftime("%Y-%m-%d")
                if user_data.get(CTX_SCHEDULE_PAGES):
                    user_data["export_back_pages"] = user_data[CTX_SCHEDULE_PAGES]
                    user_data["export_back_page_index"] = user_data.get(CTX_CURRENT_PAGE_INDEX, 0)

                back_kbd = InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Назад к расписанию", callback_data=CallbackData.BACK_TO_SCHEDULE.value)],
                    [InlineKeyboardButton("🏠 В начало", callback_data=CALLBACK_DATA_BACK_TO_START)]
                ])

                # Отправляем MediaGroup
                try:
                    sent_messages = await update.callback_query.message.reply_media_group(media=media_group)
                    # Добавляем только одно финальное сообщение с информацией
                    if sent_messages:
                        entity_label_text = ENTITY_GROUP_GENITIVE if mode == MODE_STUDENT else ENTITY_TEACHER_GENITIVE
                        await sent_messages[-1].reply_text(
                            f"📅 Расписание на неделю для {entity_label_text}: {escape_html(entity_name)}",
                            reply_markup=back_kbd
                        )
                except Exception as e:
                    logger.error(f"Ошибка при отправке MediaGroup: {e}", exc_info=True)
                    # Если MediaGroup не работает, отправляем по одной
                    logger.info(f"Отправляю {len(media_group)} фото по отдельности")
                    for i, media in enumerate(media_group):
                        try:
                            caption = media.caption if i == 0 else None
                            reply_markup = back_kbd if i == len(media_group) - 1 else None
                            await update.callback_query.message.reply_photo(
                                photo=media.media,
                                caption=caption,
                                reply_markup=reply_markup
                            )
                            await asyncio.sleep(0.5)  # Увеличена задержка для стабильности
                        except Exception as photo_error:
                            logger.error(f"Ошибка при отправке фото {i}: {photo_error}", exc_info=True)

                await progress.finish()
            else:
                await progress.finish("⚠️ Не удалось сгенерировать изображения.", delete_after=0)
                try:
                    await update.callback_query.message.reply_text("⚠️ Не удалось сгенерировать изображения.")
                except Exception as e:
                    logger.debug(f"Ошибка при отправке сообщения: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"❌ Ошибка при генерации картинок по дням: {e}", exc_info=True)
            try:
                await update.callback_query.message.reply_text("❌ Произошла ошибка при генерации картинок. Попробуйте позже.")
            except Exception as reply_error:
                logger.debug(f"Ошибка при отправке сообщения: {reply_error}", exc_info=True)
            try:
                await progress.finish("❌ Ошибка при экспорте.", delete_after=0)
            except Exception as finish_error:
                logger.debug(f"Ошибка при завершении прогресса: {finish_error}", exc_info=True)
        finally:
            logger.info(f"Завершение export_days_images, блокировка будет снята автоматически")


async def export_semester_excel(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Экспорт полного семестра в Excel"""
    if not update.callback_query:
        logger.error("export_semester_excel вызван без callback_query")
        return

    user_id = update.effective_user.id if update.effective_user else "unknown"
    username = update.effective_user.username or "без username" if update.effective_user else "unknown"
    logger.debug(f"📤 [{user_id}] @{username} → Экспорт семестра (Excel), data: {data[:50]}")

    user_data = context.user_data
    mode, query_hash, semester_option = parse_semester_callback_data(data)
    logger.debug(f"export_semester_excel: data={data}, mode={mode}, query_hash={query_hash}, semester_option={semester_option}")
    if not mode or not query_hash:
        logger.error(f"export_semester_excel: Ошибка парсинга данных - mode={mode}, query_hash={query_hash}")
        await safe_answer_callback_query(update.callback_query, "Ошибка данных", show_alert=True)
        return

    export_key = f"export_{mode}_{query_hash}"
    entity_name = user_data.get(export_key)
    logger.debug(f"export_semester_excel: Ищу ключ '{export_key}', найдено: {entity_name}")
    logger.debug(f"export_semester_excel: Доступные ключи export_*: {[k for k in user_data.keys() if k.startswith('export_')]}")
    if not entity_name:
        logger.error(f"export_semester_excel: Entity name не найден для ключа '{export_key}'. Доступные ключи: {[k for k in user_data.keys() if 'export' in k.lower()]}")
        await safe_answer_callback_query(update.callback_query, "Ошибка: данные не найдены. Попробуйте открыть расписание снова.", show_alert=True)
        return

    if not semester_option:
        text = (
            f"📊 <b>Экспорт семестра для {'преподавателя' if mode == 'teacher' else 'группы'}:</b>\n"
            f"<code>{escape_html(entity_name)}</code>\n\n"
            "Выберите семестр:"
        )
        kbd = InlineKeyboardMarkup([
            [InlineKeyboardButton("🧠 Авто (текущий)", callback_data=f"{CALLBACK_DATA_EXPORT_SEMESTER}_{mode}_{query_hash}_auto")],
            [InlineKeyboardButton("🍂 Осенний (сентябрь-декабрь)", callback_data=f"{CALLBACK_DATA_EXPORT_SEMESTER}_{mode}_{query_hash}_autumn")],
            [InlineKeyboardButton("🌸 Весенний (январь-апрель)", callback_data=f"{CALLBACK_DATA_EXPORT_SEMESTER}_{mode}_{query_hash}_spring")],
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"{CALLBACK_DATA_EXPORT_MENU}_{mode}_{query_hash}")],
        ])
        await safe_edit_message_text(update.callback_query, text, reply_markup=kbd, parse_mode=ParseMode.HTML)
        return

    if is_user_busy(user_data):
        logger.warning(f"export_semester_excel: Пользователь занят, но продолжаю (возможно, флаг не сбросился)")
        # Принудительно сбрасываем busy флаг, если он остался установленным
        # Это защита от "зависших" флагов после ошибок
        from ..state_manager import clear_user_busy_state
        clear_user_busy_state(user_data)

    await safe_answer_callback_query(update.callback_query, "Готовлю Excel...")
    progress = ExportProgress(update.callback_query.message)
    await progress.start("⏳ Собираю данные семестра...")
    logger.debug(f"export_semester_excel: Начинаю экспорт семестра для {entity_name} (semester_option={semester_option})")

    # Используем context manager для гарантированного снятия блокировки
    with user_busy_context(user_data):
        try:
            semester_key = None if semester_option == "auto" else semester_option
            start_date, end_date, semester_label = resolve_semester_bounds(semester_key, None, None, None)
            logger.debug(f"export_semester_excel: Семестр: {semester_label}, период: {start_date} - {end_date}")
            await progress.update(20, f"📅 {semester_label}")

            entity_type = API_TYPE_GROUP if mode == "student" else API_TYPE_TEACHER
            logger.debug(f"export_semester_excel: Запрашиваю расписание для {entity_name} (тип: {entity_type})")
            timetable = await fetch_semester_schedule(entity_name, entity_type, start_date, end_date)
            logger.debug(f"export_semester_excel: Получено расписаний: {len(timetable) if timetable else 0}")

            if not timetable:
                logger.warning(f"export_semester_excel: Нет расписания для периода")
                await progress.finish("📅 За период нет занятий.", delete_after=0)
                await update.callback_query.message.reply_text("❌ За выбранный период нет занятий.")
                return

            await progress.update(55, "📘 Формирую Excel...")
            logger.debug(f"export_semester_excel: Начинаю построение Excel")
            workbook, per_group_rows, per_teacher_rows, total_hours, per_group_hours, per_teacher_hours = build_excel_workbook(
                entity_name, mode, semester_label, timetable
            )
            logger.debug(f"export_semester_excel: Excel построен, всего часов: {total_hours:.1f}")

            main_buffer = BytesIO()
            workbook.save(main_buffer)
            main_buffer.seek(0)
            filename = f"{sanitize_filename(entity_name)}_{semester_label.replace(' ', '_')}.xlsx"
            entity_label = ENTITY_TEACHER_GENITIVE if mode == MODE_TEACHER else ENTITY_GROUP_GENITIVE
            caption = (
                f"📊 Семестр ({semester_label}) для {entity_label}: <b>{escape_html(entity_name)}</b>\n"
                f"🕒 Всего часов: {total_hours:.1f}"
            )

            user_data["export_back_mode"] = mode
            user_data["export_back_query"] = entity_name
            export_date = user_data.get(CTX_SELECTED_DATE, datetime.date.today().strftime("%Y-%m-%d"))
            user_data["export_back_date"] = export_date
            if user_data.get(CTX_SCHEDULE_PAGES):
                user_data["export_back_pages"] = user_data[CTX_SCHEDULE_PAGES]
                user_data["export_back_page_index"] = user_data.get(CTX_CURRENT_PAGE_INDEX, 0)

            back_kbd = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад к расписанию", callback_data=CallbackData.BACK_TO_SCHEDULE.value)],
                [InlineKeyboardButton("🏠 В начало", callback_data=CALLBACK_DATA_BACK_TO_START)]
            ])

            await progress.update(80, "📤 Отправляю файл...")
            logger.debug(f"export_semester_excel: Отправляю Excel файл пользователю")
            try:
                await update.callback_query.message.reply_document(
                    document=main_buffer,
                    filename=filename,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=back_kbd
                )
                logger.debug(f"export_semester_excel: Excel файл успешно отправлен")
            except Exception as send_error:
                logger.error(f"export_semester_excel: Ошибка при отправке файла: {send_error}", exc_info=True)
                try:
                    await update.callback_query.message.reply_text(
                        f"❌ Ошибка при отправке файла. Попробуйте позже.",
                        reply_markup=back_kbd
                    )
                except Exception as e:
                    logger.debug(f"Ошибка при отправке сообщения: {e}", exc_info=True)
                try:
                    await progress.finish("❌ Ошибка при отправке файла.", delete_after=0)
                except Exception as e:
                    logger.debug(f"Ошибка при завершении прогресса: {e}", exc_info=True)
                return

            if mode == MODE_TEACHER and per_group_rows:
                zip_bytes, groups_count = build_group_archive_bytes(per_group_rows, per_group_hours, entity_name, semester_label)
                if zip_bytes and groups_count:
                    await progress.update(90, "📦 Упаковываю группы...")
                    zip_stream = BytesIO(zip_bytes)
                    zip_filename = f"{sanitize_filename(entity_name)}_{semester_label.replace(' ', '_')}_groups.zip"
                    zip_caption = f"📁 Отдельные файлы по {groups_count} группам"
                    await update.callback_query.message.reply_document(
                        document=zip_stream,
                        filename=zip_filename,
                        caption=zip_caption,
                        reply_markup=back_kbd
                    )

            await progress.finish("✅ Экспорт готов!")
            logger.debug(f"export_semester_excel: Экспорт успешно завершен")
        except Exception as exc:
            logger.error(f"❌ Ошибка при экспорте семестра: {exc}", exc_info=True)
            try:
                await progress.finish("❌ Ошибка при экспорте.", delete_after=0)
            except Exception as progress_error:
                logger.error(f"Ошибка при завершении прогресса: {progress_error}")
            try:
                await update.callback_query.message.reply_text("❌ Произошла ошибка при экспорте. Попробуйте позже.")
            except Exception as reply_error:
                logger.error(f"Ошибка при отправке сообщения об ошибке: {reply_error}")

