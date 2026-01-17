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

    # Используем единый источник истины по дате — московское время (UTC+3),
    # чтобы избежать сдвига на один день при разнице таймзон сервера и пользователей.
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    today_msk = (now_utc + datetime.timedelta(hours=3)).date()

    # Отправляем расписание на завтра в московском времени
    target_day = today_msk + datetime.timedelta(days=1)
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

    # Определяем текст для дня (также в московском времени)
    tomorrow_msk = today_msk + datetime.timedelta(days=1)
    if target_day == tomorrow_msk:
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
    # Если сегодня воскресенье — проверяем только завтра (понедельник)
    # Если сегодня суббота — проверяем сегодня и понедельник
    from .utils import get_next_weekday
    
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
            
            # Определяем список дат для проверки
            dates_to_check = [today.strftime("%Y-%m-%d")]
            next_wd = get_next_weekday(today)
            if next_wd != today:
                dates_to_check.append(next_wd.strftime("%Y-%m-%d"))
            
            # Убираем дубликаты и фильтруем воскресенья
            dates_to_check = list(dict.fromkeys(dates_to_check))
            
            changes_detected = [] # Список для сбора изменений

            for date_str in dates_to_check:
                # Пропускаем проверку, если это воскресенье
                date_obj_check = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                if date_obj_check.weekday() == 6:
                    continue

                cache_key = f"{user_id}_{default_query}_{date_str}"
                
                try:
                    pages, err_pages = await asyncio.wait_for(
                        get_schedule(date_str, default_query, api_type, use_cache=False), 
                        timeout=10.0
                    )
                    if err_pages or not pages or "Занятий нет" in pages[0]:
                        # Если пар нет, просто сохраняем пустой хеш, чтобы не уведомлять о "пустоте"
                        admin_db.save_schedule_snapshot(cache_key, "empty")
                        continue
                        
                    new_schedule, _ = await asyncio.wait_for(
                        get_schedule_structured(date_str, default_query, api_type),
                        timeout=8.0
                    )
                except Exception:
                    continue

                current_hash = hash_schedule(pages)
                prev_hash = admin_db.get_schedule_snapshot(cache_key)

                # ГЛАВНОЕ ИСПРАВЛЕНИЕ: 
                # Не уведомляем, если prev_hash пустой (первое появление расписания)
                # или если старый хеш был "empty"
                if prev_hash and prev_hash != "empty" and prev_hash != current_hash:
                    old_schedule_key = f"schedule_struct_{cache_key}"
                    old_schedule = context.bot_data.get(old_schedule_key)
                    changes = compare_schedules(old_schedule, new_schedule)
                    
                    if changes:
                        changes_detected.append({
                            "date_str": date_str,
                            "msg": format_schedule_changes(changes, date_str, default_query),
                            "pages": pages
                        })

                # Обновляем снимки в базе
                admin_db.save_schedule_snapshot(cache_key, current_hash)
                if new_schedule:
                    context.bot_data[f"schedule_struct_{cache_key}"] = new_schedule

            # Если есть изменения, отправляем ОДНИМ сообщением
            if changes_detected:
                # Склеиваем сообщения об изменениях
                full_msg = "🔔 <b>Обнаружены изменения!</b>\n\n" + "\n\n".join([c["msg"] for c in changes_detected])
                full_msg += "\n\n👆 Нажмите кнопку ниже для просмотра."
                
                # Используем дату первого изменения для кнопки "Посмотреть"
                first_change = changes_detected[0]
                
                kbd = InlineKeyboardMarkup([
                    [InlineKeyboardButton("👁️ Посмотреть расписание", callback_data=f"view_changed_schedule_{default_mode}_{first_change['date_str']}")],
                    [InlineKeyboardButton("🏠 В начало", callback_data=CALLBACK_DATA_BACK_TO_START)]
                ])

                try:
                    await context.bot.send_message(user_id, full_msg, parse_mode=ParseMode.HTML, reply_markup=kbd)
                    logger.info(f"✅ [{user_id}] Объединенное уведомление отправлено")
                except Forbidden:
                    context.bot_data['active_users'].discard(user_id)

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


