"""
Тесты для проверки работы базы данных
"""
import sys
import os
import tempfile
import shutil

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_database_connection():
    """Проверка подключения к базе данных"""
    try:
        from app.database import db
        
        # Проверяем, что база данных доступна
        # Просто пытаемся выполнить простой запрос
        test_user = db.get_user(999999999)  # Несуществующий пользователь
        # Если не было исключения, значит подключение работает
        
        print("[OK] Подключение к базе данных работает")
        return True
        
    except Exception as e:
        print(f"[ERROR] Ошибка подключения к базе данных: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_admin_database():
    """Проверка работы админской базы данных"""
    try:
        from app.admin.database import admin_db
        
        # Проверяем базовые функции
        status = admin_db.get_bot_status()
        if status is None:
            print("[WARN] Статус бота не получен (возможно, БД не инициализирована)")
        else:
            print("[OK] Админская база данных работает")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Ошибка работы админской БД: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("=" * 50)
    print("Тестирование базы данных")
    print("=" * 50)
    
    results = []
    results.append(test_database_connection())
    results.append(test_admin_database())
    
    print("=" * 50)
    if all(results):
        print("[OK] Все тесты базы данных пройдены успешно")
        sys.exit(0)
    else:
        print("[ERROR] Некоторые тесты не пройдены")
        sys.exit(1)

