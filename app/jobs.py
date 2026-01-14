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

# Константы для валидации размеров
MAX_PHOTO_SIZE = 10 * 1024 * 1024  # 10MB - лимит Telegram для фото
MAX_DOCUMENT_SIZE = 50 * 1024 * 1024  # 50MB - лимит Telegram для документов

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
                # ОПТИМИЗАЦИЯ: Используем один запрос вместо двух
                # Получаем страницы (с кешем!) для хеширования и отображения
                try:
                    try:
                        pages, err_pages = await asyncio.wait_for(
                            get_schedule(date_str, default_query, api_type, use_cache=True),  # ОПТИМИЗАЦИЯ: use_cache=True
                            timeout=8.0  # ОПТИМИЗАЦИЯ: уменьшен таймаут
                        )
                        if err_pages or not pages:
                            continue
                    except asyncio.TimeoutError:
                        logger.debug(f"Таймаут при получении расписания для {user_id} ({date_str})")
                        continue
                    except Exception as e:
                        logger.debug(f"Ошибка при получении расписания для {user_id} ({date_str}): {e}")
                        continue

                    # ОПТИМИЗАЦИЯ: Получаем структурированное расписание только если нужно для сравнения
                    # (это использует тот же кешированный HTML)
                    try:
                        new_schedule, err = await asyncio.wait_for(
                            get_schedule_structured(date_str, default_query, api_type),
                            timeout=5.0  # ОПТИМИЗАЦИЯ: короткий таймаут, т.к. данные уже в кеше
                        )
                    except asyncio.TimeoutError:
                        new_schedule = None
                    except Exception:
                        new_schedule = None

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

                    # Сохраняем данные расписания для просмотра (с timestamp для очистки)
                    context.bot_data[f"changed_schedule_{user_id}_{date_str}"] = {
                        "query": default_query,
                        "mode": default_mode,
                        "date": date_str,
                        "pages": pages,
                        "timestamp": datetime.datetime.utcnow().isoformat()
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


async def cleanup_bot_data_job(context: ContextTypes.DEFAULT_TYPE):
    """Очистка старых данных из bot_data для предотвращения утечек памяти"""
    from datetime import datetime, timedelta

    logger.debug("🧹 Запущена очистка bot_data")
    now = datetime.utcnow()
    keys_to_delete = []

    # Очистка старых расписаний (старше 1 часа)
    for key in list(context.bot_data.keys()):
        if key.startswith("changed_schedule_"):
            schedule_data = context.bot_data.get(key)
            if isinstance(schedule_data, dict):
                timestamp = schedule_data.get('timestamp')
                if timestamp:
                    try:
                        # Если timestamp - строка, парсим её
                        if isinstance(timestamp, str):
                            timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        # Если timestamp - datetime без timezone, считаем что это UTC
                        if timestamp.tzinfo is None:
                            timestamp = timestamp.replace(tzinfo=datetime.timezone.utc)
                        # Сравниваем в UTC
                        if (now - timestamp.replace(tzinfo=None)) > timedelta(hours=1):
                            keys_to_delete.append(key)
                    except Exception as e:
                        logger.debug(f"Ошибка при проверке timestamp для {key}: {e}")
                        # Если не удалось распарсить, удаляем если ключ старше 2 часов
                        keys_to_delete.append(key)
                else:
                    # Если нет timestamp, удаляем (старые данные)
                    keys_to_delete.append(key)

        # Очистка старых структурированных расписаний (старше 2 часов)
        elif key.startswith("schedule_struct_"):
            # Эти данные используются для сравнения, можно хранить дольше
            # Но все равно очищаем старые
            schedule_data = context.bot_data.get(key)
            if schedule_data and not isinstance(schedule_data, dict):
                # Если данные повреждены, удаляем
                keys_to_delete.append(key)

    # Очистка старых export данных (старше 1 часа)
    for key in list(context.bot_data.keys()):
        if key.startswith("export_") and not key.startswith("export_back_"):
            # Проверяем, не используется ли сейчас
            # Если ключ начинается с export_ но не export_back_, это временные данные
            # Можно удалить если старше 1 часа (но у нас нет timestamp, поэтому пропускаем)
            pass

    # Удаляем найденные ключи
    deleted_count = 0
    for key in keys_to_delete:
        try:
            del context.bot_data[key]
            deleted_count += 1
        except KeyError:
            pass

    if deleted_count > 0:
        logger.info(f"🧹 Очищено {deleted_count} старых записей из bot_data")

    # Очистка users_data_cache от неактивных пользователей (не использовались 24 часа)
    # Это более сложная логика, можно добавить позже если нужно


async def automatic_backup_job(context: ContextTypes.DEFAULT_TYPE):
    """Автоматическое создание резервной копии базы данных"""
    import shutil
    import gzip
    from pathlib import Path
    from datetime import datetime
    
    logger.info("💾 Запущено автоматическое резервное копирование базы данных")
    
    try:
        from .database import DB_PATH
        from .config import DATA_DIR
        
        db_path = Path(DB_PATH)
        if not db_path.exists():
            logger.warning(f"База данных не найдена: {db_path}")
            return
        
        # Создаем директорию для бэкапов
        backup_dir = Path(DATA_DIR) / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        # Генерируем имя файла с timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"users_backup_{timestamp}.db.gz"
        
        # Копируем и сжимаем базу данных
        logger.info(f"Создание резервной копии: {backup_path}")
        with open(db_path, 'rb') as f_in:
            with gzip.open(backup_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        size = backup_path.stat().st_size
        size_mb = size / (1024 * 1024)
        logger.info(f"✅ Резервная копия создана: {backup_path} ({size_mb:.2f} MB)")
        
        # Удаляем старые бэкапы (оставляем последние 7)
        backups = sorted(backup_dir.glob("users_backup_*.db.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
        if len(backups) > 7:
            for old_backup in backups[7:]:
                try:
                    old_backup.unlink()
                    logger.debug(f"Удален старый бэкап: {old_backup.name}")
                except Exception as e:
                    logger.warning(f"Не удалось удалить старый бэкап {old_backup}: {e}")
        
    except Exception as e:
        logger.error(f"Ошибка при создании автоматического бэкапа: {e}", exc_info=True)


