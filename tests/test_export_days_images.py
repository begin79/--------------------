"""
Тест для функции export_days_images
"""
import asyncio
import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import Update, CallbackQuery, Message, User, Chat
from telegram.ext import ContextTypes

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.handlers.export import export_days_images
from app.constants import CALLBACK_DATA_EXPORT_DAYS_IMAGES, MODE_STUDENT, API_TYPE_GROUP


class MockCallbackQuery:
    def __init__(self, data: str):
        self.data = data
        self.message = MagicMock()
        self.message.reply_text = AsyncMock()
        self.message.reply_photo = AsyncMock()
        self.message.reply_media_group = AsyncMock()
        self.message.chat_id = 12345
        self.message.message_id = 1


class MockUpdate:
    def __init__(self, callback_data: str):
        self.callback_query = MockCallbackQuery(callback_data)
        self.effective_user = MagicMock()
        self.effective_user.id = 1003795435
        self.effective_user.username = "test_user"


class MockContext:
    def __init__(self):
        self.user_data = {
            "export_student_e8367d634734": "ТД1-221-ОТ"
        }
        self.bot_data = {}


async def test_export_days_images_basic():
    """Базовый тест функции export_days_images"""
    print("\n" + "="*60)
    print("Тест: export_days_images - базовая проверка")
    print("="*60)

    # Создаем мок-объекты
    callback_data = f"{CALLBACK_DATA_EXPORT_DAYS_IMAGES}_student_e8367d634734"
    update = MockUpdate(callback_data)
    context = MockContext()

    # Мокаем необходимые функции
    with patch('app.handlers.export.safe_answer_callback_query', new_callable=AsyncMock) as mock_answer, \
         patch('app.handlers.export.is_user_busy', return_value=False), \
         patch('app.handlers.export.user_busy_context') as mock_busy_context, \
         patch('app.handlers.export.ExportProgress') as mock_progress_class, \
         patch('app.export.get_week_schedule_structured', new_callable=AsyncMock) as mock_get_week, \
         patch('app.schedule.get_schedule_structured', new_callable=AsyncMock) as mock_get_day, \
         patch('app.export.generate_day_schedule_image', new_callable=AsyncMock) as mock_generate:

        # Настраиваем моки
        mock_busy_context.return_value.__enter__ = MagicMock()
        mock_busy_context.return_value.__exit__ = MagicMock(return_value=None)

        mock_progress = MagicMock()
        mock_progress.start = AsyncMock()
        mock_progress.update = AsyncMock()
        mock_progress.finish = AsyncMock()
        mock_progress_class.return_value = mock_progress

        # Мокаем get_week_schedule_structured - возвращаем расписание на неделю
        today = datetime.date.today()
        days_since_monday = today.weekday()
        if days_since_monday == 6:
            monday = today + datetime.timedelta(days=1)
        else:
            monday = today - datetime.timedelta(days=days_since_monday)

        week_schedule = {}
        for day_offset in range(6):
            current_date = monday + datetime.timedelta(days=day_offset)
            date_str = current_date.strftime("%Y-%m-%d")
            week_schedule[date_str] = [
                {
                    "time": "08:30-10:00",
                    "subject": "Тест",
                    "groups": ["ТД1-221-ОТ"],
                    "auditorium": "101",
                    "teacher": "Тестовый Преподаватель"
                }
            ]
        mock_get_week.return_value = week_schedule

        # Мокаем get_schedule_structured для каждого дня
        def mock_get_day_side_effect(date_str, entity_name, entity_type):
            return {
                "date": date_str,
                "pairs": [
                    {
                        "time": "08:30-10:00",
                        "subject": "Тест",
                        "groups": ["ТД1-221-ОТ"],
                        "auditorium": "101",
                        "teacher": "Тестовый Преподаватель"
                    }
                ]
            }, None

        mock_get_day.side_effect = mock_get_day_side_effect

        # Мокаем generate_day_schedule_image - возвращаем байты изображения
        mock_image_bytes = b"fake_image_data"
        mock_generate.return_value = mock_image_bytes

        # Вызываем функцию
        try:
            await export_days_images(update, context, callback_data)
            print("✅ Функция выполнилась без исключений")

            # Проверяем, что были вызовы
            assert mock_answer.called, "safe_answer_callback_query должен быть вызван"
            print("✅ safe_answer_callback_query вызван")

            assert mock_progress.start.called, "progress.start должен быть вызван"
            print("✅ progress.start вызван")

            assert mock_get_week.called, "get_week_schedule_structured должен быть вызван"
            print("✅ get_week_schedule_structured вызван")

            # Проверяем, что get_schedule_structured вызывался для дней
            assert mock_get_day.called, "get_schedule_structured должен быть вызван"
            print(f"✅ get_schedule_structured вызван {mock_get_day.call_count} раз(а)")

            # Проверяем, что generate_day_schedule_image вызывался
            assert mock_generate.called, "generate_day_schedule_image должен быть вызван"
            print(f"✅ generate_day_schedule_image вызван {mock_generate.call_count} раз(а)")

            # Проверяем, что были попытки отправить фото
            if update.callback_query.message.reply_media_group.called:
                print("✅ reply_media_group вызван")
            elif update.callback_query.message.reply_photo.called:
                print("✅ reply_photo вызван (fallback)")
            else:
                print("⚠️ Ни reply_media_group, ни reply_photo не были вызваны")

            print("\n✅ Тест пройден успешно!")
            return True

        except Exception as e:
            print(f"\n❌ Ошибка при выполнении теста: {e}")
            import traceback
            traceback.print_exc()
            return False


async def test_export_days_images_empty_schedule():
    """Тест с пустым расписанием"""
    print("\n" + "="*60)
    print("Тест: export_days_images - пустое расписание")
    print("="*60)

    callback_data = f"{CALLBACK_DATA_EXPORT_DAYS_IMAGES}_student_e8367d634734"
    update = MockUpdate(callback_data)
    context = MockContext()

    with patch('app.handlers.export.safe_answer_callback_query', new_callable=AsyncMock), \
         patch('app.handlers.export.is_user_busy', return_value=False), \
         patch('app.handlers.export.user_busy_context') as mock_busy_context, \
         patch('app.handlers.export.ExportProgress') as mock_progress_class, \
         patch('app.export.get_week_schedule_structured', new_callable=AsyncMock) as mock_get_week, \
         patch('app.schedule.get_schedule_structured', new_callable=AsyncMock) as mock_get_day:

        mock_busy_context.return_value.__enter__ = MagicMock()
        mock_busy_context.return_value.__exit__ = MagicMock(return_value=None)

        mock_progress = MagicMock()
        mock_progress.start = AsyncMock()
        mock_progress.update = AsyncMock()
        mock_progress.finish = AsyncMock()
        mock_progress_class.return_value = mock_progress

        # Пустое расписание
        mock_get_week.return_value = {}

        # Пустое расписание для каждого дня
        mock_get_day.return_value = ({"date": "2025-12-15", "pairs": []}, None)

        try:
            await export_days_images(update, context, callback_data)
            print("✅ Функция обработала пустое расписание без ошибок")

            # Проверяем, что finish был вызван
            assert mock_progress.finish.called, "progress.finish должен быть вызван"
            print("✅ progress.finish вызван")

            print("\n✅ Тест пройден успешно!")
            return True

        except Exception as e:
            print(f"\n❌ Ошибка: {e}")
            import traceback
            traceback.print_exc()
            return False


async def main():
    """Запуск всех тестов"""
    print("\n" + "="*60)
    print("ЗАПУСК ТЕСТОВ ДЛЯ export_days_images")
    print("="*60)

    results = []

    # Тест 1: Базовая проверка
    result1 = await test_export_days_images_basic()
    results.append(("Базовая проверка", result1))

    # Тест 2: Пустое расписание
    result2 = await test_export_days_images_empty_schedule()
    results.append(("Пустое расписание", result2))

    # Итоги
    print("\n" + "="*60)
    print("ИТОГИ ТЕСТИРОВАНИЯ")
    print("="*60)
    for name, result in results:
        status = "✅ ПРОЙДЕН" if result else "❌ ПРОВАЛЕН"
        print(f"{name}: {status}")

    all_passed = all(result for _, result in results)
    print("\n" + "="*60)
    if all_passed:
        print("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ")
    else:
        print("❌ НЕКОТОРЫЕ ТЕСТЫ ПРОВАЛЕНЫ")
    print("="*60)

    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)

