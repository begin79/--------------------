"""
Обработчики текстовых сообщений
"""
import asyncio
import hashlib
import logging
from dateutil.parser import parse as parse_date
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ..constants import (
    CTX_MODE, CTX_SELECTED_DATE, CTX_AWAITING_MANUAL_DATE, CTX_LAST_QUERY,
    CTX_AWAITING_DEFAULT_QUERY, CTX_DEFAULT_QUERY, CTX_DEFAULT_MODE,
    CALLBACK_DATA_MODE_STUDENT, CALLBACK_DATA_MODE_TEACHER, CALLBACK_DATA_BACK_TO_START,
    CALLBACK_DATA_SETTINGS_MENU, CALLBACK_DATA_CANCEL_INPUT, CALLBACK_DATA_CONFIRM_MODE,
    CALLBACK_DATA_DATE_TODAY, CALLBACK_DATA_DATE_TOMORROW,
    MODE_STUDENT, ENTITY_GROUP, ENTITY_TEACHER, CallbackData,
)
from ..admin.utils import is_bot_enabled, get_maintenance_message
from ..state_manager import (
    clear_temporary_states, safe_get_user_data, is_user_busy, set_user_busy
)
from ..utils import escape_html
from ..schedule import search_entities
from ..database import db
from .start import start_command
from .settings import settings_menu_callback
from .feedback import process_feedback_message
from .admin_dialogs import process_user_reply_to_admin_message
from .schedule import handle_schedule_search, detect_query_type, safe_get_schedule, send_schedule_with_pagination
from .utils import load_user_data_from_db, get_default_reply_keyboard, safe_answer_callback_query, user_busy_context
from .admin_dialogs import get_admin_reply_states
from .notifications import schedule_daily_notifications

logger = logging.getLogger(__name__)


async def _apply_default_selection(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chosen: str,
    mode: str,
    source: str = "message",
):
    """Финализирует установку расписания по умолчанию и включает уведомления"""
    from ..constants import (
        CTX_DEFAULT_QUERY, CTX_DEFAULT_MODE, CTX_NOTIFICATION_TIME, CTX_DAILY_NOTIFICATIONS,
        DEFAULT_NOTIFICATION_TIME
    )
    from .utils import save_user_data_to_db, get_default_reply_keyboard

    user_data = context.user_data
    user_id = update.effective_user.id if update.effective_user else None
    username = update.effective_user.username if update.effective_user else None
    first_name = update.effective_user.first_name if update.effective_user else None
    last_name = update.effective_user.last_name if update.effective_user else None

    user_data[CTX_DEFAULT_QUERY] = chosen
    user_data[CTX_DEFAULT_MODE] = mode
    if not user_data.get(CTX_NOTIFICATION_TIME):
        user_data[CTX_NOTIFICATION_TIME] = DEFAULT_NOTIFICATION_TIME

    notifications_were_enabled = bool(user_data.get(CTX_DAILY_NOTIFICATIONS, False))
    user_data[CTX_DAILY_NOTIFICATIONS] = True

    save_user_data_to_db(
        user_id=user_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        user_data=user_data,
    )
    if user_id:
        db.log_activity(user_id, "set_default_query", f"mode={mode}, query={chosen}")
        if not notifications_were_enabled:
            db.log_activity(user_id, "auto_enable_notifications", f"mode={mode}")

    chat_id = update.effective_chat.id if update.effective_chat else user_id
    schedule_daily_notifications(context, chat_id, user_data)

    # Добавляем пользователя в список активных для проверки изменений расписания
    if user_id:
        if 'active_users' not in context.bot_data:
            context.bot_data['active_users'] = set()
        if 'users_data_cache' not in context.bot_data:
            context.bot_data['users_data_cache'] = {}

        context.bot_data['active_users'].add(user_id)
        # Обновляем кеш данных пользователя для проверки изменений
        context.bot_data['users_data_cache'][user_id] = {
            CTX_DEFAULT_QUERY: chosen,
            CTX_DEFAULT_MODE: mode,
            CTX_DAILY_NOTIFICATIONS: True,
            CTX_NOTIFICATION_TIME: user_data.get(CTX_NOTIFICATION_TIME, DEFAULT_NOTIFICATION_TIME)
        }

    time_str = user_data.get(CTX_NOTIFICATION_TIME, DEFAULT_NOTIFICATION_TIME)
    notif_line = (
        f"🔔 Ежедневные уведомления уже были включены на {time_str}."
        if notifications_were_enabled
        else f"🔔 Ежедневные уведомления автоматически включены на {time_str}."
    )
    reply_keyboard = get_default_reply_keyboard()
    info_text = (
        f"✅ Установлено по умолчанию: <b>{escape_html(chosen)}</b>\n"
        f"{notif_line}"
    )

    if source == "message" and update.message:
        await update.message.reply_text(
            info_text,
            reply_markup=reply_keyboard,
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.effective_chat.send_message(
            info_text,
            reply_markup=reply_keyboard,
            parse_mode=ParseMode.HTML,
        )


async def _check_bot_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверяет статус бота. Возвращает True если бот доступен."""
    from ..admin.utils import is_admin
    user_id = update.effective_user.id
    is_admin_user = is_admin(user_id)
    if not is_admin_user and not is_bot_enabled():
        maintenance_msg = get_maintenance_message()
        await update.message.reply_text(maintenance_msg)
        return False
    return True


async def _handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    """Обрабатывает ответ администратору. Возвращает True если сообщение обработано."""
    user_data = context.user_data
    user_id = update.effective_user.id

    pending_admin_id = safe_get_user_data(user_data, "pending_admin_reply")
    if not pending_admin_id:
        reply_states = get_admin_reply_states(context)
        state = reply_states.get(user_id)
        if state and state.get("admin_id"):
            pending_admin_id = state["admin_id"]
            user_data["pending_admin_reply"] = pending_admin_id

    if pending_admin_id:
        lowered = text.lower()
        if lowered in {"отмена", "cancel", "/cancel"}:
            user_data.pop("pending_admin_reply", None)
            reply_states = get_admin_reply_states(context)
            reply_states.pop(user_id, None)
            await update.message.reply_text("✅ Ответ администратору отменён.")
        else:
            try:
                await process_user_reply_to_admin_message(update, context, pending_admin_id, text)
            except Exception as e:
                logger.error(f"Ошибка при обработке ответа администратору: {e}", exc_info=True)
                await update.message.reply_text("❌ Произошла ошибка при отправке ответа. Попробуйте позже.")
                clear_temporary_states(user_data)
        return True
    return False


async def _handle_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    """Обрабатывает отзыв. Возвращает True если сообщение обработано."""
    try:
        if await process_feedback_message(update, context, text):
            return True
    except Exception as e:
        logger.error(f"Ошибка при обработке отзыва: {e}", exc_info=True)
        clear_temporary_states(context.user_data)
    return False


async def _handle_commands(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    """Обрабатывает команды. Возвращает True если сообщение обработано."""
    user_data = context.user_data

    # Команда /start или "Старт"
    if text == "/start" or text.startswith("/start") or text.strip().lower() == "старт":
        try:
            await start_command(update, context)
        except Exception as e:
            logger.error(f"Ошибка в start_command: {e}", exc_info=True)
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте команду /start ещё раз.")
            clear_temporary_states(user_data)
        return True

    # Обработка кнопки "Настройки"
    if text.strip().lower() == "настройки":
        try:
            await settings_menu_callback(update, context)
        except Exception as e:
            logger.error(f"Ошибка в settings_menu_callback: {e}", exc_info=True)
            await update.message.reply_text("❌ Произошла ошибка при открытии настроек.")
            clear_temporary_states(user_data)
        return True

    # Обработка кнопки "Меню" (обратная совместимость)
    if text.strip().lower() == "меню":
        try:
            await start_command(update, context)
        except Exception as e:
            logger.error(f"Ошибка в start_command (меню): {e}", exc_info=True)
            await update.message.reply_text("❌ Произошла ошибка. Попробуйте команду /start ещё раз.")
            clear_temporary_states(user_data)
        return True

    return False


async def _handle_cold_start(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    """Обрабатывает умный холодный старт. Возвращает True если сообщение обработано."""
    user_data = context.user_data

    # Умный холодный старт: если режим не выбран, пытаемся определить по тексту
    if not safe_get_user_data(user_data, CTX_MODE) and not safe_get_user_data(user_data, CTX_AWAITING_DEFAULT_QUERY) and not safe_get_user_data(user_data, CTX_AWAITING_MANUAL_DATE):
        # Проверяем, есть ли у пользователя установленная группа/преподаватель
        has_default_query = bool(user_data.get(CTX_DEFAULT_QUERY))

        detected = detect_query_type(text)
        if detected:
            mode, query_text = detected
            mode_text = ENTITY_GROUP if mode == MODE_STUDENT else ENTITY_TEACHER
            user_data[CTX_MODE] = mode

            # Если у пользователя нет установленной группы/преподавателя, предлагаем сначала выбрать режим через /start
            if not has_default_query:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎓 Я студент", callback_data=CALLBACK_DATA_MODE_STUDENT)],
                    [InlineKeyboardButton("🧑‍🏫 Я преподаватель", callback_data=CALLBACK_DATA_MODE_TEACHER)],
                    [InlineKeyboardButton("❓ Не знаю", callback_data=CallbackData.HELP_COMMAND_INLINE.value)]
                ])
                await update.message.reply_text(
                    f"🔍 Я вижу, что вы ищете {mode_text}: <b>{escape_html(query_text)}</b>\n\n"
                    f"Для начала работы с ботом выберите, кто вы:",
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )
                return True
            else:
                # Для существующих пользователей предлагаем подтвердить выбор
                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Да, это правильный режим", callback_data=f"{CALLBACK_DATA_CONFIRM_MODE}{mode}_{hashlib.md5(query_text.encode()).hexdigest()[:8]}"),
                        InlineKeyboardButton("❌ Нет, выбрать другой", callback_data=CALLBACK_DATA_BACK_TO_START)
                    ],
                    [InlineKeyboardButton("🔍 Ввести другой запрос", callback_data=CALLBACK_DATA_BACK_TO_START)]
                ])
                user_data[f"pending_query_{mode}"] = query_text
                await update.message.reply_text(
                    f"🔍 Я определил, что вы ищете {mode_text}: <b>{escape_html(query_text)}</b>\n\n"
                    f"Правильно?",
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )
                return True
        else:
            # Не удалось определить, предлагаем выбрать режим
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎓 Я студент", callback_data=CALLBACK_DATA_MODE_STUDENT)],
                [InlineKeyboardButton("🧑‍🏫 Я преподаватель", callback_data=CALLBACK_DATA_MODE_TEACHER)],
                [InlineKeyboardButton("❓ Не знаю", callback_data=CallbackData.HELP_COMMAND_INLINE.value)]
            ])
            await update.message.reply_text(
                "🤔 Я не могу определить, что вы ищете. Пожалуйста, выберите режим:",
                reply_markup=keyboard
            )
            return True

    return False


async def _handle_input_states(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    """Обрабатывает состояния ожидания ввода. Возвращает True если сообщение обработано."""
    user_data = context.user_data

    if safe_get_user_data(user_data, CTX_AWAITING_DEFAULT_QUERY):
        try:
            await handle_default_query_input(update, context, text)
        except Exception as e:
            logger.error(f"Ошибка в handle_default_query_input: {e}", exc_info=True)
            await update.message.reply_text("❌ Произошла ошибка при обработке запроса.")
            clear_temporary_states(user_data)
        return True
    elif safe_get_user_data(user_data, CTX_AWAITING_MANUAL_DATE):
        try:
            await handle_manual_date_input(update, context, text)
        except Exception as e:
            logger.error(f"Ошибка в handle_manual_date_input: {e}", exc_info=True)
            await update.message.reply_text("❌ Произошла ошибка при обработке даты.")
            clear_temporary_states(user_data)
        return True

    return False


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик текстовых сообщений с улучшенной обработкой ошибок и состояний.
    Использует цепочку обработчиков для лучшей читаемости и поддерживаемости.
    """
    if not update.effective_user or not update.message:
        logger.error("handle_text_message вызван без effective_user или message")
        return

    user_data = context.user_data
    user_id = update.effective_user.id

    try:
        # 1. Проверка статуса бота
        if not await _check_bot_status(update, context):
            return

        username = update.effective_user.username or "без username"
        first_name = update.effective_user.first_name or "без имени"
        text = update.message.text.strip() if update.message.text else ""

        logger.info(f"💬 [{user_id}] @{username} ({first_name}) → Текстовое сообщение: '{text[:50]}{'...' if len(text) > 50 else ''}'")

        # 2. Обработка ответа администратору
        if await _handle_admin_reply(update, context, text):
            return

        # 3. Обработка отзыва
        if await _handle_feedback(update, context, text):
            return

        # 4. Проверка занятости
        if is_user_busy(user_data):
            await update.message.reply_text("⏳ Пожалуйста, подождите, я обрабатываю предыдущий запрос...")
            return

        # 5. Обработка команд
        if await _handle_commands(update, context, text):
            return

        # 6. Загружаем данные из БД при первом обращении
        if not safe_get_user_data(user_data, CTX_DEFAULT_QUERY):
            try:
                load_user_data_from_db(user_id, user_data)
            except Exception as e:
                logger.error(f"Ошибка при загрузке данных пользователя: {e}", exc_info=True)
                # Продолжаем работу, даже если не удалось загрузить данные

        # 7. Умный холодный старт
        if await _handle_cold_start(update, context, text):
            return

        # 8. Обработка состояний ожидания ввода
        if await _handle_input_states(update, context, text):
            return

        # 9. Поиск расписания (fallback)
        try:
            await handle_schedule_search(update, context, text)
        except Exception as e:
            logger.error(f"Ошибка в handle_schedule_search: {e}", exc_info=True)
            await update.message.reply_text("❌ Произошла ошибка при поиске расписания.")
            clear_temporary_states(user_data)

    except Exception as e:
        # Общая обработка ошибок для всей функции
        logger.error(f"Критическая ошибка в handle_text_message: {e}", exc_info=True)
        try:
            await update.message.reply_text("❌ Произошла критическая ошибка. Попробуйте позже или используйте /start.")
        except Exception as e:
            logger.debug(f"Ошибка при обновлении прогресса: {e}", exc_info=True)
        clear_temporary_states(user_data)


async def handle_default_query_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    from ..constants import (
        CTX_MODE, CTX_AWAITING_DEFAULT_QUERY, API_TYPE_GROUP, API_TYPE_TEACHER,
        MODE_STUDENT, ENTITY_GROUP, ENTITY_TEACHER, CALLBACK_DATA_SETTINGS_MENU,
        CALLBACK_DATA_BACK_TO_START
    )
    from .utils import safe_answer_callback_query

    if not update.effective_user:
        logger.error("handle_default_query_input вызван без effective_user")
        return

    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    user_data = context.user_data

    lowered = text.strip().lower()
    if lowered in {"отмена", "cancel", "/cancel"}:
        user_data.pop(CTX_AWAITING_DEFAULT_QUERY, None)
        await update.message.reply_text("❌ Установка по умолчанию отменена.")
        await settings_menu_callback(update, context)
        return

    # Проверяем, что режим установлен
    mode = user_data.get(CTX_MODE)
    if not mode:
        logger.error(f"❌ [{user_id}] CTX_MODE не установлен в user_data при установке по умолчанию")
        user_data.pop(CTX_AWAITING_DEFAULT_QUERY, None)
        kbd = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_DATA_SETTINGS_MENU)],
            [InlineKeyboardButton("🏠 В начало", callback_data=CALLBACK_DATA_BACK_TO_START)]
        ])
        await update.message.reply_text(
            "❌ Ошибка: режим не установлен. Пожалуйста, выберите режим через /start.",
            reply_markup=kbd
        )
        return

    # Используем context manager для автоматического управления блокировкой
    with user_busy_context(user_data):
        mode_text = ENTITY_GROUP if mode == MODE_STUDENT else ENTITY_TEACHER
        logger.info(f"⚙️ [{user_id}] @{username} → Устанавливает {mode_text} по умолчанию: '{text}'")

        api_type = API_TYPE_GROUP if mode == MODE_STUDENT else API_TYPE_TEACHER
        found, err = await search_entities(text, api_type)

        if found:
            logger.debug(f"✅ [{user_id}] Найдено {len(found)} вариантов для '{text}'")
        else:
            logger.warning(f"❌ [{user_id}] Не найдено вариантов для '{text}': {err}")

        if err or not found:
            kbd = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_DATA_SETTINGS_MENU)],
                [InlineKeyboardButton("🏠 В начало", callback_data=CALLBACK_DATA_BACK_TO_START)]
            ])
            await update.message.reply_text("Не удалось найти. Попробуйте еще раз.", reply_markup=kbd)
            return

        match = next((e for e in found if e.lower() == text.lower()), None)
        if match:
            logger.info(f"✅ [{user_id}] @{username} → Установлено по умолчанию: '{match}' (режим: {mode_text})")
            user_data.pop(CTX_AWAITING_DEFAULT_QUERY, None)

            # Проверяем, новый ли это пользователь (первый запуск)
            is_new_user = user_data.get(CTX_DEFAULT_QUERY) is None

            await _apply_default_selection(update, context, match, mode, source="message")

            if is_new_user:
                # Для новых пользователей показываем сообщение об успешной установке и настройки
                success_msg = await update.message.reply_text(
                    f"✅ Вы установили {mode_text}: <b>{escape_html(match)}</b>\n\n"
                    f"Теперь вы будете получать ежедневные уведомления о расписании.",
                    parse_mode=ParseMode.HTML
                )
                # Удаляем сообщение через 5 секунд
                from .utils import _delete_message_after_delay
                asyncio.create_task(_delete_message_after_delay(context.bot, success_msg.chat_id, success_msg.message_id, 5.0))
                # Показываем настройки для удобства дальнейшей настройки
                await settings_menu_callback(update, context)
            else:
                await settings_menu_callback(update, context)
            return

        # Если точного совпадения нет, показываем варианты в ReplyKeyboard (как при обычном поиске)
        max_options = 20
        options = found[:max_options]
        hint = "🔎 Найдено несколько вариантов. Выберите нужный текстом:"
        if len(found) > max_options:
            hint = f"🔎 Найдено слишком много ({len(found)}). Показаны первые {max_options}:"

        option_rows = [[KeyboardButton(option)] for option in options]
        option_rows.append([KeyboardButton("Отмена")])

        await update.message.reply_text(
            hint,
            reply_markup=ReplyKeyboardMarkup(option_rows, resize_keyboard=True, one_time_keyboard=True)
        )


async def handle_manual_date_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    from ..constants import CTX_SELECTED_DATE, CTX_AWAITING_MANUAL_DATE, CTX_MODE, CTX_LAST_QUERY, CALLBACK_DATA_CANCEL_INPUT, CALLBACK_DATA_BACK_TO_START
    from .schedule import fetch_and_display_schedule

    user_data = context.user_data
    # Устанавливаем стандартную клавиатуру
    reply_keyboard = get_default_reply_keyboard()
    try:
        date_obj = parse_date(text, dayfirst=True).date()
        user_data[CTX_SELECTED_DATE] = date_obj.strftime("%Y-%m-%d")
        user_data.pop(CTX_AWAITING_MANUAL_DATE)
        await update.message.reply_text(f"📅 Дата установлена: {date_obj.strftime('%d.%m.%Y')}.", reply_markup=reply_keyboard)
        if user_data.get(CTX_MODE) and user_data.get(CTX_LAST_QUERY):
            msg = await update.message.reply_text("Обновляю расписание...")
            await fetch_and_display_schedule(update, context, user_data[CTX_LAST_QUERY], msg_to_edit=msg)
    except (ValueError, TypeError):
        kbd = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отмена", callback_data=CALLBACK_DATA_CANCEL_INPUT)],
            [InlineKeyboardButton("🏠 В начало", callback_data=CALLBACK_DATA_BACK_TO_START)]
        ])
        await update.message.reply_text("Не могу распознать дату. Попробуйте формат ДД.ММ.ГГГГ или ГГГГ-ММ-ДД.", reply_markup=kbd)


async def handle_quick_date_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Обработка быстрых кнопок 'Сегодня/Завтра' из главного меню или расписания"""
    import datetime
    from ..constants import (
        CTX_SELECTED_DATE, CTX_MODE, CTX_LAST_QUERY, CTX_DEFAULT_QUERY, CTX_DEFAULT_MODE,
        CTX_SCHEDULE_PAGES, CTX_CURRENT_PAGE_INDEX, MODE_STUDENT, API_TYPE_GROUP, API_TYPE_TEACHER,
        CALLBACK_DATA_DATE_TODAY, CALLBACK_DATA_DATE_TOMORROW
    )
    from .start import start_command
    from .schedule import safe_get_schedule, send_schedule_with_pagination

    user_data = context.user_data

    # Определяем дату
    if "today" in data:
        date = datetime.date.today()
        date_text = "сегодня"
    else:
        date = datetime.date.today() + datetime.timedelta(days=1)
        date_text = "завтра"

    # Извлекаем режим из callback_data
    mode = None
    if "_quick_" in data:
        mode = data.split("_quick_")[-1]
    elif data.startswith(f"{CALLBACK_DATA_DATE_TODAY}_") or data.startswith(f"{CALLBACK_DATA_DATE_TOMORROW}_"):
        # Новый формат: pick_date_today_student или pick_date_tomorrow_student
        parts = data.split("_", 3)  # Разбиваем на 4 части: pick_date_today/tomorrow_mode
        if len(parts) >= 4:
            mode = parts[3]
        elif len(parts) >= 3:
            mode = parts[2]
    elif data.startswith("pick_date_"):
        # Старый формат: pick_date_today_student или pick_date_tomorrow_student
        parts = data.split("_")
        if len(parts) >= 4:
            mode = parts[3]  # student или teacher

    # Если режим не найден, используем сохраненный или дефолтный
    if not mode:
        mode = user_data.get(CTX_MODE) or user_data.get(CTX_DEFAULT_MODE) or MODE_STUDENT

    # Получаем query
    query = user_data.get(CTX_LAST_QUERY) or user_data.get(CTX_DEFAULT_QUERY)

    if not query:
        await safe_answer_callback_query(update.callback_query, "❌ Не указана группа/преподаватель. Выберите в настройках.", show_alert=True)
        await start_command(update, context)
        return

    user_data[CTX_SELECTED_DATE] = date.strftime("%Y-%m-%d")
    user_data[CTX_MODE] = mode
    user_data[CTX_LAST_QUERY] = query

    await safe_answer_callback_query(update.callback_query, f"📅 Загружаю расписание на {date_text}...")

    # Загружаем расписание
    api_type = API_TYPE_GROUP if mode == MODE_STUDENT else API_TYPE_TEACHER
    with user_busy_context(user_data):
        pages, err = await safe_get_schedule(date.strftime("%Y-%m-%d"), query, api_type)
        if err or not pages:
            await update.callback_query.message.reply_text(
                f"❌ Не удалось получить расписание на {date_text} для '{escape_html(query)}': {err or 'Расписание не найдено'}",
                parse_mode=ParseMode.HTML
            )
            return

        user_data[CTX_SCHEDULE_PAGES] = pages
        user_data[CTX_CURRENT_PAGE_INDEX] = 0
        await send_schedule_with_pagination(update, context)

