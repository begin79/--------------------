import asyncio
import datetime
import logging
from typing import Optional, List, Dict, Any
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.error import Forbidden, NetworkError, TimedOut
from telegram.ext import ContextTypes

from .constants import (
    API_TYPE_GROUP, API_TYPE_TEACHER, CALLBACK_DATA_BACK_TO_START,
    CALLBACK_DATA_NOTIFICATION_OPEN_PREFIX, CTX_DEFAULT_QUERY, CTX_DEFAULT_MODE,
    ENTITY_GROUP_GENITIVE, ENTITY_TEACHER_GENITIVE, MODE_STUDENT
)
from .schedule import get_schedule, get_schedule_structured
from .utils import escape_html, hash_schedule, compare_schedules, format_schedule_changes, get_next_weekday
from .admin.database import admin_db

logger = logging.getLogger(__name__)

# Константы для валидации размеров
MAX_PHOTO_SIZE = 10 * 1024 * 1024  # 10MB - лимит Telegram для фото
MAX_DOCUMENT_SIZE = 50 * 1024 * 1024  # 50MB - лимит Telegram для документов


def is_weekend(date: datetime.date) -> bool:
    """
    Проверяет, является ли дата выходным днем.
    
    Args:
        date: Дата для проверки
    
    Returns:
        True если это суббота или воскресенье
    """
    return date.weekday() >= 5  # 5 = суббота, 6 = воскресенье


def get_next_workday(date: datetime.date) -> datetime.date:
    """
    Получает следующий рабочий день после указанной даты.
    Пропускает воскресенье.
    
    Args:
        date: Исходная дата
    
    Returns:
        Следующий рабочий день
    """
    next_day = date + datetime.timedelta(days=1)
    
    # Если следующий день - воскресенье, пропускаем его
    if next_day.weekday() == 6:  # Воскресенье
        next_day = next_day + datetime.timedelta(days=1)  # Понедельник
    
    return next_day


def get_target_date_for_notification(today: datetime.date) -> datetime.date:
    """
    Определяет дату для уведомления, учитывая выходные.
    
    Args:
        today: Сегодняшняя дата
    
    Returns:
        Дата для уведомления
    """
    # Отправляем расписание на завтра
    tomorrow = today + datetime.timedelta(days=1)
    
    # Если завтра - воскресенье, отправляем на понедельник
    if tomorrow.weekday() == 6:  # Воскресенье
        return tomorrow + datetime.timedelta(days=1)  # Понедельник
    
    return tomorrow

async def daily_schedule_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Ежедневное уведомление о расписании.
    Улучшенная версия с явной обработкой выходных и ошибок.
    """
    job = context.job
    chat_id = job.chat_id
    query = job.data["query"]
    mode = job.data["mode"]
    mode_text = ENTITY_GROUP_GENITIVE if mode == MODE_STUDENT else ENTITY_TEACHER_GENITIVE
    logger.info(f"🔔 [{chat_id}] → Ежедневное уведомление для {mode_text} '{query}'")

    try:
        # Используем единый источник истины по дате — московское время (UTC+3)
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        today_msk = (now_utc + datetime.timedelta(hours=3)).date()
        
        # Если сегодня воскресенье, не отправляем уведомление
        if today_msk.weekday() == 6:
            logger.debug(f"Сегодня воскресенье, уведомление не отправляется")
            return
        
        # Определяем дату для уведомления с учетом выходных
        target_day = get_target_date_for_notification(today_msk)
        
        api_type = API_TYPE_GROUP if mode == MODE_STUDENT else API_TYPE_TEACHER
        
        # Получаем расписание с таймаутом и улучшенной обработкой ошибок
        try:
            pages, err = await asyncio.wait_for(
                get_schedule(target_day.strftime("%Y-%m-%d"), query, api_type),
                timeout=12.0
            )
        except asyncio.TimeoutError:
            logger.warning(f"Таймаут при получении расписания для уведомления {query}")
            pages, err = None, "Превышено время ожидания ответа от сервера"
        except (NetworkError, TimedOut) as e:
            logger.warning(f"Сетевая ошибка при получении расписания для уведомления: {e}")
            pages, err = None, "Проблемы с подключением к серверу"
        except Exception as e:
            logger.error(f"Ошибка при получении расписания для уведомления: {e}", exc_info=True)
            pages, err = None, f"Ошибка: {str(e)}"

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
        except (NetworkError, TimedOut) as e:
            logger.warning(f"Сетевая ошибка при отправке уведомления пользователю {job.chat_id}: {e}")
            # Не удаляем задачу при временных сетевых ошибках
    except Exception as e:
        logger.error(f"Критическая ошибка в daily_schedule_job для пользователя {chat_id}: {e}", exc_info=True)

async def check_schedule_changes_job(context: ContextTypes.DEFAULT_TYPE):
    logger.info("🔄 Запущена проверка изменений расписания")

    if 'active_users' not in context.bot_data:
        context.bot_data['active_users'] = set()
    if 'users_data_cache' not in context.bot_data:
        context.bot_data['users_data_cache'] = {}

    today = datetime.date.today()
    
    # Определяем даты для проверки с учетом выходных
    dates_to_check: List[datetime.date] = []
    
    # Проверяем сегодня (если это не воскресенье)
    if not is_weekend(today):
        dates_to_check.append(today)
    
    # Проверяем следующий рабочий день
    next_workday = get_next_workday(today)
    if next_workday not in dates_to_check:
        dates_to_check.append(next_workday)
    
    active_users = context.bot_data.get('active_users', set()).copy()
    logger.info(f"👥 Проверяю расписание для {len(active_users)} активных пользователей")

    for user_id in active_users:
        try:
            user_data = context.bot_data['users_data_cache'].get(user_id, {})
            default_query = user_data.get(CTX_DEFAULT_QUERY)
            default_mode = user_data.get(CTX_DEFAULT_MODE)
            
            if not default_query or not default_mode:
                logger.debug(f"Пользователь {user_id} без установленной группы/преподавателя, пропускаем")
                continue

            api_type = API_TYPE_GROUP if default_mode == MODE_STUDENT else API_TYPE_TEACHER
            changes_detected: List[Dict[str, Any]] = []

            for date_obj in dates_to_check:
                date_str = date_obj.strftime("%Y-%m-%d")
                
                # Пропускаем воскресенье (защита на всякий случай)
                if date_obj.weekday() == 6:
                    continue

                cache_key = f"{user_id}_{default_query}_{date_str}"
                
                try:
                    # Получаем расписание без кеша для точного сравнения
                    pages, err_pages = await asyncio.wait_for(
                        get_schedule(date_str, default_query, api_type, use_cache=False), 
                        timeout=10.0
                    )
                    
                    # Обрабатываем случай, когда пар нет или ошибка
                    if err_pages or not pages or (pages and "Занятий нет" in pages[0]):
                        # Если пар нет, сохраняем "empty" хеш
                        current_hash = "empty"
                        prev_hash = admin_db.get_schedule_snapshot(cache_key)
                        
                        # Не уведомляем о появлении "пустоты", если раньше уже была "пустота"
                        # И не уведомляем, если это первое появление "пустоты" (prev_hash == None)
                        if prev_hash and prev_hash != "empty" and prev_hash != current_hash:
                            # Расписание изменилось с "непустого" на "пустое" - это изменение
                            changes_detected.append({
                                "date_str": date_str,
                                "msg": f"🔔 <b>Изменения в расписании</b>\n\n📅 Дата: {date_str}\n📌 {escape_html(default_query)}\n\n➖ <b>Удалено:</b> Все занятия отменены",
                                "pages": pages
                            })
                        
                        # Сохраняем текущее состояние (пустое)
                        admin_db.save_schedule_snapshot(cache_key, current_hash)
                        context.bot_data[f"schedule_struct_{cache_key}"] = None
                        continue
                        
                    # Получаем структурированное расписание для сравнения
                    try:
                        new_schedule, _ = await asyncio.wait_for(
                            get_schedule_structured(date_str, default_query, api_type),
                            timeout=8.0
                        )
                    except asyncio.TimeoutError:
                        logger.warning(f"Таймаут при получении структурированного расписания для {user_id}")
                        continue
                    except Exception as e:
                        logger.error(f"Ошибка при получении структурированного расписания для {user_id}: {e}", exc_info=True)
                        continue
                except asyncio.TimeoutError:
                    logger.warning(f"Таймаут при проверке расписания для пользователя {user_id} на дату {date_str}")
                    continue
                except (NetworkError, TimedOut) as e:
                    logger.warning(f"Сетевая ошибка при проверке расписания для пользователя {user_id}: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Ошибка при проверке расписания для пользователя {user_id} на дату {date_str}: {e}", exc_info=True)
                    continue

                current_hash = hash_schedule(pages)
                prev_hash = admin_db.get_schedule_snapshot(cache_key)

                # ГЛАВНОЕ ИСПРАВЛЕНИЕ: 
                # Не уведомляем, если prev_hash пустой (первое появление расписания)
                # или если старый хеш был "empty"
                if prev_hash and prev_hash != "empty" and prev_hash != current_hash:
                    old_schedule_key = f"schedule_struct_{cache_key}"
                    old_schedule = context.bot_data.get(old_schedule_key)
                    
                    # Сравниваем расписания только если есть старое структурированное расписание
                    # Если его нет (например, после перезапуска), но хеш изменился - 
                    # не уведомляем, так как не можем показать детали изменений
                    if old_schedule:
                        changes = compare_schedules(old_schedule, new_schedule)
                        if changes:
                            changes_detected.append({
                                "date_str": date_str,
                                "msg": format_schedule_changes(changes, date_str, default_query),
                                "pages": pages
                            })

                # Обновляем снимки в базе (всегда, даже если не было изменений)
                admin_db.save_schedule_snapshot(cache_key, current_hash)
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
                    logger.warning(f"Пользователь {user_id} заблокировал бота. Удаляю из активных.")
                    context.bot_data['active_users'].discard(user_id)
                except (NetworkError, TimedOut) as e:
                    logger.warning(f"Сетевая ошибка при отправке уведомления пользователю {user_id}: {e}")
                    # Не удаляем пользователя из активных при временных сетевых ошибках

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
    if 'users_data_cache' in context.bot_data:
        users_cache = context.bot_data['users_data_cache']
        inactive_users: List[int] = []
        
        for user_id, user_data in users_cache.items():
            # Если пользователь не в active_users более 24 часов, удаляем из кеша
            # Это упрощенная логика, в реальности можно добавить timestamp последней активности
            if user_id not in context.bot_data.get('active_users', set()):
                # Проверяем, есть ли у пользователя установленная группа/преподаватель
                if not user_data.get(CTX_DEFAULT_QUERY):
                    inactive_users.append(user_id)
        
        for user_id in inactive_users:
            users_cache.pop(user_id, None)
        
        if inactive_users:
            logger.debug(f"Очищено {len(inactive_users)} неактивных пользователей из users_data_cache")


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


