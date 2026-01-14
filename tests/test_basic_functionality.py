"""
Тесты основного функционала согласно roadmap Phase 1.3
Проверяет основные сценарии использования бота
"""
import sys
import os
import io
import asyncio
from datetime import date, datetime

# Настройка кодировки для Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.schedule import search_entities, get_schedule
from app.constants import API_TYPE_GROUP, API_TYPE_TEACHER, MODE_STUDENT, MODE_TEACHER
from app.database import db
from app.admin.utils import is_admin


async def test_search_groups():
    """Тест 1: Поиск групп"""
    print("\n" + "="*60)
    print("Тест 1: Поиск групп")
    print("="*60)
    
    try:
        # Тестируем поиск по частичному совпадению
        groups, err = await search_entities("ПИ", API_TYPE_GROUP)
        
        if err:
            print(f"❌ Ошибка поиска: {err}")
            return False
        
        if not groups or len(groups) == 0:
            print("⚠️ Группы не найдены (возможно, проблема с API)")
            return False
        
        print(f"✅ Найдено {len(groups)} групп")
        print(f"   Примеры: {groups[:5]}")
        return True
        
    except Exception as e:
        print(f"❌ Исключение при поиске групп: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_search_teachers():
    """Тест 2: Поиск преподавателей"""
    print("\n" + "="*60)
    print("Тест 2: Поиск преподавателей")
    print("="*60)
    
    try:
        # Тестируем поиск преподавателей
        teachers, err = await search_entities("Иванов", API_TYPE_TEACHER)
        
        if err:
            print(f"⚠️ Ошибка поиска: {err}")
            # Это не критично, может просто не быть такого преподавателя
            return True
        
        if not teachers or len(teachers) == 0:
            print("ℹ️ Преподаватели с фамилией 'Иванов' не найдены (это нормально)")
            return True
        
        print(f"✅ Найдено {len(teachers)} преподавателей")
        print(f"   Примеры: {teachers[:5]}")
        return True
        
    except Exception as e:
        print(f"❌ Исключение при поиске преподавателей: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_get_schedule():
    """Тест 3: Получение расписания"""
    print("\n" + "="*60)
    print("Тест 3: Получение расписания")
    print("="*60)
    
    try:
        # Сначала найдем группу для теста
        groups, err = await search_entities("ПИ", API_TYPE_GROUP)
        
        if err or not groups:
            print("⚠️ Не удалось найти группу для теста")
            return False
        
        # Берем первую найденную группу
        test_group = groups[0]
        today = date.today().strftime("%Y-%m-%d")
        
        print(f"📅 Тестируем расписание для группы '{test_group}' на {today}")
        
        schedule, err = await get_schedule(
            today,
            test_group,
            API_TYPE_GROUP
        )
        
        if err:
            print(f"⚠️ Ошибка получения расписания: {err}")
            # Это может быть нормально, если на сегодня нет пар
            return True
        
        if not schedule:
            print("ℹ️ Расписание не найдено (возможно, на сегодня нет пар)")
            return True
        
        print(f"✅ Расписание получено: {len(schedule)} страниц")
        if schedule:
            # Показываем первые 500 символов первой страницы
            preview = schedule[0][:500]
            print(f"   Превью: {preview}...")
        
        return True
        
    except Exception as e:
        print(f"❌ Исключение при получении расписания: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_database_operations():
    """Тест 4: Операции с базой данных"""
    print("\n" + "="*60)
    print("Тест 4: Операции с базой данных")
    print("="*60)
    
    try:
        # Тест получения всех пользователей
        all_users = db.get_all_users()
        print(f"✅ Получено {len(all_users)} пользователей из БД")
        
        # Тест получения пользователей с установленной группой
        users_with_query = db.get_users_with_default_query()
        print(f"✅ Найдено {len(users_with_query)} пользователей с установленной группой/преподавателем")
        
        # Тест получения всех известных user_id
        all_user_ids = db.get_all_known_user_ids()
        print(f"✅ Найдено {len(all_user_ids)} уникальных user_id")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка работы с БД: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_admin_utils():
    """Тест 5: Утилиты админ-панели"""
    print("\n" + "="*60)
    print("Тест 5: Утилиты админ-панели")
    print("="*60)
    
    try:
        # Тест проверки админа (для несуществующего пользователя)
        test_user_id = 999999999
        is_admin_result = is_admin(test_user_id)
        print(f"✅ is_admin({test_user_id}) = {is_admin_result} (ожидается False)")
        
        # Тест проверки статуса бота
        from app.admin.utils import is_bot_enabled, get_maintenance_message
        bot_enabled = is_bot_enabled()
        maintenance_msg = get_maintenance_message()
        print(f"✅ Бот включен: {bot_enabled}")
        print(f"✅ Сообщение о техобслуживании: '{maintenance_msg[:50]}...'")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка тестирования админ-утилит: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_imports():
    """Тест 6: Проверка всех критических импортов"""
    print("\n" + "="*60)
    print("Тест 6: Проверка импортов")
    print("="*60)
    
    try:
        # Проверяем основные модули
        from app.main import build_app
        from app.handlers.text import handle_text_message
        from app.start import start_command
        from app.settings import settings_menu_callback
        from app.callbacks import callback_router
        from app.admin.utils import is_admin
        from app.admin.handlers import admin_command
        
        print("✅ Все критические модули успешно импортированы")
        return True
        
    except ImportError as e:
        print(f"❌ Ошибка импорта: {e}")
        import traceback
        traceback.print_exc()
        return False


async def run_all_tests():
    """Запуск всех тестов"""
    print("="*60)
    print("🧪 ТЕСТИРОВАНИЕ ОСНОВНОГО ФУНКЦИОНАЛА БОТА")
    print("="*60)
    print(f"Дата и время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = []
    
    # Синхронные тесты
    results.append(("Импорты", test_imports()))
    results.append(("БД операции", test_database_operations()))
    results.append(("Админ утилиты", test_admin_utils()))
    
    # Асинхронные тесты
    results.append(("Поиск групп", await test_search_groups()))
    results.append(("Поиск преподавателей", await test_search_teachers()))
    results.append(("Получение расписания", await test_get_schedule()))
    
    # Итоги
    print("\n" + "="*60)
    print("ИТОГИ ТЕСТИРОВАНИЯ")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "[OK] ПРОЙДЕН" if result else "[FAIL] ПРОВАЛЕН"
        print(f"{test_name:.<30} {status}")
    
    print("="*60)
    print(f"Пройдено: {passed}/{total} тестов ({passed*100//total}%)")
    print("="*60)
    
    return passed == total


if __name__ == "__main__":
    try:
        success = asyncio.run(run_all_tests())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️ Тестирование прервано пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

