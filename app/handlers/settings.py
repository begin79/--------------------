"""
Обработчики настроек
"""
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from ..constants import (
    CTX_DEFAULT_QUERY, CTX_DEFAULT_MODE, CTX_LAST_QUERY,
    CTX_SCHEDULE_PAGES, CTX_CURRENT_PAGE_INDEX, CTX_SELECTED_DATE,
    CTX_DAILY_NOTIFICATIONS, CTX_NOTIFICATION_TIME,
    CALLBACK_DATA_SETTINGS_MENU, CALLBACK_DATA_BACK_TO_START, CALLBACK_DATA_BACK_TO_SCHEDULE,
    CALLBACK_DATA_TOGGLE_DAILY, CALLBACK_DATA_SET_NOTIFICATION_TIME,
    CALLBACK_DATA_FEEDBACK, CALLBACK_DATA_RESET_SETTINGS, CALLBACK_DATA_DO_RESET_SETTINGS,
    DEFAULT_NOTIFICATION_TIME, JOB_PREFIX_DAILY_SCHEDULE,
)
from ..database import db
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

    # БД - единственный источник правды: всегда загружаем данные из БД в начале важных действий
    load_user_data_from_db(user_id, user_data, force=True)

    query = user_data.get(CTX_DEFAULT_QUERY, "Не задано")
    is_daily = user_data.get(CTX_DAILY_NOTIFICATIONS, False)
    notification_time = user_data.get(CTX_NOTIFICATION_TIME, DEFAULT_NOTIFICATION_TIME)
    logger.debug(f"📊 [{user_id}] Настройки: группа='{query}', уведомления={'вкл' if is_daily else 'выкл'}")
    
    # Проверяем, пришел ли пользователь из просмотра расписания
    last_query = user_data.get(CTX_LAST_QUERY)
    has_schedule_context = bool(last_query and user_data.get(CTX_SCHEDULE_PAGES))
    
    # Формируем текст настроек с улучшенной структурой
    text = "⚙️ <b>Настройки</b>\n\n"
    text += f"📌 Текущая группа/преподаватель:\n   <code>{escape_html(query)}</code>\n\n"
    text += f"⏰ Время уведомлений:\n   <code>{notification_time}</code>"
    
    # Формируем клавиатуру с контекстной кнопкой
    keyboard_buttons = []
    
    # Если пользователь пришел из расписания, добавляем кнопку возврата к нему
    if has_schedule_context:
        keyboard_buttons.append([
            InlineKeyboardButton(f"🔙 Вернуться к {escape_html(last_query)}", callback_data=CALLBACK_DATA_BACK_TO_SCHEDULE)
        ])
    
    keyboard_buttons.extend([
        [InlineKeyboardButton("Установить/изменить группу", callback_data="set_default_mode_student")],
        [InlineKeyboardButton("Установить/изменить преподавателя", callback_data="set_default_mode_teacher")],
        [InlineKeyboardButton(f"{'✅' if is_daily else '❌'} Ежедневные уведомления", callback_data=CALLBACK_DATA_TOGGLE_DAILY)],
        [InlineKeyboardButton("⏰ Изменить время уведомлений", callback_data=CALLBACK_DATA_SET_NOTIFICATION_TIME)],
        [InlineKeyboardButton("💬 Оставить отзыв", callback_data=CALLBACK_DATA_FEEDBACK)],
        [InlineKeyboardButton("♻️ Сбросить настройки", callback_data=CALLBACK_DATA_RESET_SETTINGS)],
        [InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_DATA_BACK_TO_START)]
    ])
    
    kbd = InlineKeyboardMarkup(keyboard_buttons)
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


async def handle_reset_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Подтверждение сброса настроек"""
    prompt = (
        "Вы уверены, что хотите сбросить настройки?\n\n"
        "Будут удалены: выбранная группа/преподаватель и отключены уведомления."
    )
    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да, сбросить", callback_data=CALLBACK_DATA_DO_RESET_SETTINGS)],
        [InlineKeyboardButton("⬅️ Отмена", callback_data=CALLBACK_DATA_SETTINGS_MENU)]
    ])
    await safe_edit_message_text(update.callback_query, prompt, reply_markup=kbd)


async def handle_reset_execute(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Выполнение сброса настроек"""
    user_data = context.user_data
    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    # Останавливаем джоб, если активна
    chat_id = update.effective_chat.id if update.effective_chat else None
    if context.job_queue and chat_id:
        job_name = f"{JOB_PREFIX_DAILY_SCHEDULE}{chat_id}"
        job = context.job_queue.get_jobs_by_name(job_name)
        if job:
            for j in job:
                try:
                    j.schedule_removal()
                except Exception as e:
                    logger.debug(f"Ошибка при удалении задачи: {e}", exc_info=True)
    # Чистим user_data
    for key in [
        CTX_DEFAULT_QUERY,
        CTX_DEFAULT_MODE,
        CTX_LAST_QUERY,
        CTX_SCHEDULE_PAGES,
        CTX_CURRENT_PAGE_INDEX,
    ]:
        user_data.pop(key, None)
    user_data[CTX_DAILY_NOTIFICATIONS] = False
    user_data[CTX_NOTIFICATION_TIME] = DEFAULT_NOTIFICATION_TIME
    user_data.pop(CTX_SELECTED_DATE, None)
    # Сохраняем в БД: гарантированно очищаем значения в таблице
    first_name = update.effective_user.first_name if update.effective_user else None
    last_name = update.effective_user.last_name if update.effective_user else None
    try:
        # Полное удаление записи и создание чистой с дефолтами
        db.delete_user(user_id)
    except Exception as e:
        logger.debug(f"Ошибка при удалении пользователя: {e}", exc_info=True)
    # Создаем запись со сброшенными настройками
    db.save_user(
        user_id=user_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        default_query=None,
        default_mode=None,
        daily_notifications=False,
        notification_time=DEFAULT_NOTIFICATION_TIME
    )
    db.log_activity(user_id, "reset_settings", "defaults_cleared")
    # Возвращаемся в настройки
    from .utils import safe_answer_callback_query
    await safe_answer_callback_query(update.callback_query, "Настройки сброшены.")
    await settings_menu_callback(update, context)

