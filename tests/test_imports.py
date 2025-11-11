"""
Тесты для проверки импортов всех модулей
"""
import sys
import os

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_import_app_modules():
    """Проверка импорта основных модулей приложения"""
    try:
        import app
        import app.main
        import app.handlers
        import app.schedule
        import app.export
        import app.database
        import app.http
        import app.jobs
        import app.utils
        import app.constants
        import app.config
        print("[OK] Все основные модули успешно импортированы")
        return True
    except ImportError as e:
        print(f"[ERROR] Ошибка импорта: {e}")
        return False


def test_import_admin_modules():
    """Проверка импорта модулей админ-панели"""
    try:
        import app.admin
        import app.admin.handlers
        import app.admin.database
        import app.admin.utils
        print("[OK] Все модули админ-панели успешно импортированы")
        return True
    except ImportError as e:
        print(f"[ERROR] Ошибка импорта админ-модулей: {e}")
        return False


def test_import_telegram_modules():
    """Проверка импорта модулей telegram"""
    try:
        from telegram import Update, Bot
        from telegram.ext import Application, CommandHandler
        from telegram.error import NetworkError, TimedOut, BadRequest
        print("[OK] Все модули telegram успешно импортированы")
        return True
    except ImportError as e:
        print(f"[ERROR] Ошибка импорта telegram модулей: {e}")
        return False


if __name__ == "__main__":
    print("=" * 50)
    print("Тестирование импортов модулей")
    print("=" * 50)
    
    results = []
    results.append(test_import_app_modules())
    results.append(test_import_admin_modules())
    results.append(test_import_telegram_modules())
    
    print("=" * 50)
    if all(results):
        print("[OK] Все тесты импортов пройдены успешно")
        sys.exit(0)
    else:
        print("[ERROR] Некоторые тесты импортов не пройдены")
        sys.exit(1)

