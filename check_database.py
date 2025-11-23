#!/usr/bin/env python3
"""
Скрипт для проверки и отображения содержимого базы данных
Использование:
    python check_database.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.database import db, DB_PATH
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def check_database():
    """Проверить содержимое базы данных"""
    print("=" * 60)
    print("ПРОВЕРКА БАЗЫ ДАННЫХ")
    print("=" * 60)
    print(f"Путь к базе данных: {DB_PATH}")
    print(f"Файл существует: {Path(DB_PATH).exists()}")
    
    if Path(DB_PATH).exists():
        size = Path(DB_PATH).stat().st_size
        print(f"Размер файла: {size / 1024:.2f} KB")
    
    print("\n" + "=" * 60)
    print("СТАТИСТИКА ПОЛЬЗОВАТЕЛЕЙ")
    print("=" * 60)
    
    try:
        all_users = db.get_all_users()
        print(f"Всего пользователей в базе: {len(all_users)}")
        
        users_with_query = db.get_users_with_default_query()
        print(f"Пользователей с установленной группой/преподавателем: {len(users_with_query)}")
        
        if users_with_query:
            print("\nАктивные пользователи (с установленной группой/преподавателем):")
            print("-" * 60)
            for i, user in enumerate(users_with_query, 1):
                print(f"{i}. user_id={user['user_id']}")
                print(f"   Группа/Преподаватель: {user.get('default_query', 'N/A')}")
                print(f"   Режим: {user.get('default_mode', 'N/A')}")
                print(f"   Уведомления: {'Включены' if user.get('daily_notifications') else 'Выключены'}")
                print(f"   Время уведомлений: {user.get('notification_time', 'N/A')}")
                print()
        
        if all_users:
            print("\nВсе пользователи в базе:")
            print("-" * 60)
            for i, user in enumerate(all_users[:20], 1):  # Показываем первые 20
                has_query = bool(user.get('default_query'))
                status = "✓ Активен" if has_query else "○ Неактивен"
                print(f"{i}. user_id={user['user_id']} | {status} | username={user.get('username', 'N/A')}")
            if len(all_users) > 20:
                print(f"... и еще {len(all_users) - 20} пользователей")
        
        # Проверяем activity_log
        print("\n" + "=" * 60)
        print("СТАТИСТИКА ЛОГОВ АКТИВНОСТИ")
        print("=" * 60)
        
        all_user_ids = db.get_all_known_user_ids(include_activity_log=True)
        print(f"Уникальных user_id в логах активности: {len(all_user_ids)}")
        
    except Exception as e:
        print(f"ОШИБКА: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_database()

