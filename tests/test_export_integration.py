#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Интеграционный тест экспорта
Проверяет полный цикл экспорта от начала до конца
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
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.export import (
    get_week_schedule_structured,
    generate_schedule_image,
    generate_day_schedule_image,
)
from app.schedule import get_schedule_structured
from app.constants import API_TYPE_GROUP, API_TYPE_TEACHER
import hashlib

def print_section(title: str):
    """Печатает заголовок секции"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)

async def test_export_week_image():
    """Тест экспорта недели картинкой"""
    print_section("ТЕСТ: Экспорт недели картинкой")

    test_cases = [
        ("ЮР1-251-ОТ", API_TYPE_GROUP, "Группа ЮР1-251-ОТ"),
        ("Фролов С.В.", API_TYPE_TEACHER, "Преподаватель Фролов С.В."),
    ]

    for entity_name, entity_type, description in test_cases:
        print(f"\n  📊 Тест: {description}")
        try:
            # Получаем расписание
            print(f"     ⏳ Получение расписания...")
            week_schedule = await get_week_schedule_structured(entity_name, entity_type)

            if not week_schedule:
                print(f"     ⚠️ Расписание пустое")
                continue

            print(f"     ✅ Получено расписание: {len(week_schedule)} дней")

            # Генерируем изображение
            print(f"     ⏳ Генерация изображения...")
            img_bytes = await generate_schedule_image(week_schedule, entity_name, entity_type)

            if img_bytes:
                size = len(img_bytes.getvalue())
                print(f"     ✅ Изображение сгенерировано: {size} байт ({size/1024:.1f} KB)")

                # Проверяем, что изображение не пустое
                if size > 1000:
                    print(f"     ✅ Изображение валидно (размер > 1 KB)")
                else:
                    print(f"     ⚠️ Изображение слишком маленькое")
            else:
                print(f"     ❌ Не удалось сгенерировать изображение")

        except Exception as e:
            print(f"     ❌ Ошибка: {e}")
            import traceback
            traceback.print_exc()

async def test_export_semester():
    """Тест экспорта семестра"""
    print_section("ТЕСТ: Экспорт семестра")

    try:
        from excel_export.export_semester import (
            resolve_semester_bounds,
            fetch_semester_schedule,
            build_excel_workbook,
        )
        from io import BytesIO

        entity_name = "ЮР1-251-ОТ"
        entity_type = API_TYPE_GROUP

        print(f"\n  📊 Тест: Группа {entity_name}")

        # Определяем границы семестра
        start_date, end_date, semester_label = resolve_semester_bounds("autumn", None, None, None)
        print(f"     📅 Семестр: {semester_label}")
        print(f"     📅 Период: {start_date} - {end_date}")

        # Получаем расписание
        print(f"     ⏳ Получение расписания...")
        timetable = await fetch_semester_schedule(entity_name, entity_type, start_date, end_date)

        if not timetable:
            print(f"     ⚠️ Расписание пустое")
            return

        print(f"     ✅ Получено расписаний: {len(timetable)}")

        # Строим Excel
        print(f"     ⏳ Построение Excel...")
        workbook, per_group_rows, per_teacher_rows, total_hours, per_group_hours, per_teacher_hours = build_excel_workbook(
            entity_name, "student", semester_label, timetable
        )

        # Сохраняем в буфер
        main_buffer = BytesIO()
        workbook.save(main_buffer)
        main_buffer.seek(0)
        size = len(main_buffer.getvalue())

        print(f"     ✅ Excel файл создан: {size} байт ({size/1024:.1f} KB)")
        print(f"     📊 Всего часов: {total_hours:.1f}")

    except Exception as e:
        print(f"     ❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

async def test_export_data_storage():
    """Тест сохранения данных для экспорта"""
    print_section("ТЕСТ: Сохранение данных для экспорта")

    # Симулируем сохранение данных как в send_schedule_with_pagination
    query = "ЮР1-251-ОТ"
    mode = "student"
    query_hash = hashlib.md5(query.encode('utf-8')).hexdigest()[:12]
    export_key = f"export_{mode}_{query_hash}"

    print(f"\n  📊 Тест: Сохранение данных")
    print(f"     Query: {query}")
    print(f"     Mode: {mode}")
    print(f"     Hash: {query_hash}")
    print(f"     Key: {export_key}")

    # Симулируем user_data
    user_data = {}
    user_data[export_key] = query

    # Проверяем восстановление
    entity_name = user_data.get(export_key)
    if entity_name == query:
        print(f"     ✅ Данные сохранены и восстановлены корректно")
    else:
        print(f"     ❌ Ошибка восстановления данных")

async def main():
    """Главная функция"""
    print("\n" + "=" * 60)
    print("  🚀 ИНТЕГРАЦИОННОЕ ТЕСТИРОВАНИЕ ЭКСПОРТА")
    print("=" * 60)

    try:
        # Тест сохранения данных
        await test_export_data_storage()

        # Тест экспорта недели
        await test_export_week_image()

        # Тест экспорта семестра
        await test_export_semester()

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

