#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для тестирования производительности бота
Проверяет скорость работы различных компонентов системы
"""

import time
import asyncio
import statistics
from pathlib import Path
import sys
import io

# Настройка кодировки для Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Добавляем путь к проекту
sys.path.insert(0, str(Path(__file__).parent))

from app.database import db, UserDatabase
from app.schedule import get_schedule
from app.config import DB_PATH, EXPORTS_DIR

def print_section(title: str):
    """Печатает заголовок секции"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)

def print_result(test_name: str, times: list, unit: str = "ms"):
    """Печатает результаты теста"""
    if not times:
        print(f"  ❌ {test_name}: Нет данных")
        return

    avg = statistics.mean(times)
    median = statistics.median(times)
    min_time = min(times)
    max_time = max(times)
    stdev = statistics.stdev(times) if len(times) > 1 else 0

    print(f"  ✅ {test_name}:")
    print(f"     Среднее: {avg:.2f} {unit}")
    print(f"     Медиана: {median:.2f} {unit}")
    print(f"     Мин: {min_time:.2f} {unit}, Макс: {max_time:.2f} {unit}")
    print(f"     Стд. откл.: {stdev:.2f} {unit}")

    # Оценка производительности
    if unit == "ms":
        if avg < 10:
            status = "🟢 Отлично"
        elif avg < 50:
            status = "🟡 Хорошо"
        elif avg < 100:
            status = "🟠 Приемлемо"
        else:
            status = "🔴 Медленно"
        print(f"     Оценка: {status}")

def test_database_operations():
    """Тестирует операции с базой данных"""
    print_section("ТЕСТ: Операции с базой данных")

    # Используем глобальный экземпляр db

    # Тест 1: get_user (с кешем)
    print("\n  📊 Тест 1: get_user (с кешем)")
    test_user_id = 123456789
    times = []

    # Создаем тестового пользователя
    db.save_user(test_user_id, "test_user", "Test", "User", "ИС-21", "student")

    for i in range(10):
        start = time.perf_counter()
        user = db.get_user(test_user_id)
        end = time.perf_counter()
        times.append((end - start) * 1000)  # в миллисекундах

    print_result("get_user (кеш)", times)

    # Тест 2: save_user
    print("\n  📊 Тест 2: save_user")
    times = []
    for i in range(10):
        start = time.perf_counter()
        db.save_user(test_user_id, f"test_user_{i}", "Test", "User", f"ИС-{i}", "student")
        end = time.perf_counter()
        times.append((end - start) * 1000)

    print_result("save_user", times)

    # Тест 3: get_all_users
    print("\n  📊 Тест 3: get_all_users")
    times = []
    for i in range(5):
        start = time.perf_counter()
        users = db.get_all_users()
        end = time.perf_counter()
        times.append((end - start) * 1000)

    print_result("get_all_users", times)
    print(f"     Всего пользователей: {len(users)}")

    # Тест 4: log_activity (batch mode)
    print("\n  📊 Тест 4: log_activity (batch mode)")
    times = []
    for i in range(10):
        start = time.perf_counter()
        db.log_activity(test_user_id, "test_action", f"test_data_{i}")
        end = time.perf_counter()
        times.append((end - start) * 1000)

    print_result("log_activity (batch)", times)

    # Принудительно сбрасываем очередь логов
    db._flush_activity_log_internal()

async def test_schedule_parsing():
    """Тестирует парсинг расписания"""
    print_section("ТЕСТ: Парсинг расписания")

    # Тестовые запросы
    test_cases = [
        ("ИС-21", "student", "2025-01-15"),
        ("ИС-22", "student", "2025-01-15"),
        ("Фролов С.В.", "teacher", "2025-01-15"),
    ]

    all_times = []

    for query, api_type, date in test_cases:
        print(f"\n  📊 Тест: {api_type} - {query} на {date}")
        times = []

        for i in range(3):  # 3 попытки для каждого
            start = time.perf_counter()
            try:
                schedule, error = await get_schedule(date, query, api_type, timeout=10)
                end = time.perf_counter()
                elapsed = (end - start) * 1000
                times.append(elapsed)

                if error:
                    print(f"     ⚠️ Попытка {i+1}: Ошибка - {error[:50]}")
                else:
                    print(f"     ✅ Попытка {i+1}: {elapsed:.2f} ms")
            except Exception as e:
                end = time.perf_counter()
                elapsed = (end - start) * 1000
                times.append(elapsed)
                print(f"     ❌ Попытка {i+1}: Исключение - {str(e)[:50]}")

        if times:
            print_result(f"{api_type} - {query}", times)
            all_times.extend(times)

    if all_times:
        print("\n  📊 Общая статистика парсинга:")
        print_result("Все запросы", all_times)

def test_cache_performance():
    """Тестирует производительность кеша"""
    print_section("ТЕСТ: Производительность кеша")

    # Используем глобальный экземпляр db
    test_user_id = 123456789

    # Первый запрос (без кеша)
    start = time.perf_counter()
    user1 = db.get_user(test_user_id)
    first_time = (time.perf_counter() - start) * 1000

    # Последующие запросы (с кешем)
    times = []
    for i in range(20):
        start = time.perf_counter()
        user = db.get_user(test_user_id)
        end = time.perf_counter()
        times.append((end - start) * 1000)

    print(f"  📊 Первый запрос (без кеша): {first_time:.2f} ms")
    print_result("Последующие запросы (с кешем)", times)

    if times:
        speedup = first_time / statistics.mean(times) if statistics.mean(times) > 0 else 0
        print(f"  🚀 Ускорение благодаря кешу: {speedup:.1f}x")

def test_file_operations():
    """Тестирует операции с файлами"""
    print_section("ТЕСТ: Операции с файлами")

    # Проверка путей
    print(f"  📁 DB_PATH: {DB_PATH}")
    print(f"  📁 EXPORTS_DIR: {EXPORTS_DIR}")

    # Проверка существования директорий
    db_exists = Path(DB_PATH).parent.exists()
    export_exists = Path(EXPORTS_DIR).exists()

    print(f"  📊 Директория БД существует: {'✅' if db_exists else '❌'}")
    print(f"  📊 Директория экспорта существует: {'✅' if export_exists else '❌'}")

    # Тест записи/чтения файла
    export_path = Path(EXPORTS_DIR)
    export_path.mkdir(parents=True, exist_ok=True)
    test_file = export_path / "test_performance.txt"
    times = []

    for i in range(10):
        start = time.perf_counter()
        test_file.write_text(f"Test data {i}")
        content = test_file.read_text()
        test_file.unlink()
        end = time.perf_counter()
        times.append((end - start) * 1000)

    print_result("Запись/чтение файла", times)

def generate_report():
    """Генерирует итоговый отчет"""
    print_section("ИТОГОВЫЙ ОТЧЕТ")

    print("  📋 Рекомендации по оптимизации:")
    print()
    print("  1. ✅ Кеш пользователей - реализован")
    print("  2. ✅ Асинхронное логирование - реализовано")
    print("  3. ✅ Оптимизация запросов к БД - выполнена")
    print()
    print("  🔍 Что стоит проверить дополнительно:")
    print("     - Производительность при большом количестве пользователей")
    print("     - Время ответа API kis.vgltu.ru")
    print("     - Использование памяти при длительной работе")
    print("     - Производительность фоновых задач (jobs)")

def main():
    """Главная функция"""
    print("\n" + "=" * 60)
    print("  🚀 ТЕСТИРОВАНИЕ ПРОИЗВОДИТЕЛЬНОСТИ БОТА")
    print("=" * 60)

    try:
        # Тесты БД
        test_database_operations()

        # Тесты кеша
        test_cache_performance()

        # Тесты файлов
        test_file_operations()

        # Тесты парсинга расписания
        print("\n  ⚠️ Тест парсинга расписания требует подключения к API...")
        print("  ⏭️ Пропущен (запустите вручную при необходимости)")
        # Раскомментируйте следующую строку для запуска теста парсинга:
        # asyncio.run(test_schedule_parsing())

        # Итоговый отчет
        generate_report()

        print("\n" + "=" * 60)
        print("  ✅ ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
        print("=" * 60 + "\n")

    except Exception as e:
        print(f"\n  ❌ Ошибка при тестировании: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()

