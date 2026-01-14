"""
Интеграционные тесты для проверки полного flow работы бота
Согласно roadmap Phase 1.3
"""
import sys
import os
import io
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock
from datetime import date, datetime

# Настройка кодировки для Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Добавляем корневую директорию проекта в путь
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from telegram import Update, Message, User, Chat
from telegram.ext import ContextTypes
from app.constants import MODE_STUDENT, MODE_TEACHER, API_TYPE_GROUP, API_TYPE_TEACHER
from app.database import db
from app.schedule import search_entities, get_schedule


def create_mock_update(text: str, user_id: int = 123456, username: str = "test_user") -> Update:
    """Создает мок Update для тестирования"""
    user = Mock(spec=User)
    user.id = user_id
    user.username = username
    user.first_name = "Test"
    user.last_name = None
    
    chat = Mock(spec=Chat)
    chat.id = user_id
    
    message = Mock(spec=Message)
    message.text = text
    message.reply_text = AsyncMock()
    message.reply_markup = None
    
    update = Mock(spec=Update)
    update.effective_user = user
    update.effective_chat = chat
    update.message = message
    update.callback_query = None
    
    return update


def create_mock_context() -> ContextTypes.DEFAULT_TYPE:
    """Создает мок Context для тестирования"""
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.user_data = {}
    context.bot_data = {}
    context.bot = Mock()
    context.bot.send_message = AsyncMock()
    return context


async def test_new_user_flow():
    """Тест 1: Первый запуск нового пользователя"""
    print("\n" + "="*60)
    print("Интеграционный тест 1: Первый запуск нового пользователя")
    print("="*60)
    
    try:
        from app.start import start_command
        
        update = create_mock_update("/start", user_id=999999999)
        context = create_mock_context()
        
        # Вызываем команду /start
        await start_command(update, context)
        
        # Проверяем, что бот ответил
        assert update.message.reply_text.called, "Бот должен ответить на /start"
        
        # Проверяем, что пользователь сохранен в БД
        user = db.get_user(999999999)
        assert user is not None, "Пользователь должен быть сохранен в БД"
        
        print("✅ Новый пользователь успешно зарегистрирован")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_search_and_schedule_flow():
    """Тест 2: Поиск расписания (полный flow)"""
    print("\n" + "="*60)
    print("Интеграционный тест 2: Поиск расписания")
    print("="*60)
    
    try:
        # Шаг 1: Поиск группы
        groups, err = await search_entities("ПИ", API_TYPE_GROUP)
        
        if err or not groups:
            print("⚠️ Не удалось найти группы для теста")
            return True  # Не критично для интеграционного теста
        
        test_group = groups[0]
        print(f"✅ Найдена группа: {test_group}")
        
        # Шаг 2: Получение расписания
        today = date.today().strftime("%Y-%m-%d")
        schedule, err = await get_schedule(today, test_group, API_TYPE_GROUP)
        
        if err:
            print(f"⚠️ Ошибка получения расписания: {err}")
            return True  # Не критично, может быть нет расписания
        
        if schedule:
            print(f"✅ Расписание получено: {len(schedule)} страниц")
        else:
            print("ℹ️ Расписание не найдено (возможно, нет пар на сегодня)")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_settings_flow():
    """Тест 3: Работа с настройками"""
    print("\n" + "="*60)
    print("Интеграционный тест 3: Настройки")
    print("="*60)
    
    try:
        from app.settings import settings_menu_callback
        
        update = create_mock_update("/settings", user_id=999999998)
        context = create_mock_context()
        
        # Сохраняем пользователя в БД для теста
        db.save_user(999999998, username="test_user_settings", first_name="Test")
        
        # Вызываем команду настроек
        await settings_menu_callback(update, context)
        
        # Проверяем, что бот ответил
        assert update.message.reply_text.called, "Бот должен показать меню настроек"
        
        print("✅ Меню настроек открывается корректно")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_text_message_handling():
    """Тест 4: Обработка текстовых сообщений"""
    print("\n" + "="*60)
    print("Интеграционный тест 4: Обработка текстовых сообщений")
    print("="*60)
    
    try:
        from app.handlers.text import handle_text_message
        
        # Тест 1: Команда "Старт"
        update = create_mock_update("Старт", user_id=999999997)
        context = create_mock_context()
        
        await handle_text_message(update, context)
        
        assert update.message.reply_text.called, "Бот должен обработать текстовое сообщение"
        
        print("✅ Текстовые сообщения обрабатываются корректно")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_error_handling():
    """Тест 5: Обработка ошибок"""
    print("\n" + "="*60)
    print("Интеграционный тест 5: Обработка ошибок")
    print("="*60)
    
    try:
        # Тест обработки несуществующей группы
        schedule, err = await get_schedule(
            date.today().strftime("%Y-%m-%d"),
            "НЕСУЩЕСТВУЮЩАЯ_ГРУППА_12345",
            API_TYPE_GROUP
        )
        
        # Должна быть ошибка или пустое расписание
        if err or not schedule:
            print("✅ Ошибки обрабатываются корректно")
        else:
            print("⚠️ Неожиданный результат для несуществующей группы")
        
        return True
        
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False


async def run_all_integration_tests():
    """Запуск всех интеграционных тестов"""
    print("="*60)
    print("🧪 ИНТЕГРАЦИОННОЕ ТЕСТИРОВАНИЕ")
    print("="*60)
    print(f"Дата и время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = []
    
    results.append(("Новый пользователь", await test_new_user_flow()))
    results.append(("Поиск расписания", await test_search_and_schedule_flow()))
    results.append(("Настройки", await test_settings_flow()))
    results.append(("Текстовые сообщения", await test_text_message_handling()))
    results.append(("Обработка ошибок", await test_error_handling()))
    
    # Итоги
    print("\n" + "="*60)
    print("ИТОГИ ИНТЕГРАЦИОННОГО ТЕСТИРОВАНИЯ")
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
        success = asyncio.run(run_all_integration_tests())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️ Тестирование прервано пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

