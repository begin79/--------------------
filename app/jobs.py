import asyncio
import datetime
import logging
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.error import Forbidden
from telegram.ext import ContextTypes

from .constants import (
    API_TYPE_GROUP, API_TYPE_TEACHER, CALLBACK_DATA_BACK_TO_START,
    CALLBACK_DATA_NOTIFICATION_OPEN_PREFIX, CTX_DEFAULT_QUERY, CTX_DEFAULT_MODE,
    ENTITY_GROUP_GENITIVE, ENTITY_TEACHER_GENITIVE, MODE_STUDENT
)
from .schedule import get_schedule, get_schedule_structured
from .utils import escape_html, hash_schedule, compare_schedules, format_schedule_changes
from .admin.database import admin_db

logger = logging.getLogger(__name__)

async def daily_schedule_job(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    query = job.data["query"]
    mode = job.data["mode"]
    mode_text = ENTITY_GROUP_GENITIVE if mode == MODE_STUDENT else ENTITY_TEACHER_GENITIVE
    logger.info(f"🔔 [{chat_id}] → Ежедневное уведомление для {mode_text} '{query}'")

    today = datetime.date.today()
    # Отправляем расписание на завтра (сегодня + 1 день), независимо от выходных
    target_day = today + datetime.timedelta(days=1)
    api_type = API_TYPE_GROUP if job.data["mode"] == MODE_STUDENT else API_TYPE_TEACHER
    # Используем таймаут для уведомлений, чтобы не блокировать другие задачи
    try:
        pages, err = await asyncio.wait_for(
            get_schedule(target_day.strftime("%Y-%m-%d"), job.data["query"], api_type),
            timeout=12.0  # Уменьшен таймаут для быстрых уведомлений
        )
    except asyncio.TimeoutError:
        logger.warning(f"Таймаут при получении расписания для уведомления {job.data['query']}")
        pages, err = None, "Таймаут"
    except Exception as e:
        logger.error(f"Ошибка при получении расписания для уведомления: {e}")
        pages, err = None, str(e)

    if pages:
        logger.info(f"✅ [{chat_id}] Уведомление отправлено успешно")
    else:
        logger.warning(f"❌ [{chat_id}] Ошибка получения расписания для уведомления: {err}")

    # Определяем текст для дня
    if target_day == today + datetime.timedelta(days=1):
        day_text = "на завтра"
    else:
        weekdays = ["понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье"]
        weekday_name = weekdays[target_day.weekday()]
        day_text = f"на {weekday_name}"

    msg = f"Не удалось получить расписание {day_text} для '{escape_html(job.data['query'])}'."
    if not err and pages:
        header = f"🗓️ <b>Расписание {day_text} ({target_day.strftime('%d.%m.%Y')}) для {escape_html(job.data['query'])}</b>\n\n"
        schedule = pages[0]
        if "Занятий нет" in schedule or "не найдено" in schedule:
            msg = f"🎉 {day_text.capitalize()} для '{escape_html(job.data['query'])}' занятий нет!"
        else:
            msg = header + schedule

    open_callback = f"{CALLBACK_DATA_NOTIFICATION_OPEN_PREFIX}{job.data['mode']}_{target_day.strftime('%Y-%m-%d')}"
    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Перейти к расписанию", callback_data=open_callback)],
        [InlineKeyboardButton("🏠 В начало", callback_data=CALLBACK_DATA_BACK_TO_START)]
    ])

    try:
        await context.bot.send_message(job.chat_id, msg, parse_mode=ParseMode.HTML, reply_markup=kbd)
    except Forbidden:
        logger.warning(f"Пользователь {job.chat_id} заблокировал бота. Удаляю задачу.")
        job.schedule_removal()

async def check_schedule_changes_job(context: ContextTypes.DEFAULT_TYPE):
    logger.info("🔄 Запущена проверка изменений расписания")

    if 'active_users' not in context.bot_data:
        context.bot_data['active_users'] = set()
    if 'users_data_cache' not in context.bot_data:
        context.bot_data['users_data_cache'] = {}

    today = datetime.date.today()
    from .utils import get_next_weekday
    next_weekday = get_next_weekday(today)
    dates_to_check = [today.strftime("%Y-%m-%d"), next_weekday.strftime("%Y-%m-%d")]

    active_users = context.bot_data.get('active_users', set()).copy()
    logger.info(f"👥 Проверяю расписание для {len(active_users)} активных пользователей")

    for user_id in active_users:
        try:
            user_data = context.bot_data['users_data_cache'].get(user_id, {})
            default_query = user_data.get(CTX_DEFAULT_QUERY)
            default_mode = user_data.get(CTX_DEFAULT_MODE)
            if not default_query or not default_mode:
                continue

            api_type = API_TYPE_GROUP if default_mode == MODE_STUDENT else API_TYPE_TEACHER
            for date_str in dates_to_check:
                cache_key = f"{user_id}_{default_query}_{date_str}"
                # Используем таймаут для проверки изменений
                # Обернуто в try-except, чтобы падение одного запроса не прерывало цикл для остальных пользователей
                try:
                    # Получаем структурированное расписание для сравнения
                    try:
                        new_schedule, err = await asyncio.wait_for(
                            get_schedule_structured(date_str, default_query, api_type),
                            timeout=10.0
                        )
                        if err or not new_schedule:
                            continue
                    except asyncio.TimeoutError:
                        logger.debug(f"Таймаут при получении структурированного расписания для {user_id} ({date_str})")
                        continue
                    except Exception as e:
                        logger.debug(f"Ошибка при получении структурированного расписания для {user_id} ({date_str}): {e}")
                        continue

                    # Получаем страницы для хеширования и отображения
                    try:
                        pages, err_pages = await asyncio.wait_for(
                            get_schedule(date_str, default_query, api_type, use_cache=False),
                            timeout=10.0
                        )
                        if err_pages or not pages:
                            continue
                    except asyncio.TimeoutError:
                        logger.debug(f"Таймаут при получении страниц расписания для {user_id} ({date_str})")
                        continue
                    except Exception as e:
                        logger.debug(f"Ошибка при получении страниц расписания для {user_id} ({date_str}): {e}")
                        continue

                except Exception as e:
                    # Общий catch для любых неожиданных ошибок
                    logger.error(f"Неожиданная ошибка при проверке изменений для {user_id} ({date_str}): {e}", exc_info=True)
                    continue

                current_hash = hash_schedule(pages)
                prev_hash = admin_db.get_schedule_snapshot(cache_key)

                if prev_hash and prev_hash != current_hash:
                    date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                    date_display = "сегодня" if date_obj == today else "завтра"
                    logger.info(f"🔔 [{user_id}] → Обнаружено изменение расписания {date_display} для '{default_query}'")

                    # Получаем старое структурированное расписание из кеша
                    old_schedule_key = f"schedule_struct_{cache_key}"
                    old_schedule = context.bot_data.get(old_schedule_key)

                    # Сравниваем расписания
                    changes = compare_schedules(old_schedule, new_schedule)

                    # Формируем сообщение
                    if changes:
                        msg = format_schedule_changes(changes, date_str, default_query)
                        # Добавляем кнопку "Посмотреть полное расписание"
                        msg += "\n\n👆 Нажмите кнопку ниже, чтобы посмотреть полное расписание."
                    else:
                        # Если не удалось сравнить детально, показываем общее сообщение
                        msg = f"🔔 <b>Расписание изменилось</b>\n\nРасписание {date_display} ({date_obj.strftime('%d.%m.%Y')}) для {escape_html(default_query)} было обновлено."

                    kbd = InlineKeyboardMarkup([
                        [InlineKeyboardButton("👁️ Посмотреть расписание", callback_data=f"view_changed_schedule_{default_mode}_{date_str}")],
                        [InlineKeyboardButton("🏠 В начало", callback_data=CALLBACK_DATA_BACK_TO_START)]
                    ])

                    # Сохраняем данные расписания для просмотра
                    context.bot_data[f"changed_schedule_{user_id}_{date_str}"] = {
                        "query": default_query,
                        "mode": default_mode,
                        "date": date_str,
                        "pages": pages
                    }

                    try:
                        await context.bot.send_message(user_id, msg, parse_mode=ParseMode.HTML, reply_markup=kbd)
                        logger.info(f"✅ [{user_id}] Уведомление об изменении отправлено")
                    except Forbidden:
                        logger.warning(f"⚠️ [{user_id}] Пользователь заблокировал бота")
                        context.bot_data['active_users'].discard(user_id)

                    # Сохраняем новое структурированное расписание для следующего сравнения
                    context.bot_data[old_schedule_key] = new_schedule

                # Сохраняем хеш и структурированное расписание
                admin_db.save_schedule_snapshot(cache_key, current_hash)
                if new_schedule:
                    schedule_struct_key = f"schedule_struct_{cache_key}"
                    context.bot_data[schedule_struct_key] = new_schedule
        except Exception as e:
            logger.error(f"Ошибка при проверке расписания для пользователя {user_id}: {e}")


