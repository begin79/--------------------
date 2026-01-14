"""
Обработчики уведомлений
"""
import datetime
import logging
from datetime import timezone
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ..constants import (
    CTX_DEFAULT_QUERY, CTX_DEFAULT_MODE, CTX_DAILY_NOTIFICATIONS, CTX_NOTIFICATION_TIME,
    CTX_SELECTED_DATE, CTX_MODE, CTX_LAST_QUERY, CTX_SCHEDULE_PAGES, CTX_CURRENT_PAGE_INDEX,
    CALLBACK_DATA_SETTINGS_MENU, CALLBACK_DATA_NOTIFICATION_OPEN_PREFIX,
    CALLBACK_DATA_DATE_TODAY, CALLBACK_DATA_DATE_TOMORROW,
    DEFAULT_NOTIFICATION_TIME, JOB_PREFIX_DAILY_SCHEDULE,
    MODE_STUDENT, API_TYPE_GROUP, API_TYPE_TEACHER,
    CTX_AWAITING_FEEDBACK,
)
from ..database import db
from ..utils import escape_html
from ..state_manager import set_user_busy
from .utils import safe_edit_message_text, safe_answer_callback_query, save_user_data_to_db
from .settings import settings_menu_callback
from .start import start_command
from ..jobs import daily_schedule_job

logger = logging.getLogger(__name__)


def schedule_daily_notifications(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_data: dict):
    """Перенастраивает ежедневное уведомление согласно текущим настройкам пользователя"""
    if not context.job_queue or not chat_id:
        return

    job_name = f"{JOB_PREFIX_DAILY_SCHEDULE}{chat_id}"
    for job in context.job_queue.get_jobs_by_name(job_name):
        try:
            job.schedule_removal()
        except Exception as e:
            logger.debug(f"Ошибка при удалении задачи: {e}", exc_info=True)

    query = user_data.get(CTX_DEFAULT_QUERY)
    mode = user_data.get(CTX_DEFAULT_MODE)
    if not query or not mode:
        return

    time_str = user_data.get(CTX_NOTIFICATION_TIME, DEFAULT_NOTIFICATION_TIME) or DEFAULT_NOTIFICATION_TIME
    try:
        hour, minute = map(int, time_str.split(":"))
    except ValueError:
        hour, minute = 21, 0
        time_str = DEFAULT_NOTIFICATION_TIME
        user_data[CTX_NOTIFICATION_TIME] = time_str

    utc_hour = (hour - 3) % 24
    job_data = {"query": query, "mode": mode}
    context.job_queue.run_daily(
        daily_schedule_job,
        time=datetime.time(utc_hour, minute, tzinfo=timezone.utc),
        chat_id=chat_id,
        name=job_name,
        data=job_data,
    )


async def show_notification_time_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "⏰ Выберите время для ежедневных уведомлений:"
    # Улучшенное расположение кнопок в 2 колонки для удобства на мобильных
    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("07:00", callback_data="set_time_07:00"), InlineKeyboardButton("18:00", callback_data="set_time_18:00")],
        [InlineKeyboardButton("19:00", callback_data="set_time_19:00"), InlineKeyboardButton("20:00", callback_data="set_time_20:00")],
        [InlineKeyboardButton("21:00", callback_data="set_time_21:00"), InlineKeyboardButton("22:00", callback_data="set_time_22:00")],
        [InlineKeyboardButton("23:00", callback_data="set_time_23:00")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_DATA_SETTINGS_MENU)]
    ])
    await safe_edit_message_text(update.callback_query, text, reply_markup=kbd)


async def set_notification_time(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    first_name = update.effective_user.first_name
    last_name = update.effective_user.last_name
    time_str = data.replace("set_time_", "")
    logger.info(f"⏰ [{user_id}] @{username} → Установлено время уведомлений: {time_str}")

    user_data = context.user_data
    user_data[CTX_NOTIFICATION_TIME] = time_str

    # Обновляем задачу уведомлений, если она активна
    chat_id = update.effective_chat.id
    if user_data.get(CTX_DAILY_NOTIFICATIONS) and context.job_queue and user_data.get(CTX_DEFAULT_QUERY):
        job_name = f"{JOB_PREFIX_DAILY_SCHEDULE}{chat_id}"
        # Удаляем старую задачу
        for job in context.job_queue.get_jobs_by_name(job_name):
            try:
                job.schedule_removal()
            except Exception as e:
                logger.debug(f"Ошибка при удалении задачи: {e}", exc_info=True)

        # Создаем новую задачу с новым временем
        hour, minute = map(int, time_str.split(":"))
        utc_hour = (hour - 3) % 24
        job_data = {"query": user_data[CTX_DEFAULT_QUERY], "mode": user_data[CTX_DEFAULT_MODE]}
        context.job_queue.run_daily(
            daily_schedule_job,
            time=datetime.time(utc_hour, minute, tzinfo=timezone.utc),
            chat_id=chat_id,
            name=job_name,
            data=job_data,
        )

    # Сохраняем в БД
    save_user_data_to_db(user_id, username, first_name, last_name, user_data)
    db.log_activity(user_id, "set_notification_time", f"time={time_str}")

    await safe_answer_callback_query(update.callback_query, f"Время уведомлений установлено: {time_str}")
    await settings_menu_callback(update, context)


async def toggle_daily_notifications_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    first_name = update.effective_user.first_name
    last_name = update.effective_user.last_name
    chat_id, user_data = update.effective_chat.id, context.user_data
    current_state = user_data.get(CTX_DAILY_NOTIFICATIONS, False)
    new_state = not current_state
    logger.info(f"🔔 [{user_id}] @{username} → {'Включены' if new_state else 'Выключены'} ежедневные уведомления")

    if not context.job_queue:
        await safe_answer_callback_query(update.callback_query, "Функция уведомлений неактивна.", show_alert=True)
        return
    if not user_data.get(CTX_DEFAULT_QUERY):
        await safe_answer_callback_query(update.callback_query, "Сначала установите группу/преподавателя!", show_alert=True)
        return

    job_name = f"{JOB_PREFIX_DAILY_SCHEDULE}{chat_id}"
    for job in context.job_queue.get_jobs_by_name(job_name):
        try:
            job.schedule_removal()
        except Exception as e:
            logger.debug(f"Ошибка при удалении задачи: {e}", exc_info=True)

    if user_data.get(CTX_DAILY_NOTIFICATIONS, False):
        user_data[CTX_DAILY_NOTIFICATIONS] = False
        await safe_answer_callback_query(update.callback_query, "Ежедневные уведомления отключены.")
    else:
        user_data[CTX_DAILY_NOTIFICATIONS] = True
        time_str = user_data.get(CTX_NOTIFICATION_TIME, DEFAULT_NOTIFICATION_TIME)
        hour, minute = map(int, time_str.split(":"))
        utc_hour = (hour - 3) % 24
        job_data = {"query": user_data[CTX_DEFAULT_QUERY], "mode": user_data[CTX_DEFAULT_MODE]}
        context.job_queue.run_daily(
            daily_schedule_job,
            time=datetime.time(utc_hour, minute, tzinfo=timezone.utc),
            chat_id=chat_id,
            name=job_name,
            data=job_data,
        )
        await safe_answer_callback_query(update.callback_query, f"Ежедневные уведомления включены на {time_str}!")

    # Сохраняем в БД
    save_user_data_to_db(user_id, username, first_name, last_name, user_data)
    db.log_activity(user_id, "toggle_daily_notifications", f"enabled={new_state}")

    await settings_menu_callback(update, context)


async def handle_notification_open_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Открывает расписание по кнопке из уведомления"""
    if not update.callback_query:
        return

    payload = data.replace(CALLBACK_DATA_NOTIFICATION_OPEN_PREFIX, "", 1)
    try:
        mode_part, date_str = payload.split("_", 1)
    except ValueError:
        await safe_answer_callback_query(update.callback_query, "Данные уведомления устарели.", show_alert=True)
        return

    mode = MODE_STUDENT if mode_part == "student" else "teacher"
    user_data = context.user_data
    # При открытии расписания из уведомления сбрасываем режим ожидания отзыва.
    user_data.pop(CTX_AWAITING_FEEDBACK, None)
    user_data[CTX_SELECTED_DATE] = date_str
    user_data[CTX_MODE] = mode
    query = user_data.get(CTX_DEFAULT_QUERY)

    if not query:
        await safe_answer_callback_query(update.callback_query, "Группа/преподаватель не установлены.", show_alert=True)
        await start_command(update, context)
        return

    user_data[CTX_LAST_QUERY] = query
    api_type = API_TYPE_GROUP if mode == MODE_STUDENT else API_TYPE_TEACHER

    await safe_answer_callback_query(update.callback_query, "📅 Загружаю расписание...")

    from .schedule import safe_get_schedule, send_schedule_with_pagination
    from .utils import user_busy_context

    async with user_busy_context(user_data):
        pages, err = await safe_get_schedule(date_str, query, api_type)
        if err or not pages:
            await update.callback_query.message.reply_text(
                f"❌ Не удалось получить расписание: {err or 'Расписание не найдено'}",
                parse_mode=ParseMode.HTML
            )
            return

        user_data[CTX_SCHEDULE_PAGES] = pages
        user_data[CTX_CURRENT_PAGE_INDEX] = 0
        await send_schedule_with_pagination(update, context)

