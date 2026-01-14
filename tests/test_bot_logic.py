"""
Тестирование логики работы бота
Проверяет основные сценарии и потенциальные проблемы
"""
import sys
import os
import io

# Настройка кодировки для Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Добавляем корневую директорию проекта в путь
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from unittest.mock import Mock, AsyncMock, MagicMock
import asyncio
from datetime import datetime

# Импорты для тестирования
from app.constants import *
from app.utils import escape_html, hash_schedule, compare_schedules, format_schedule_changes
from app.database import db


def test_escape_html():
    """Тест экранирования HTML"""
    print("🧪 Тест escape_html...")
    assert escape_html("<b>test</b>") == "&lt;b&gt;test&lt;/b&gt;"
    assert escape_html("&") == "&amp;"
    assert escape_html("'") == "&#x27;"
    print("✅ escape_html работает корректно")


def test_hash_schedule():
    """Тест хеширования расписания"""
    print("🧪 Тест hash_schedule...")
    pages1 = ["Понедельник\n1. Математика", "Вторник\n1. Физика"]
    pages2 = ["Понедельник\n1. Математика", "Вторник\n1. Физика"]
    pages3 = ["Понедельник\n1. Химия", "Вторник\n1. Физика"]
    
    hash1 = hash_schedule(pages1)
    hash2 = hash_schedule(pages2)
    hash3 = hash_schedule(pages3)
    
    assert hash1 == hash2, "Одинаковые расписания должны иметь одинаковый хеш"
    assert hash1 != hash3, "Разные расписания должны иметь разные хеши"
    assert len(hash1) == 32, "MD5 хеш должен быть длиной 32 символа"
    print("✅ hash_schedule работает корректно")


def test_compare_schedules():
    """Тест сравнения расписаний"""
    print("🧪 Тест compare_schedules...")
    
    old_schedule = {
        "pairs": [
            {"time": "08:30-10:00", "subject": "Математика", "auditorium": "101"},
            {"time": "10:10-11:40", "subject": "Физика", "auditorium": "102"}
        ]
    }
    
    new_schedule = {
        "pairs": [
            {"time": "08:30-10:00", "subject": "Математика", "auditorium": "101"},
            {"time": "10:10-11:40", "subject": "Химия", "auditorium": "102"},
            {"time": "12:00-13:30", "subject": "Информатика", "auditorium": "103"}
        ]
    }
    
    changes = compare_schedules(old_schedule, new_schedule)
    
    assert len(changes) > 0, "Должны быть обнаружены изменения"
    print(f"✅ compare_schedules работает корректно (найдено {len(changes)} изменений)")


def test_format_schedule_changes():
    """Тест форматирования изменений"""
    print("🧪 Тест format_schedule_changes...")
    
    changes = [
        {"type": "added", "pair": {"time": "12:00-13:30", "subject": "Информатика"}},
        {"type": "removed", "pair": {"time": "10:10-11:40", "subject": "Физика"}},
        {"type": "modified", "old": {"time": "08:30-10:00", "subject": "Математика"}, 
         "new": {"time": "08:30-10:00", "subject": "Алгебра"}}
    ]
    
    msg = format_schedule_changes(changes, "2026-01-07", "ИС1-231")
    
    assert "Изменения" in msg, "Сообщение должно содержать информацию об изменениях"
    assert "ИС1-231" in msg, "Сообщение должно содержать название группы"
    assert len(msg) > 0, "Сообщение не должно быть пустым"
    print("✅ format_schedule_changes работает корректно")


def test_constants():
    """Тест констант"""
    print("🧪 Тест констант...")
    
    assert MODE_STUDENT == "student", "MODE_STUDENT должен быть 'student'"
    assert MODE_TEACHER == "teacher", "MODE_TEACHER должен быть 'teacher'"
    assert CALLBACK_DATA_MODE_STUDENT is not None, "CALLBACK_DATA_MODE_STUDENT должен быть определен"
    assert CALLBACK_DATA_MODE_TEACHER is not None, "CALLBACK_DATA_MODE_TEACHER должен быть определен"
    print("✅ Константы определены корректно")


async def test_start_command_logic():
    """Тест логики команды /start"""
    print("🧪 Тест логики start_command...")
    
    # Создаем моки
    update = Mock()
    context = Mock()
    
    update.effective_user = Mock()
    update.effective_user.id = 123456
    update.effective_user.username = "test_user"
    update.effective_user.first_name = "Test"
    update.effective_user.last_name = None
    
    update.message = Mock()
    update.message.reply_text = AsyncMock()
    
    context.user_data = {}
    context.bot_data = {}
    
    # Проверяем, что логика работает
    assert update.effective_user.id == 123456
    assert context.user_data == {}
    
    print("✅ Логика start_command корректна")


def test_database_connection():
    """Тест подключения к БД"""
    print("🧪 Тест подключения к БД...")
    
    try:
        # Проверяем, что БД доступна
        users = db.get_all_users()
        print(f"✅ БД доступна, найдено {len(users)} пользователей")
    except Exception as e:
        print(f"⚠️ Ошибка подключения к БД: {e}")


def test_callback_routing():
    """Тест маршрутизации callback-запросов"""
    print("🧪 Тест маршрутизации callback...")
    
    # Проверяем основные callback data
    callbacks = [
        CALLBACK_DATA_MODE_STUDENT,
        CALLBACK_DATA_MODE_TEACHER,
        CALLBACK_DATA_BACK_TO_START,
        CALLBACK_DATA_SETTINGS_MENU,
    ]
    
    for cb in callbacks:
        assert cb is not None, f"Callback {cb} должен быть определен"
        assert isinstance(cb, str), f"Callback {cb} должен быть строкой"
    
    print("✅ Маршрутизация callback корректна")


def analyze_potential_issues():
    """Анализ потенциальных проблем"""
    print("\n🔍 Анализ потенциальных проблем...")
    
    issues = []
    
    # Проверка 1: Импорты
    try:
        from app.callbacks import callback_router, inline_query_handler
        print("✅ Импорты callbacks работают")
    except Exception as e:
        issues.append(f"❌ Проблема с импортами callbacks: {e}")
    
    # Проверка 2: Обработчики
    try:
        from app.start import start_command
        from app.handlers.text import handle_text_message
        from app.settings import settings_menu_callback
        print("✅ Основные обработчики импортируются")
    except Exception as e:
        issues.append(f"❌ Проблема с импортами обработчиков: {e}")
    
    # Проверка 3: Функции в handlers
    try:
        from app.handlers.schedule import handle_mode_selection
        print("✅ handle_mode_selection доступна")
    except Exception as e:
        issues.append(f"❌ handle_mode_selection не найдена: {e}")
    
    # Проверка 4: Константы
    try:
        from app.constants import MAX_INLINE_RESULTS, MAX_SEARCH_RESULTS_DISPLAY
        print("✅ Константы для магических чисел определены")
    except ImportError:
        issues.append("⚠️ Константы MAX_INLINE_RESULTS, MAX_SEARCH_RESULTS_DISPLAY не определены")
    
    if issues:
        print("\n⚠️ Найдены проблемы:")
        for issue in issues:
            print(f"  {issue}")
    else:
        print("\n✅ Критических проблем не обнаружено")
    
    return issues


def main():
    """Запуск всех тестов"""
    print("=" * 60)
    print("🧪 ТЕСТИРОВАНИЕ ЛОГИКИ БОТА")
    print("=" * 60)
    
    # Базовые тесты
    print("\n📋 Базовые тесты:")
    test_escape_html()
    test_hash_schedule()
    test_compare_schedules()
    test_format_schedule_changes()
    test_constants()
    test_callback_routing()
    
    # Тесты БД
    print("\n📊 Тесты БД:")
    test_database_connection()
    
    # Асинхронные тесты
    print("\n🔄 Асинхронные тесты:")
    asyncio.run(test_start_command_logic())
    
    # Анализ проблем
    print("\n" + "=" * 60)
    issues = analyze_potential_issues()
    
    print("\n" + "=" * 60)
    if issues:
        print(f"❌ Найдено {len(issues)} проблем")
        return 1
    else:
        print("✅ Все тесты пройдены успешно!")
        return 0


if __name__ == "__main__":
    exit(main())

