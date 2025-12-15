"""
Обработчики настроек
"""
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from ..constants import (
    CTX_DEFAULT_QUERY, CTX_DEFAULT_MODE,
    CTX_DAILY_NOTIFICATIONS, CTX_NOTIFICATION_TIME,
    CALLBACK_DATA_SETTINGS_MENU, CALLBACK_DATA_BACK_TO_START,
    CALLBACK_DATA_TOGGLE_DAILY, CALLBACK_DATA_SET_NOTIFICATION_TIME,
    CALLBACK_DATA_FEEDBACK, CALLBACK_DATA_RESET_SETTINGS,
    DEFAULT_NOTIFICATION_TIME,
)
from ..utils import escape_html
from .utils import safe_edit_message_text, load_user_data_from_db

logger = logging.getLogger(__name__)


async def settings_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        logger.error("settings_menu_callback вызван без effective_user")
        return

    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    source = "команда /settings" if update.message else "callback"
    logger.info(f"👤 [{user_id}] @{username} → Открыл настройки ({source})")

    user_data = context.user_data

    # ОПТИМИЗАЦИЯ: Загружаем из БД только если данные отсутствуют в контексте
    if not user_data.get(CTX_DEFAULT_QUERY) and not user_data.get(CTX_DEFAULT_MODE):
        load_user_data_from_db(user_id, user_data)

    query = user_data.get(CTX_DEFAULT_QUERY, "Не задано")
    is_daily = user_data.get(CTX_DAILY_NOTIFICATIONS, False)
    notification_time = user_data.get(CTX_NOTIFICATION_TIME, DEFAULT_NOTIFICATION_TIME)
    logger.debug(f"📊 [{user_id}] Настройки: группа='{query}', уведомления={'вкл' if is_daily else 'выкл'}")
    # Формируем текст настроек с улучшенной структурой
    text = "⚙️ <b>Настройки</b>\n\n"
    text += f"📌 Текущая группа/преподаватель:\n   <code>{escape_html(query)}</code>\n\n"
    text += f"⏰ Время уведомлений:\n   <code>{notification_time}</code>"
    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("Установить/изменить группу", callback_data="set_default_mode_student")],
        [InlineKeyboardButton("Установить/изменить преподавателя", callback_data="set_default_mode_teacher")],
        [InlineKeyboardButton(f"{'✅' if is_daily else '❌'} Ежедневные уведомления", callback_data=CALLBACK_DATA_TOGGLE_DAILY)],
        [InlineKeyboardButton("⏰ Изменить время уведомлений", callback_data=CALLBACK_DATA_SET_NOTIFICATION_TIME)],
        [InlineKeyboardButton("💬 Оставить отзыв", callback_data=CALLBACK_DATA_FEEDBACK)],
        [InlineKeyboardButton("♻️ Сбросить настройки", callback_data=CALLBACK_DATA_RESET_SETTINGS)],
        [InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_DATA_BACK_TO_START)]
    ])
    try:
        if update.callback_query:
            if not await safe_edit_message_text(update.callback_query, text, reply_markup=kbd, parse_mode=ParseMode.HTML):
                try:
                    await update.callback_query.message.reply_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
                except Exception as e:
                    logger.debug(f"Ошибка при отправке сообщения: {e}", exc_info=True)
        else:
            await update.effective_message.reply_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logger.info("Меню настроек не изменилось.")
        else:
            logger.error(f"Не удалось обновить меню настроек: {e}")

