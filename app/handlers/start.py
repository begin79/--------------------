"""
Обработчик команды /start
"""
import asyncio
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ParseMode
from telegram.error import NetworkError, TimedOut
from telegram.ext import ContextTypes

from ..constants import (
    CTX_MODE, CTX_SELECTED_DATE, CTX_AWAITING_MANUAL_DATE, CTX_LAST_QUERY, CTX_SCHEDULE_PAGES,
    CTX_CURRENT_PAGE_INDEX, CTX_AWAITING_DEFAULT_QUERY, CTX_DEFAULT_QUERY, CTX_DEFAULT_MODE,
    CTX_DAILY_NOTIFICATIONS, CTX_NOTIFICATION_TIME, CTX_IS_BUSY, CTX_REPLY_KEYBOARD_PINNED, CTX_FOUND_ENTITIES,
    CTX_AWAITING_FEEDBACK,
    CALLBACK_DATA_MODE_STUDENT, CALLBACK_DATA_MODE_TEACHER, CALLBACK_DATA_SETTINGS_MENU,
    CALLBACK_DATA_BACK_TO_START, CallbackData,
    MODE_STUDENT, MODE_TEACHER,
)
from ..utils import escape_html
from ..database import db
from ..admin.utils import is_bot_enabled, get_maintenance_message
from .utils import safe_edit_message_text, save_user_data_to_db, get_default_reply_keyboard, load_user_data_from_db

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        logger.error("start_command вызван без effective_user")
        return

    user_id = update.effective_user.id

    # Для админов: сбрасываем все флаги админ-панели при команде /start
    from ..admin.utils import is_admin
    if is_admin(user_id):
        context.user_data.pop('awaiting_broadcast', None)
        context.user_data.pop('broadcast_message', None)
        context.user_data.pop('awaiting_maintenance_msg', None)
        context.user_data.pop('awaiting_admin_id', None)
        context.user_data.pop('awaiting_remove_admin_id', None)
        context.user_data.pop('awaiting_user_search', None)
        context.user_data.pop('awaiting_direct_message', None)
        context.user_data.pop('direct_message_target', None)
        logger.debug(f"Админ {user_id}: сброшены все флаги админ-панели при /start")

    # Проверяем статус бота (с обработкой ошибок, чтобы не блокировать работу при проблемах с БД)
    try:
        if not is_bot_enabled():
            maintenance_msg = get_maintenance_message()
            try:
                if update.message:
                    await update.message.reply_text(maintenance_msg)
                elif update.callback_query:
                    await safe_edit_message_text(update.callback_query, maintenance_msg)
            except Exception as e:
                logger.warning(f"Не удалось отправить сообщение о техническом обслуживании: {e}")
            return
    except Exception as e:
        logger.warning(f"Ошибка при проверке статуса бота, продолжаем работу: {e}")
        # Продолжаем работу, если не удалось проверить статус

    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    first_name = update.effective_user.first_name or "без имени"
    last_name = update.effective_user.last_name
    logger.info(f"👤 [{user_id}] @{username} ({first_name}) → Команда /start")

    # БД - единственный источник правды: всегда загружаем данные из БД в начале важных действий
    load_user_data_from_db(user_id, context.user_data, force=True)
    
    # Проверяем, новый ли это пользователь
    user_db = db.get_user(user_id)
    is_first_time = user_db is None

    # Очищаем временные ключи
    temp_keys = [CTX_MODE, CTX_SELECTED_DATE, CTX_AWAITING_MANUAL_DATE, CTX_LAST_QUERY,
                 CTX_SCHEDULE_PAGES, CTX_CURRENT_PAGE_INDEX, CTX_AWAITING_DEFAULT_QUERY, CTX_IS_BUSY, CTX_FOUND_ENTITIES, CTX_AWAITING_FEEDBACK]
    for key in temp_keys:
        context.user_data.pop(key, None)
    for dynamic_key in list(context.user_data.keys()):
        if dynamic_key.startswith("pending_query_"):
            context.user_data.pop(dynamic_key, None)

    # Сохраняем информацию о пользователе в БД
    save_user_data_to_db(user_id, username, first_name, last_name, context.user_data)

    # Обновляем кеш активных пользователей, если у пользователя есть установленная группа/преподаватель
    default_query = context.user_data.get(CTX_DEFAULT_QUERY)
    default_mode = context.user_data.get(CTX_DEFAULT_MODE)
    if default_query and default_mode:
        if 'active_users' not in context.bot_data:
            context.bot_data['active_users'] = set()
        if 'users_data_cache' not in context.bot_data:
            context.bot_data['users_data_cache'] = {}

        context.bot_data['active_users'].add(user_id)
        context.bot_data['users_data_cache'][user_id] = {
            CTX_DEFAULT_QUERY: default_query,
            CTX_DEFAULT_MODE: default_mode,
            CTX_DAILY_NOTIFICATIONS: context.user_data.get(CTX_DAILY_NOTIFICATIONS, False),
            CTX_NOTIFICATION_TIME: context.user_data.get(CTX_NOTIFICATION_TIME, '21:00')
        }

    # Логируем активность
    db.log_activity(user_id, "start_command", f"username={username}")

    # Проверяем, есть ли у пользователя установленное расписание по умолчанию
    default_query = context.user_data.get(CTX_DEFAULT_QUERY)
    default_mode = context.user_data.get(CTX_DEFAULT_MODE)

    # Для новых пользователей без установленной группы показываем выбор режима
    if is_first_time and not default_query:
        text = "👋 Привет! Я бот для получения расписания ВГЛТУ 📅\n\n"
        text += "Выберите, кто вы:"

        keyboard_rows = [
            [InlineKeyboardButton("🎓 Студент", callback_data=CALLBACK_DATA_MODE_STUDENT)],
            [InlineKeyboardButton("🧑‍🏫 Преподаватель", callback_data=CALLBACK_DATA_MODE_TEACHER)]
        ]
    else:
        text = "👋 Привет! Я бот для получения расписания ВГЛТУ 📅\n\n"
        keyboard_rows = []

        # Если есть расписание по умолчанию, показываем быстрый доступ
        if default_query and default_mode:
            text += f"📌 Ваше расписание: <b>{escape_html(default_query)}</b>\n\n"
            # Быстрая кнопка для расписания по умолчанию
            keyboard_rows.append([
                InlineKeyboardButton(
                    f"📋 Показать расписание ({default_query[:20]}{'...' if len(default_query) > 20 else ''})",
                    callback_data=f"quick_schedule_{default_mode}"
                )
            ])
            keyboard_rows.append([])  # Пустая строка для разделения

        text += "Выберите режим или перейдите в настройки:"

        keyboard_rows.extend([
            [InlineKeyboardButton("🎓 Студент", callback_data=CALLBACK_DATA_MODE_STUDENT)],
            [InlineKeyboardButton("🧑‍🏫 Преподаватель", callback_data=CALLBACK_DATA_MODE_TEACHER)],
            [InlineKeyboardButton("⚙️ Настройки", callback_data=CALLBACK_DATA_SETTINGS_MENU)],
            [InlineKeyboardButton("ℹ️ Помощь", callback_data=CallbackData.HELP_COMMAND_INLINE.value)]
        ])

    keyboard = InlineKeyboardMarkup(keyboard_rows)

    # Устанавливаем стандартную клавиатуру для всех сообщений
    reply_keyboard = get_default_reply_keyboard()

    async def ensure_reply_keyboard():
        """Гарантирует наличие ReplyKeyboard без лишних подсказок"""
        chat = update.effective_chat
        if not chat:
            return
        if context.user_data.get(CTX_REPLY_KEYBOARD_PINNED):
            return
        try:
            hint_text = "⌨️ Кнопки «Старт» и «Меню» доступны ниже для быстрого доступа."
            msg = await context.bot.send_message(
                chat_id=chat.id,
                text=hint_text,
                reply_markup=reply_keyboard,
                parse_mode=ParseMode.HTML,
                disable_notification=True,
            )
            context.user_data[CTX_REPLY_KEYBOARD_PINNED] = msg.message_id
        except Exception as e:
            logger.debug(f"Не удалось установить ReplyKeyboard: {e}")

    if update.message:
        # Устанавливаем клавиатуру в основном сообщении с обработкой сетевых ошибок
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await update.message.reply_text(
                    text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )
                break  # Успешно отправлено
            except (NetworkError, TimedOut) as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Экспоненциальная задержка: 1, 2, 4 секунды
                    logger.warning(f"⚠️ [{user_id}] Сетевая ошибка при отправке /start (попытка {attempt + 1}/{max_retries}): {e}. Повтор через {wait_time} сек.")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"❌ [{user_id}] Не удалось отправить /start после {max_retries} попыток: {e}")
                    # Пытаемся отправить хотя бы простое сообщение без форматирования
                    try:
                        await update.message.reply_text(
                            "👋 Привет! Я бот для получения расписания ВГЛТУ 📅\n\nВыберите режим:",
                            reply_markup=keyboard
                        )
                    except Exception as final_error:
                        logger.error(f"❌ [{user_id}] Критическая ошибка при отправке сообщения: {final_error}")
            except Exception as e:
                logger.error(f"❌ [{user_id}] Неожиданная ошибка при отправке /start: {e}", exc_info=True)
                break  # Для других ошибок не повторяем

        await ensure_reply_keyboard()
    elif update.callback_query:
        if not await safe_edit_message_text(update.callback_query, text, reply_markup=keyboard, parse_mode=ParseMode.HTML):
            # Если редактирование не удалось, пытаемся отправить новое сообщение
            try:
                await update.callback_query.message.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.debug(f"Не удалось отправить новое сообщение: {e}", exc_info=True)
        await ensure_reply_keyboard()

