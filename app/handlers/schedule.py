"""
Обработчики расписания
"""
import asyncio
import datetime
import hashlib
import logging
import re
from typing import Optional, Tuple
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardRemove
from telegram.constants import ParseMode, ChatAction
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from ..constants import (
    CTX_MODE, CTX_SELECTED_DATE, CTX_LAST_QUERY, CTX_SCHEDULE_PAGES, CTX_CURRENT_PAGE_INDEX,
    CTX_FOUND_ENTITIES, CTX_DEFAULT_QUERY, CTX_DEFAULT_MODE,
    CTX_AWAITING_DEFAULT_QUERY, CTX_AWAITING_FEEDBACK,
    CALLBACK_DATA_BACK_TO_START, CALLBACK_DATA_SETTINGS_MENU,
    CALLBACK_DATA_PREV_SCHEDULE_PREFIX, CALLBACK_DATA_NEXT_SCHEDULE_PREFIX,
    CALLBACK_DATA_REFRESH_SCHEDULE_PREFIX, CALLBACK_DATA_EXPORT_MENU,
    CALLBACK_DATA_CANCEL_INPUT,
    MODE_STUDENT, API_TYPE_GROUP, API_TYPE_TEACHER,
    ENTITY_GROUP, ENTITY_GROUPS, ENTITY_GROUP_GENITIVE, ENTITY_TEACHER, ENTITY_TEACHER_GENITIVE,
    GROUP_NAME_PATTERN,
)
from ..utils import escape_html
from ..schedule import get_schedule, search_entities, LayoutChangedError
from ..database import db
from ..monitoring import monitor
from ..admin.utils import get_root_admin_id
from .utils import safe_edit_message_text, get_default_reply_keyboard, user_busy_context

logger = logging.getLogger(__name__)


def detect_query_type(text: str) -> Optional[Tuple[str, str]]:
    """
    Определяет тип запроса (группа/преподаватель) по тексту
    Возвращает (mode, text) или None
    """
    text = text.strip()

    # Проверяем, похоже ли на название группы
    if re.match(GROUP_NAME_PATTERN, text, re.IGNORECASE):
        return ("student", text)

    # Проверяем, похоже ли на ФИО преподавателя (два слова с заглавной буквы)
    words = text.split()
    if len(words) >= 2 and all(word[0].isupper() for word in words if word):
        # Может быть преподаватель
        return ("teacher", text)

    return None


async def handle_mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str, for_default: bool = False):
    """
    Обрабатывает выбор режима (студент/преподаватель)
    
    Args:
        update: Обновление от Telegram
        context: Контекст бота
        mode: Режим ('student' или 'teacher')
        for_default: Если True, устанавливает флаг для сохранения как значения по умолчанию
    """
    from .utils import safe_answer_callback_query, safe_edit_message_text
    
    if not update.callback_query:
        return
    
    user_data = context.user_data
    
    # Устанавливаем режим
    user_data[CTX_MODE] = mode
    
    # ВАЖНО: Очищаем CTX_AWAITING_FEEDBACK при выборе режима, чтобы избежать конфликтов
    user_data.pop(CTX_AWAITING_FEEDBACK, None)
    
    # Если это для установки по умолчанию, устанавливаем флаг
    if for_default:
        user_data[CTX_AWAITING_DEFAULT_QUERY] = True
    
    mode_text = ENTITY_GROUP if mode == MODE_STUDENT else ENTITY_TEACHER
    
    # Отвечаем на callback
    await safe_answer_callback_query(update.callback_query, f"Выбран режим: {'Студент' if mode == MODE_STUDENT else 'Преподаватель'}")
    
    # Формируем сообщение
    if for_default:
        text = f"⚙️ <b>Установка по умолчанию</b>\n\n"
        text += f"✅ Вы выбрали режим: <b>{'Студент' if mode == MODE_STUDENT else 'Преподаватель'}</b>\n\n"
        text += f"Теперь введите название {mode_text.lower()}:"
    else:
        text = f"✅ Вы выбрали режим: <b>{'Студент' if mode == MODE_STUDENT else 'Преподаватель'}</b>\n\n"
        text += f"Теперь введите название {mode_text.lower()}:"
    
    if mode == MODE_STUDENT:
        text += "\n\n💡 <i>Например: ИС1-231-ОТ</i>"
    else:
        text += "\n\n💡 <i>Например: Иванов Иван Иванович</i>"
    
    # Добавляем Inline-кнопку "Назад" для удобства
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_DATA_CANCEL_INPUT)]
    ])
    
    # Редактируем сообщение или отправляем новое
    await safe_edit_message_text(update.callback_query, text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


async def safe_get_schedule(date: str, query: str, api_type: str, timeout: float = 15.0, bot=None):
    """Безопасное получение расписания с таймаутом (оптимизировано для быстрых ответов)"""
    try:
        return await asyncio.wait_for(
            get_schedule(date, query, api_type, bot=bot),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        logger.warning(f"Таймаут при получении расписания для {query} на {date}")
        return None, "Превышено время ожидания ответа от сервера. Попробуйте позже."
    except LayoutChangedError:
        # Пробрасываем LayoutChangedError дальше для обработки в handlers
        raise
    except Exception as e:
        logger.error(f"Ошибка при получении расписания: {e}", exc_info=True)
        return None, f"Ошибка при получении расписания: {str(e)}"


async def handle_schedule_search(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    if not update.effective_user:
        logger.error("handle_schedule_search вызван без effective_user")
        return

    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    user_data = context.user_data

    # При входе в поиск расписания сбрасываем режим ожидания отзыва,
    # чтобы ввод группы/преподавателя не перехватывался обработчиком feedback.
    user_data.pop(CTX_AWAITING_FEEDBACK, None)

    # Используем context manager для автоматического управления блокировкой
    async with user_busy_context(user_data):
        if not user_data.get(CTX_MODE):
            logger.warning(f"⚠️ [{user_id}] @{username} → Попытка поиска без выбора режима")
            await update.message.reply_text("Сначала выберите режим через /start.")
            return

        mode = user_data[CTX_MODE]
        mode_text = ENTITY_GROUP if mode == MODE_STUDENT else ENTITY_TEACHER

        # Проверяем, есть ли сохраненные варианты из предыдущего поиска
        saved_found = user_data.get(CTX_FOUND_ENTITIES, [])
        if saved_found:
            # Проверяем точное совпадение (без учета регистра)
            exact_match = next((entity for entity in saved_found if entity.lower() == text.lower()), None)
            if exact_match:
                logger.debug(f"✅ [{user_id}] @{username} → Точное совпадение с сохраненным вариантом: '{exact_match}'")
                # Очищаем сохраненные варианты
                user_data.pop(CTX_FOUND_ENTITIES, None)
                # Устанавливаем стандартную клавиатуру
                reply_keyboard = get_default_reply_keyboard()
                s_name = "группа" if mode == MODE_STUDENT else "преподаватель"
                verb = "Найдена" if mode == MODE_STUDENT else "Найден"
                await update.message.reply_text(
                    f"{verb} {s_name}: {exact_match}.\nЗагружаю...",
                    reply_markup=reply_keyboard
                )
                # Сохраняем в историю поиска
                db.save_search_history(user_id, exact_match, mode)
                await fetch_and_display_schedule(update, context, exact_match)
                return

        logger.debug(f"🔍 [{user_id}] @{username} → Ищет {mode_text}: '{text}'")

        await update.message.reply_chat_action(ChatAction.TYPING)
        api_type = API_TYPE_GROUP if mode == MODE_STUDENT else API_TYPE_TEACHER
        p_name, s_name, verb, not_found = (ENTITY_GROUPS, "группа", "Найдена", "Группы не найдены.") if mode == MODE_STUDENT else ("преподаватели", "преподаватель", "Найден", "Преподаватели не найдены.")

        found, err = await search_entities(text, api_type)

        if found:
            logger.debug(f"✅ [{user_id}] Найдено {len(found)} {p_name} для запроса '{text}'")
            if len(found) == 1:
                logger.debug(f"📅 [{user_id}] Загружаю расписание для: {found[0]}")
                # Сохраняем в историю поиска
                db.save_search_history(user_id, found[0], mode)
        else:
            logger.warning(f"❌ [{user_id}] {not_found} для запроса '{text}': {err}")

        if err or not found:
            # Очищаем сохраненные варианты при ошибке
            user_data.pop(CTX_FOUND_ENTITIES, None)
            # Улучшенное сообщение об ошибке с примерами
            error_text = f"❌ <b>{not_found}</b>\n\n"
            error_text += "💡 <b>Попробуйте:</b>\n"
            error_text += f"   • Ввести первые 3-4 буквы: <code>{text[:4] if len(text) >= 4 else text}</code>\n"
            if mode == MODE_STUDENT:
                error_text += "   • Проверить формат: <code>ИС1-231-ОТ</code>\n"
            else:
                error_text += "   • Ввести фамилию: <code>Иванов</code>\n"
            error_text += "   • Использовать точное название"
            # Устанавливаем стандартную клавиатуру
            reply_keyboard = get_default_reply_keyboard()
            error_kbd = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В начало", callback_data=CALLBACK_DATA_BACK_TO_START)]])
            await update.message.reply_text(error_text, reply_markup=reply_keyboard, parse_mode=ParseMode.HTML)
            await update.message.reply_text("💡 Используйте кнопки ниже для навигации:", reply_markup=error_kbd)
            return

        # Устанавливаем стандартную клавиатуру
        reply_keyboard = get_default_reply_keyboard()

        if len(found) == 1:
            # Очищаем сохраненные варианты при успешном поиске одной группы
            user_data.pop(CTX_FOUND_ENTITIES, None)
            await update.message.reply_text(
                f"{verb} {s_name}: {found[0]}.\nЗагружаю...",
                reply_markup=reply_keyboard
            )
            await fetch_and_display_schedule(update, context, found[0])
        else:
            # Сохраняем найденные варианты для последующей проверки
            from ..constants import MAX_SEARCH_RESULTS_DISPLAY
            user_data[CTX_FOUND_ENTITIES] = found[:MAX_SEARCH_RESULTS_DISPLAY]
            kbd = [[KeyboardButton(e)] for e in found[:MAX_SEARCH_RESULTS_DISPLAY]]
            msg = (
                f"Найдено несколько {p_name}. Выберите вариант:" 
                if len(found) <= MAX_SEARCH_RESULTS_DISPLAY 
                else f"Найдено слишком много ({len(found)}). Показаны первые {MAX_SEARCH_RESULTS_DISPLAY}:"
            )
            await update.message.reply_text(
                msg,
                reply_markup=ReplyKeyboardMarkup(kbd, resize_keyboard=True, one_time_keyboard=True)
            )


async def fetch_and_display_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str, msg_to_edit: Optional[Message] = None):
    if not update.effective_user:
        logger.error("fetch_and_display_schedule вызван без effective_user")
        return

    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    user_data = context.user_data

    # Любой прямой заход в показ расписания должен сбрасывать режим отзыва.
    user_data.pop(CTX_AWAITING_FEEDBACK, None)

    # Используем context manager для автоматического управления блокировкой
    async with user_busy_context(user_data):
        mode = user_data.get(CTX_MODE)
        api_type = API_TYPE_GROUP if mode == MODE_STUDENT else API_TYPE_TEACHER
        date = user_data.setdefault(CTX_SELECTED_DATE, datetime.date.today().strftime("%Y-%m-%d"))
        user_data[CTX_LAST_QUERY] = query

        mode_text = ENTITY_GROUP_GENITIVE if mode == MODE_STUDENT else ENTITY_TEACHER_GENITIVE
        logger.debug(f"📥 [{user_id}] @{username} → Загружаю расписание {mode_text} '{query}' на {date}")

        # Показываем индикатор загрузки
        if update.callback_query:
            try:
                await safe_edit_message_text(update.callback_query, "⏳ Загружаю расписание...", reply_markup=None)
            except Exception as e:
                logger.debug(f"Ошибка при редактировании сообщения: {e}", exc_info=True)

        try:
            # Передаем bot для мониторинга
            pages, err = await safe_get_schedule(date, query, api_type, bot=context.bot)
        except LayoutChangedError as e:
            # ВОТ ОНО! Хендлер поймал критическую ошибку
            # Алерт уже отправлен в get_schedule, если был передан bot
            monitor.log_user_request(user_id, query, api_type, date, success=False)
            reply_keyboard = get_default_reply_keyboard()
            target = msg_to_edit or update.effective_message
            if target:
                await target.reply_text("🔧 Техническая проблема с сайтом университета. Администратор уже уведомлен.", reply_markup=reply_keyboard)
            return

        if pages:
            logger.debug(f"✅ [{user_id}] Получено расписание: {len(pages)} страниц")
            monitor.log_user_request(user_id, query, api_type, date, success=True)
        else:
            logger.warning(f"❌ [{user_id}] Ошибка получения расписания: {err}")
            monitor.log_user_request(user_id, query, api_type, date, success=False)

        if err or not pages:
            reply_keyboard = get_default_reply_keyboard()
            target = msg_to_edit or update.effective_message
            if target:
                await target.reply_text(err or "Не удалось получить расписание.", reply_markup=reply_keyboard)
            return

        if "Расписание не найдено" in pages[0]:
            kbd = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В начало", callback_data=CALLBACK_DATA_BACK_TO_START)]])
            target = msg_to_edit or (update.callback_query and update.callback_query.message)
            if target:
                try:
                    await target.edit_text(pages[0], reply_markup=kbd, parse_mode=ParseMode.HTML)
                except BadRequest as e:
                    if "no text in the message" in str(e).lower():
                        # Сообщение содержит фото/документ, отправляем новое
                        await target.reply_text(pages[0], reply_markup=kbd, parse_mode=ParseMode.HTML)
                    else:
                        raise
            else:
                await update.effective_message.reply_text(pages[0], reply_markup=kbd, parse_mode=ParseMode.HTML)
            return

        user_data[CTX_SCHEDULE_PAGES], user_data[CTX_CURRENT_PAGE_INDEX] = pages, 0
        await send_schedule_with_pagination(update, context, msg_to_edit=msg_to_edit)

        # Логируем активность
        db.log_activity(user_id, "view_schedule", f"mode={mode}, query={query}, date={date}")


async def send_schedule_with_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE, msg_to_edit: Optional[Message] = None):
    user_data = context.user_data
    pages, idx, mode, query = user_data.get(CTX_SCHEDULE_PAGES), user_data.get(CTX_CURRENT_PAGE_INDEX, 0), user_data.get(CTX_MODE), user_data.get(CTX_LAST_QUERY)

    # Проверяем, что есть страницы и запрос
    if not pages or len(pages) == 0:
        logger.warning("Нет страниц для отображения")
        kbd = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В начало", callback_data=CALLBACK_DATA_BACK_TO_START)]])
        target = msg_to_edit or (update.callback_query and update.callback_query.message) or update.effective_message
        if target:
            await target.reply_text("Расписание не найдено.", reply_markup=kbd)
        return

    if not query:
        logger.warning("Нет запроса для отображения")
        kbd = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В начало", callback_data=CALLBACK_DATA_BACK_TO_START)]])
        target = msg_to_edit or (update.callback_query and update.callback_query.message) or update.effective_message
        if target:
            await target.reply_text("Запрос не найден.", reply_markup=kbd)
        return

    # Проверяем mode
    if not mode:
        mode = MODE_STUDENT  # Значение по умолчанию
    user_data[CTX_MODE] = mode

    # Проверяем индекс страницы
    if idx < 0:
        idx = 0
    if idx >= len(pages):
        idx = len(pages) - 1
    user_data[CTX_CURRENT_PAGE_INDEX] = idx

    # Логирование только если есть update с пользователем
    if update.effective_user:
        user_id = update.effective_user.id
        username = update.effective_user.username or "без username"
        logger.debug(f"📋 [{user_id}] @{username} → Отображение расписания '{query}' (страница {idx + 1}/{len(pages)})")

    # Улучшенное форматирование расписания (убрано дублирование)
    section_emoji = "🎓" if mode == MODE_STUDENT else "🧑‍🏫"
    entity_text = "группы" if mode == MODE_STUDENT else "преподавателя"
    header = f"{section_emoji} <b>Расписание {entity_text}</b>\n"
    header += f"👤 <b>{escape_html(query)}</b>\n"
    header += f"📄 Страница {idx + 1} из {len(pages)}\n\n"

    # Проверяем длину сообщения (Telegram ограничивает до 4096 символов)
    schedule_content = pages[idx]
    text = header + schedule_content

    # Если сообщение слишком длинное, обрезаем его и добавляем предупреждение
    MAX_MESSAGE_LENGTH = 4000  # Оставляем запас для HTML тегов
    if len(text) > MAX_MESSAGE_LENGTH:
        # Обрезаем содержимое расписания, оставляя место для заголовка и предупреждения
        available_length = MAX_MESSAGE_LENGTH - len(header) - 100  # 100 символов для предупреждения
        schedule_content = schedule_content[:available_length] + "\n\n⚠️ <i>Расписание обрезано из-за ограничения длины сообщения</i>"
        text = header + schedule_content
        logger.warning(f"Сообщение слишком длинное ({len(text)} символов), обрезано до {MAX_MESSAGE_LENGTH}")

    # Создаем кнопки навигации

    # Первая строка: навигация по страницам
    nav_row = []
    if idx > 0:
        prev_callback = f"{CALLBACK_DATA_PREV_SCHEDULE_PREFIX}{mode}_{idx-1}"
        nav_row.append(InlineKeyboardButton("⬅️ Предыдущая", callback_data=prev_callback))

    refresh_callback = f"{CALLBACK_DATA_REFRESH_SCHEDULE_PREFIX}{mode}_{idx}"
    nav_row.append(InlineKeyboardButton("🔄 Обновить", callback_data=refresh_callback))

    if idx < len(pages) - 1:
        next_callback = f"{CALLBACK_DATA_NEXT_SCHEDULE_PREFIX}{mode}_{idx+1}"
        nav_row.append(InlineKeyboardButton("Следующая ➡️", callback_data=next_callback))

    kbd_rows = [nav_row] if nav_row else []

    # Вторая строка: экспорт
    if query:
        query_hash = hashlib.md5(query.encode('utf-8')).hexdigest()[:12]
        user_data[f"export_{mode}_{query_hash}"] = query
        kbd_rows.append([InlineKeyboardButton("📤 Экспорт", callback_data=f"{CALLBACK_DATA_EXPORT_MENU}_{mode}_{query_hash}")])

    # Третья строка: быстрые действия
    action_row = []
    # Проверяем, не установлена ли уже эта группа/преподаватель по умолчанию
    current_default = user_data.get(CTX_DEFAULT_QUERY)
    current_default_mode = user_data.get(CTX_DEFAULT_MODE)
    is_already_default = (current_default and current_default.lower() == query.lower() and
                         current_default_mode == mode)

    if not is_already_default:
        # Сохраняем данные для установки по умолчанию
        user_data[f"set_default_query_{query_hash}"] = query
        user_data[f"set_default_mode_{query_hash}"] = mode
        action_row.append(InlineKeyboardButton("⭐ Установить по умолчанию",
                                               callback_data=f"set_default_from_schedule_{mode}_{query_hash}"))
    action_row.append(InlineKeyboardButton("⚙️ Настройки", callback_data=CALLBACK_DATA_SETTINGS_MENU))
    if action_row:
        kbd_rows.append(action_row)

    # Последняя строка: возврат в начало
    kbd_rows.append([InlineKeyboardButton("🏠 В начало", callback_data=CALLBACK_DATA_BACK_TO_START)])
    kbd = InlineKeyboardMarkup(kbd_rows)

    try:
        target = msg_to_edit or (update.callback_query and update.callback_query.message)
        if target:
            try:
                await target.edit_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
            except BadRequest as e:
                if "no text in the message" in str(e).lower():
                    # Сообщение содержит фото/документ, отправляем новое
                    await target.reply_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
                elif "Message is not modified" not in str(e):
                    logger.error(f"Ошибка при обновлении расписания: {e}")
        else:
            await update.effective_message.reply_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
    except BadRequest as e:
        if "Message is not modified" not in str(e) and "no text in the message" not in str(e).lower():
            logger.error(f"Ошибка при обновлении расписания: {e}")


async def schedule_navigation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    query_obj, data = update.callback_query, update.callback_query.data
    try:
        action, mode, page_str = data.split("_", 2)
        context.user_data[CTX_MODE] = mode
        if action + "_" == CALLBACK_DATA_REFRESH_SCHEDULE_PREFIX:
            logger.info(f"🔄 [{user_id}] @{username} → Обновление расписания")
            await query_obj.answer("🔄 Обновляю...")
            last_query = context.user_data.get(CTX_LAST_QUERY) or context.user_data.get(CTX_DEFAULT_QUERY)
            if not last_query:
                logger.warning(f"⚠️ [{user_id}] @{username} → Обновление без сохраненного запроса")
                await query_obj.answer("Не найден предыдущий запрос. Введите группу или преподавателя заново.", show_alert=True)
                return
            await fetch_and_display_schedule(update, context, last_query)
        else:
            page_num = int(page_str)
            direction = "← Назад" if action == "prev" else "→ Вперед"
            logger.info(f"📄 [{user_id}] @{username} → Навигация: {direction} (страница {page_num + 1})")
            context.user_data[CTX_CURRENT_PAGE_INDEX] = page_num
            await send_schedule_with_pagination(update, context)
    except Exception as e:
        logger.error(f"❌ [{user_id}] Ошибка навигации: {e}", exc_info=True)
        await query_obj.answer("Ошибка навигации.", show_alert=True)

