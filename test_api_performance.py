#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тест производительности API kis.vgltu.ru
Проверяет время ответа и надежность API
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

from app.schedule import get_schedule
from app.constants import API_TYPE_GROUP, API_TYPE_TEACHER

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
        if avg < 500:
            status = "🟢 Отлично"
        elif avg < 1000:
            status = "🟡 Хорошо"
        elif avg < 2000:
            status = "🟠 Приемлемо"
        else:
            status = "🔴 Медленно"
        print(f"     Оценка: {status}")

async def test_api_performance():
    """Тестирует время ответа API kis.vgltu.ru"""
    print_section("ТЕСТ: Время ответа API kis.vgltu.ru")
    
    # Тестовые запросы - разные группы и преподаватели
    test_cases = [
        ("ИС-21", API_TYPE_GROUP, "2025-01-15", "Группа ИС-21"),
        ("ИС-22", API_TYPE_GROUP, "2025-01-15", "Группа ИС-22"),
        ("ИС-23", API_TYPE_GROUP, "2025-01-15", "Группа ИС-23"),
        ("Фролов С.В.", API_TYPE_TEACHER, "2025-01-15", "Преподаватель Фролов С.В."),
        ("Иванов И.И.", API_TYPE_TEACHER, "2025-01-15", "Преподаватель Иванов И.И."),
    ]
    
    all_times = []
    success_count = 0
    error_count = 0
    timeout_count = 0
    errors_list = []
    
    print("\n  📊 Тестирование различных запросов...")
    print("  ⚠️ Это может занять некоторое время...\n")
    
    for query, api_type, date, description in test_cases:
        api_type_name = "student" if api_type == API_TYPE_GROUP else "teacher"
        print(f"  📊 Тест: {description} ({api_type_name})")
        times = []
        case_success = 0
        case_errors = 0
        
        for i in range(3):  # 3 попытки для каждого
            start = time.perf_counter()
            try:
                schedule, error = await get_schedule(date, query, api_type)
                end = time.perf_counter()
                elapsed = (end - start) * 1000
                times.append(elapsed)
                
                if error:
                    print(f"     ⚠️ Попытка {i+1}: Ошибка ({elapsed:.2f} ms) - {error[:60]}")
                    case_errors += 1
                    error_count += 1
                    errors_list.append(f"{description}: {error[:60]}")
                else:
                    print(f"     ✅ Попытка {i+1}: {elapsed:.2f} ms - успешно")
                    case_success += 1
                    success_count += 1
            except asyncio.TimeoutError:
                end = time.perf_counter()
                elapsed = (end - start) * 1000
                times.append(elapsed)
                print(f"     ⏱️ Попытка {i+1}: Таймаут ({elapsed:.2f} ms)")
                timeout_count += 1
                case_errors += 1
                error_count += 1
                errors_list.append(f"{description}: Таймаут")
            except Exception as e:
                end = time.perf_counter()
                elapsed = (end - start) * 1000
                times.append(elapsed)
                print(f"     ❌ Попытка {i+1}: Исключение ({elapsed:.2f} ms) - {str(e)[:60]}")
                case_errors += 1
                error_count += 1
                errors_list.append(f"{description}: {str(e)[:60]}")
            
            # Небольшая задержка между запросами
            await asyncio.sleep(0.5)
        
        if times:
            print_result(f"{description}", times)
            all_times.extend(times)
            print(f"     Успешных: {case_success}/3, Ошибок: {case_errors}/3")
        print()
    
    # Общая статистика
    if all_times:
        print_section("ОБЩАЯ СТАТИСТИКА API")
        print_result("Все запросы к API", all_times)
        print(f"\n  📊 Статистика успешности:")
        print(f"     Успешных запросов: {success_count}")
        print(f"     Ошибок: {error_count}")
        print(f"     Таймаутов: {timeout_count}")
        total_requests = success_count + error_count
        if total_requests > 0:
            success_rate = (success_count / total_requests) * 100
            print(f"     Процент успеха: {success_rate:.1f}%")
            
            if success_rate >= 90:
                status = "🟢 Отлично"
            elif success_rate >= 70:
                status = "🟡 Хорошо"
            elif success_rate >= 50:
                status = "🟠 Приемлемо"
            else:
                status = "🔴 Плохо"
            print(f"     Оценка надежности: {status}")
        
        if errors_list:
            print(f"\n  ⚠️ Список ошибок:")
            for i, error in enumerate(errors_list[:10], 1):  # Показываем первые 10
                print(f"     {i}. {error}")
            if len(errors_list) > 10:
                print(f"     ... и еще {len(errors_list) - 10} ошибок")
    
    # Рекомендации
    print_section("РЕКОМЕНДАЦИИ")
    if all_times:
        avg_time = statistics.mean(all_times)
        if avg_time > 2000:
            print("  ⚠️ API отвечает медленно (>2 сек)")
            print("     Рекомендация: Добавить кэширование ответов API")
        elif avg_time > 1000:
            print("  ⚠️ API отвечает умеренно медленно (1-2 сек)")
            print("     Рекомендация: Рассмотреть кэширование для часто запрашиваемых данных")
        else:
            print("  ✅ API отвечает быстро (<1 сек)")
            print("     Кэширование опционально, но может снизить нагрузку на сервер")
        
        if error_count > success_count:
            print("\n  ⚠️ Высокий процент ошибок!")
            print("     Рекомендация: Проверить доступность API и добавить retry-логику")
        elif error_count > 0:
            print("\n  ⚠️ Есть ошибки в запросах")
            print("     Рекомендация: Добавить обработку ошибок и retry для критичных запросов")
        else:
            print("\n  ✅ Все запросы успешны!")
            print("     API работает стабильно")

async def test_api_concurrent_requests():
    """Тестирует производительность при одновременных запросах"""
    print_section("ТЕСТ: Одновременные запросы к API")
    
    print("\n  📊 Тестирование 5 одновременных запросов...")
    
    async def make_request(query, api_type, date, request_num):
        start = time.perf_counter()
        try:
            schedule, error = await get_schedule(date, query, api_type)
            elapsed = (time.perf_counter() - start) * 1000
            if error:
                return {"success": False, "time": elapsed, "error": error[:50], "request": request_num}
            return {"success": True, "time": elapsed, "request": request_num}
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return {"success": False, "time": elapsed, "error": str(e)[:50], "request": request_num}
    
    # Создаем 5 одновременных запросов
    tasks = [
        make_request("ИС-21", API_TYPE_GROUP, "2025-01-15", 1),
        make_request("ИС-22", API_TYPE_GROUP, "2025-01-15", 2),
        make_request("ИС-23", API_TYPE_GROUP, "2025-01-15", 3),
        make_request("Фролов С.В.", API_TYPE_TEACHER, "2025-01-15", 4),
        make_request("ИС-21", API_TYPE_GROUP, "2025-01-16", 5),
    ]
    
    start_total = time.perf_counter()
    results = await asyncio.gather(*tasks)
    total_time = (time.perf_counter() - start_total) * 1000
    
    success_count = sum(1 for r in results if r.get("success"))
    times = [r["time"] for r in results]
    
    print(f"\n  ✅ Выполнено 5 запросов за {total_time:.2f} ms")
    print(f"     Успешных: {success_count}/5")
    print(f"     Среднее время на запрос: {statistics.mean(times):.2f} ms")
    print(f"     Параллельная эффективность: {(sum(times) / total_time * 100):.1f}%")
    
    print("\n  📊 Детали запросов:")
    for r in results:
        status = "✅" if r.get("success") else "❌"
        print(f"     {status} Запрос {r['request']}: {r['time']:.2f} ms", end="")
        if not r.get("success"):
            print(f" - {r.get('error', 'Ошибка')}")
        else:
            print()

def main():
    """Главная функция"""
    print("\n" + "=" * 60)
    print("  🚀 ТЕСТИРОВАНИЕ ПРОИЗВОДИТЕЛЬНОСТИ API kis.vgltu.ru")
    print("=" * 60)
    
    try:
        # Основной тест API
        asyncio.run(test_api_performance())
        
        # Тест одновременных запросов
        print("\n  📊 Запуск теста одновременных запросов...")
        asyncio.run(test_api_concurrent_requests())
        
        print("\n" + "=" * 60)
        print("  ✅ ТЕСТИРОВАНИЕ API ЗАВЕРШЕНО")
        print("=" * 60 + "\n")
        
    except KeyboardInterrupt:
        print("\n\n  ⚠️ Тестирование прервано пользователем")
    except Exception as e:
        print(f"\n  ❌ Ошибка при тестировании: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()

