#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тест функций экспорта бота
Проверяет работоспособность всех функций экспорта
"""

import asyncio
import sys
import io
from pathlib import Path

# Настройка кодировки для Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Добавляем путь к проекту
sys.path.insert(0, str(Path(__file__).parent))

from app.export import (
    get_week_schedule_structured,
    generate_schedule_image,
    generate_day_schedule_image,
    format_week_schedule_text,
)
from app.schedule import get_schedule_structured
from app.constants import API_TYPE_GROUP, API_TYPE_TEACHER

def print_section(title: str):
    """Печатает заголовок секции"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)

async def test_get_week_schedule():
    """Тест получения расписания на неделю"""
    print_section("ТЕСТ: Получение расписания на неделю")
    
    test_cases = [
        ("ЮР1-251-ОТ", API_TYPE_GROUP, "Группа ЮР1-251-ОТ"),
        ("Фролов С.В.", API_TYPE_TEACHER, "Преподаватель Фролов С.В."),
    ]
    
    for entity_name, entity_type, description in test_cases:
        print(f"\n  📊 Тест: {description}")
        try:
            week_schedule = await get_week_schedule_structured(entity_name, entity_type)
            if week_schedule:
                print(f"     ✅ Получено расписание: {len(week_schedule)} дней")
                for date_str, pairs in list(week_schedule.items())[:3]:
                    print(f"        {date_str}: {len(pairs)} пар")
            else:
                print(f"     ⚠️ Расписание пустое")
        except Exception as e:
            print(f"     ❌ Ошибка: {e}")
            import traceback
            traceback.print_exc()

async def test_generate_images():
    """Тест генерации изображений"""
    print_section("ТЕСТ: Генерация изображений")
    
    # Получаем расписание для теста
    entity_name = "ЮР1-251-ОТ"
    entity_type = API_TYPE_GROUP
    
    print(f"\n  📊 Получение расписания для {entity_name}...")
    week_schedule = await get_week_schedule_structured(entity_name, entity_type)
    
    if not week_schedule:
        print("     ⚠️ Нет расписания для теста")
        return
    
    # Тест генерации недельного изображения
    print(f"\n  📊 Тест: Генерация недельного изображения")
    try:
        img_bytes = await generate_schedule_image(week_schedule, entity_name, entity_type)
        if img_bytes:
            print(f"     ✅ Изображение сгенерировано: {len(img_bytes.getvalue())} байт")
        else:
            print(f"     ❌ Не удалось сгенерировать изображение")
    except Exception as e:
        print(f"     ❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    
    # Тест генерации дневного изображения
    print(f"\n  📊 Тест: Генерация дневного изображения")
    try:
        # Берем первый день с парами
        first_date = list(week_schedule.keys())[0]
        day_schedule, err = await get_schedule_structured(first_date, entity_name, entity_type)
        
        if err or not day_schedule:
            print(f"     ⚠️ Не удалось получить расписание для дня: {err}")
        else:
            img_bytes = await generate_day_schedule_image(day_schedule, entity_name, entity_type)
            if img_bytes:
                print(f"     ✅ Изображение сгенерировано: {len(img_bytes.getvalue())} байт")
            else:
                print(f"     ❌ Не удалось сгенерировать изображение")
    except Exception as e:
        print(f"     ❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

async def test_format_text():
    """Тест форматирования текста"""
    print_section("ТЕСТ: Форматирование текста")
    
    entity_name = "ЮР1-251-ОТ"
    entity_type = API_TYPE_GROUP
    
    print(f"\n  📊 Получение расписания для {entity_name}...")
    week_schedule = await get_week_schedule_structured(entity_name, entity_type)
    
    if not week_schedule:
        print("     ⚠️ Нет расписания для теста")
        return
    
    try:
        text = format_week_schedule_text(week_schedule, entity_name, entity_type)
        if text:
            lines = text.split('\n')
            print(f"     ✅ Текст сгенерирован: {len(lines)} строк, {len(text)} символов")
            print(f"        Первые 3 строки:")
            for line in lines[:3]:
                print(f"        {line[:60]}...")
        else:
            print(f"     ❌ Текст пустой")
    except Exception as e:
        print(f"     ❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

async def main():
    """Главная функция"""
    print("\n" + "=" * 60)
    print("  🚀 ТЕСТИРОВАНИЕ ФУНКЦИЙ ЭКСПОРТА")
    print("=" * 60)
    
    try:
        # Тест получения расписания
        await test_get_week_schedule()
        
        # Тест генерации изображений
        await test_generate_images()
        
        # Тест форматирования текста
        await test_format_text()
        
        print("\n" + "=" * 60)
        print("  ✅ ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
        print("=" * 60 + "\n")
        
    except KeyboardInterrupt:
        print("\n\n  ⚠️ Тестирование прервано пользователем")
    except Exception as e:
        print(f"\n  ❌ Ошибка при тестировании: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())

