#!/usr/bin/env python3
"""
Скрипт для восстановления пользователей из логов активности в базу данных
Использование:
    python restore_users_from_logs.py
"""
import os
import sys
import logging
from pathlib import Path
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('restore_users.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Добавляем путь к модулям приложения
sys.path.insert(0, str(Path(__file__).parent))

from app.database import DB_PATH, UserDatabase

def restore_users_from_activity_log():
    """Восстановить пользователей из логов активности"""
    db_path = Path(DB_PATH)

    if not db_path.exists():
        logger.error(f"База данных не найдена: {db_path}")
        return False

    try:
        logger.info("=" * 60)
        logger.info("НАЧАЛО ВОССТАНОВЛЕНИЯ ПОЛЬЗОВАТЕЛЕЙ ИЗ ЛОГОВ")
        logger.info("=" * 60)

        db = UserDatabase(db_path)

        # Получаем все user_id из activity_log
        logger.info("[1/4] Получение списка пользователей из логов активности...")
        all_user_ids = db.get_all_known_user_ids(include_activity_log=True)
        logger.info(f"     Найдено уникальных user_id: {len(all_user_ids)}")

        if not all_user_ids:
            logger.warning("     Пользователи не найдены в логах активности")
            return False

        # Получаем существующих пользователей
        logger.info("[2/4] Проверка существующих пользователей в базе...")
        existing_users = db.get_all_users()
        existing_user_ids = {u['user_id'] for u in existing_users}
        logger.info(f"     Существующих пользователей в базе: {len(existing_user_ids)}")

        # Находим пользователей, которых нужно добавить
        users_to_add = [uid for uid in all_user_ids if uid not in existing_user_ids]
        logger.info(f"     Пользователей для добавления: {len(users_to_add)}")

        if not users_to_add:
            logger.info("     Все пользователи уже есть в базе данных")
            return True

        # Получаем информацию о пользователях из activity_log
        logger.info("[3/4] Получение информации о пользователях из логов...")
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Получаем последнюю активность для каждого пользователя
        user_info = {}
        for user_id in users_to_add:
            cursor.execute('''
                SELECT user_id, action, details, timestamp
                FROM activity_log
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT 1
            ''', (user_id,))
            row = cursor.fetchone()
            if row:
                user_info[user_id] = dict(row)

        conn.close()

        # Добавляем пользователей в базу данных
        logger.info("[4/4] Добавление пользователей в базу данных...")
        added_count = 0
        skipped_count = 0

        for user_id in users_to_add:
            try:
                # Парсим информацию из details (если есть username)
                username = None
                first_name = None
                last_name = None

                info = user_info.get(user_id)
                if info and info.get('details'):
                    details = info['details']
                    # Пытаемся извлечь username из details (формат: "username=...")
                    if 'username=' in details:
                        try:
                            username = details.split('username=')[1].split(',')[0].strip()
                        except:
                            pass

                # Создаем запись пользователя с минимальными данными
                db.save_user(
                    user_id=user_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    default_query=None,  # Будет установлено позже пользователем
                    default_mode=None,
                    daily_notifications=False,
                    notification_time='21:00'
                )

                added_count += 1
                if added_count % 10 == 0:
                    logger.info(f"     Добавлено пользователей: {added_count}/{len(users_to_add)}")

            except Exception as e:
                logger.warning(f"     Ошибка при добавлении пользователя {user_id}: {e}")
                skipped_count += 1

        logger.info("=" * 60)
        logger.info("ВОССТАНОВЛЕНИЕ ЗАВЕРШЕНО")
        logger.info("=" * 60)
        logger.info(f"Всего пользователей в логах: {len(all_user_ids)}")
        logger.info(f"Уже было в базе: {len(existing_user_ids)}")
        logger.info(f"Добавлено новых: {added_count}")
        logger.info(f"Пропущено (ошибки): {skipped_count}")

        # Финальная проверка
        final_users = db.get_all_users()
        logger.info(f"Итого пользователей в базе: {len(final_users)}")

        # Показываем статистику по активным пользователям
        active_users = [u for u in final_users if u.get('default_query')]
        logger.info(f"Активных пользователей (с установленной группой): {len(active_users)}")

        return True

    except Exception as e:
        logger.error(f"КРИТИЧЕСКАЯ ОШИБКА при восстановлении: {e}", exc_info=True)
        return False

def restore_users_from_bot_data():
    """Попытка восстановить пользователей из bot_data.pickle (если доступно)"""
    try:
        import pickle
        bot_data_path = Path("bot_data.pickle")

        if not bot_data_path.exists():
            logger.info("Файл bot_data.pickle не найден, пропускаем")
            return False

        logger.info("Попытка восстановления из bot_data.pickle...")

        with open(bot_data_path, 'rb') as f:
            bot_data = pickle.load(f)

        # Проверяем наличие данных о пользователях
        if 'users_data_cache' in bot_data:
            logger.info(f"Найдено пользователей в кеше: {len(bot_data['users_data_cache'])}")
            # Можно добавить логику восстановления из кеша
            return True

        return False

    except Exception as e:
        logger.warning(f"Не удалось восстановить из bot_data.pickle: {e}")
        return False

if __name__ == "__main__":
    logger.info("Запуск скрипта восстановления пользователей")
    logger.info(f"База данных: {DB_PATH}")

    # Пытаемся восстановить из activity_log
    success = restore_users_from_activity_log()

    # Дополнительно пытаемся восстановить из bot_data.pickle
    restore_users_from_bot_data()

    if success:
        logger.info("Скрипт выполнен успешно!")
        sys.exit(0)
    else:
        logger.error("Скрипт завершился с ошибками")
        sys.exit(1)

