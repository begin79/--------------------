#!/usr/bin/env python3
"""
Комплексные тесты производительности для нагрузки 1000 пользователей
Тестирует скорость обработки запросов, параллельность, память
"""
import asyncio
import time
import statistics
import sys
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

# Добавляем корневую директорию в путь
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from app.database import UserDatabase

# Инициализация БД
db = UserDatabase()

def print_section(title: str):
    """Красиво выводит заголовок секции"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)

def print_result(test_name: str, times: List[float], unit: str = "ms", details: Dict[str, Any] = None):
    """Выводит результаты теста в красивом формате"""
    if not times:
        print(f"  ERROR {test_name}: Нет данных")
        return
    
    avg = statistics.mean(times)
    median = statistics.median(times)
    min_time = min(times)
    max_time = max(times)
    stdev = statistics.stdev(times) if len(times) > 1 else 0
    
    # Оценка производительности
    if avg < 10:
        status = "GREEN Отлично"
    elif avg < 50:
        status = "YELLOW Хорошо"
    elif avg < 100:
        status = "ORANGE Приемлемо"
    else:
        status = "RED Требует оптимизации"
    
    print(f"\n  {test_name}:")
    print(f"     Среднее: {avg:.2f} {unit}")
    print(f"     Медиана: {median:.2f} {unit}")
    print(f"     Мин: {min_time:.2f} {unit}")
    print(f"     Макс: {max_time:.2f} {unit}")
    print(f"     Стд. откл.: {stdev:.2f} {unit}")
    print(f"     Оценка: {status}")
    
    if details:
        for key, value in details.items():
            print(f"     {key}: {value}")

async def test_concurrent_users(num_users: int = 1000, concurrent: int = 50):
    """Тестирует производительность при одновременных запросах от множества пользователей"""
    print_section(f"ТЕСТ: Одновременные запросы от {num_users} пользователей (по {concurrent} параллельно)")
    
    # Создаем тестовых пользователей
    print(f"\n  Создание {num_users} тестовых пользователей...")
    test_users = []
    start = time.perf_counter()
    
    for i in range(num_users):
        user_id = 2000000 + i
        db.save_user(
            user_id,
            f"load_test_{i}",
            f"Load{i}",
            f"Test{i}",
            f"ИС-{20 + (i % 10)}",
            "student"
        )
        test_users.append(user_id)
    
    creation_time = (time.perf_counter() - start) * 1000
    print(f"  OK Создано за {creation_time:.2f} ms ({creation_time/num_users:.3f} ms/пользователь)")
    
    # Тест параллельного чтения
    print(f"\n  Тест параллельного чтения ({concurrent} одновременных запросов)...")
    
    async def read_user(user_id: int) -> float:
        start_time = time.perf_counter()
        db.get_user(user_id)
        return (time.perf_counter() - start_time) * 1000
    
    # Запускаем несколько раундов параллельных запросов
    all_times = []
    rounds = num_users // concurrent
    
    for round_num in range(rounds):
        start_idx = round_num * concurrent
        end_idx = min(start_idx + concurrent, num_users)
        user_batch = test_users[start_idx:end_idx]
        
        start = time.perf_counter()
        tasks = [read_user(uid) for uid in user_batch]
        round_times = await asyncio.gather(*tasks)
        round_duration = (time.perf_counter() - start) * 1000
        
        all_times.extend(round_times)
        
        if (round_num + 1) % 10 == 0:
            print(f"     Раунд {round_num + 1}/{rounds}: {round_duration:.2f} ms для {len(user_batch)} запросов")
    
    print_result(
        f"Параллельное чтение ({num_users} запросов)",
        all_times,
        details={
            "Всего раундов": rounds,
            "Запросов в раунде": concurrent,
            "Общее время": f"{sum(all_times):.2f} ms"
        }
    )
    
    return test_users

async def test_database_write_performance(num_users: int = 1000):
    """Тестирует производительность записи в БД"""
    print_section(f"ТЕСТ: Производительность записи в БД ({num_users} операций)")
    
    times = []
    test_users = []
    
    for i in range(num_users):
        user_id = 3000000 + i
        start = time.perf_counter()
        db.save_user(
            user_id,
            f"write_test_{i}",
            f"Write{i}",
            f"Test{i}",
            f"ИС-{20 + (i % 10)}",
            "student"
        )
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)
        test_users.append(user_id)
        
        if (i + 1) % 100 == 0:
            print(f"     Обработано: {i + 1}/{num_users}")
    
    print_result(
        f"Запись в БД ({num_users} операций)",
        times,
        details={
            "Всего операций": num_users,
            "Общее время": f"{sum(times):.2f} ms",
            "Операций/сек": f"{num_users / (sum(times) / 1000):.1f}"
        }
    )
    
    return test_users

async def test_cache_efficiency(num_requests: int = 1000):
    """Тестирует эффективность кеширования"""
    print_section(f"ТЕСТ: Эффективность кеширования ({num_requests} запросов)")
    
    # Создаем тестового пользователя
    test_user_id = 4000000
    db.save_user(
        test_user_id,
        "cache_test",
        "Cache",
        "Test",
        "ИС-227",
        "student"
    )
    
    # Первый запрос (без кеша)
    start = time.perf_counter()
    db.get_user(test_user_id)
    first_request_time = (time.perf_counter() - start) * 1000
    
    # Последующие запросы (с кешем)
    cached_times = []
    for i in range(num_requests - 1):
        start = time.perf_counter()
        db.get_user(test_user_id)
        elapsed = (time.perf_counter() - start) * 1000
        cached_times.append(elapsed)
    
    avg_cached = statistics.mean(cached_times) if cached_times else 0
    speedup = first_request_time / avg_cached if avg_cached > 0 else float('inf')
    
    print(f"\n  Результаты:")
    print(f"     Первый запрос (без кеша): {first_request_time:.2f} ms")
    print(f"     Среднее с кешем: {avg_cached:.3f} ms")
    print(f"     Ускорение: {speedup:.1f}x")
    print(f"     Экономия времени: {(first_request_time - avg_cached) * num_requests:.2f} ms")

async def test_activity_logging_performance(num_logs: int = 1000):
    """Тестирует производительность логирования активности"""
    print_section(f"ТЕСТ: Логирование активности ({num_logs} записей)")
    
    test_user_id = 5000000
    times = []
    
    for i in range(num_logs):
        start = time.perf_counter()
        db.log_activity(test_user_id, "test_action", f"test_data_{i}")
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)
        
        if (i + 1) % 100 == 0:
            print(f"     Обработано: {i + 1}/{num_logs}")
    
    print_result(
        f"Логирование активности ({num_logs} записей)",
        times,
        details={
            "Всего записей": num_logs,
            "Записей/сек": f"{num_logs / (sum(times) / 1000):.1f}"
        }
    )

async def test_memory_usage(num_users: int = 1000):
    """Тестирует использование памяти"""
    print_section(f"ТЕСТ: Использование памяти ({num_users} пользователей)")
    
    import psutil
    import os
    
    process = psutil.Process(os.getpid())
    
    # Память до создания пользователей
    mem_before = process.memory_info().rss / 1024 / 1024  # MB
    
    # Создаем пользователей
    test_users = []
    for i in range(num_users):
        user_id = 6000000 + i
        db.save_user(
            user_id,
            f"mem_test_{i}",
            f"Mem{i}",
            f"Test{i}",
            f"ИС-{20 + (i % 10)}",
            "student"
        )
        test_users.append(user_id)
    
    # Память после создания
    mem_after = process.memory_info().rss / 1024 / 1024  # MB
    mem_diff = mem_after - mem_before
    
    print(f"\n  Результаты:")
    print(f"     Память до: {mem_before:.2f} MB")
    print(f"     Память после: {mem_after:.2f} MB")
    print(f"     Использовано: {mem_diff:.2f} MB")
    print(f"     На пользователя: {mem_diff / num_users * 1024:.2f} KB")
    
    if mem_diff / num_users > 1:  # Больше 1 MB на пользователя
        print(f"     WARNING: Высокое использование памяти!")
    else:
        print(f"     OK Использование памяти в норме")

async def test_query_performance(num_queries: int = 1000):
    """Тестирует производительность различных запросов"""
    print_section(f"ТЕСТ: Производительность запросов ({num_queries} операций)")
    
    # Тест get_all_users
    print(f"\n  Тест: get_all_users")
    times = []
    for i in range(10):  # Меньше итераций, т.к. операция тяжелая
        start = time.perf_counter()
        users = db.get_all_users()
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)
    
    print_result(
        "get_all_users",
        times,
        details={"Всего пользователей": len(users) if times else 0}
    )
    
    # Тест поиска пользователя
    print(f"\n  Тест: Поиск пользователя")
    test_user_id = 7000000
    db.save_user(test_user_id, "search_test", "Search", "Test", "ИС-227", "student")
    
    times = []
    for i in range(num_queries):
        start = time.perf_counter()
        db.get_user(test_user_id)
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)
    
    print_result(f"Поиск пользователя ({num_queries} запросов)", times)

async def main():
    """Главная функция запуска всех тестов"""
    print("=" * 70)
    print("  КОМПЛЕКСНОЕ ТЕСТИРОВАНИЕ ПРОИЗВОДИТЕЛЬНОСТИ")
    print("  Нагрузка: 1000 пользователей")
    print("=" * 70)
    
    start_time = time.perf_counter()
    
    try:
        # Тест параллельных пользователей
        test_users = await test_concurrent_users(1000, 50)
        
        # Тест записи в БД
        await test_database_write_performance(1000)
        
        # Тест эффективности кеша
        await test_cache_efficiency(1000)
        
        # Тест логирования
        await test_activity_logging_performance(1000)
        
        # Тест памяти
        try:
            await test_memory_usage(1000)
        except ImportError:
            print("\n  ⚠️ psutil не установлен, пропускаем тест памяти")
        
        # Тест запросов
        await test_query_performance(1000)
        
        total_time = time.perf_counter() - start_time
        
        print_section("ИТОГОВЫЙ ОТЧЕТ")
        print(f"\n  OK Все тесты завершены")
        print(f"  Общее время выполнения: {total_time:.2f} секунд")
        print(f"  Протестировано операций: ~5000+")
        print(f"\n  Рекомендации:")
        print(f"     - Проверьте средние времена отклика")
        print(f"     - Обратите внимание на операции с оценкой RED")
        print(f"     - Оптимизируйте операции, превышающие 100ms")
        
    except Exception as e:
        print(f"\n  ERROR Ошибка при выполнении тестов: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())

