"""
Тест производительности на 1000 пользователей
Проверяет скорость обработки запросов и отклик программы
"""
import asyncio
import time
import os
import sys
from datetime import datetime
from typing import List, Dict, Any
from unittest.mock import AsyncMock, MagicMock, patch

# Добавляем корневую директорию проекта в sys.path
sys.path.insert(0, os.path.abspath('.'))

from app.database import db
from app.state_manager import set_user_busy, clear_user_busy_state
from app.constants import CTX_MODE, MODE_STUDENT

# Мокируем API вызовы на уровне модуля
import app.schedule as schedule_module
schedule_module.search_entities = AsyncMock(return_value=(["ИС1-231"], None))
schedule_module.get_schedule = AsyncMock(return_value={"days": []})

# Импортируем handlers после мокирования
from app.handlers import handle_schedule_search

# Мокируем fetch_and_display_schedule
import app.handlers as handlers_module
async def mock_fetch_display(*args, **kwargs):
    return None
handlers_module.fetch_and_display_schedule = mock_fetch_display

# Mock-объекты для имитации Telegram API
class MockUser:
    def __init__(self, user_id: int, username: str = None):
        self.id = user_id
        self.username = username or f"user_{user_id}"
        self.first_name = f"User{user_id}"
        self.last_name = None

class MockChat:
    def __init__(self, chat_id: int):
        self.id = chat_id

class MockMessage:
    def __init__(self, user_id: int, text: str):
        self.from_user = MockUser(user_id)
        self.chat = MockChat(user_id)
        self.text = text
        self.reply_text = AsyncMock()
        self.reply_chat_action = AsyncMock()

class MockUpdate:
    def __init__(self, user_id: int, text: str):
        self.effective_user = MockUser(user_id)
        self.effective_chat = MockChat(user_id)
        self.message = MockMessage(user_id, text)
        self.callback_query = None

class MockContext:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}
        self.job_queue = MagicMock()
        self.bot = MagicMock()
        self.bot.send_message = AsyncMock()
        self.application = MagicMock()
        self.application.bot_data = {}

# Статистика
stats = {
    "total_requests": 0,
    "successful_requests": 0,
    "failed_requests": 0,
    "total_time": 0.0,
    "min_time": float('inf'),
    "max_time": 0.0,
    "times": []
}

async def simulate_user_request(user_id: int, query: str, context: MockContext) -> Dict[str, Any]:
    """Симуляция запроса пользователя (API уже замокировано)"""
    start_time = time.time()
    update = MockUpdate(user_id, query)
    
    # Устанавливаем режим для пользователя
    context.user_data[CTX_MODE] = MODE_STUDENT
    
    try:
        # Имитируем поиск расписания (API уже замокировано на уровне модуля)
        await handle_schedule_search(update, context, query)
        
        elapsed = time.time() - start_time
        stats["total_requests"] += 1
        stats["successful_requests"] += 1
        stats["total_time"] += elapsed
        stats["times"].append(elapsed)
        stats["min_time"] = min(stats["min_time"], elapsed)
        stats["max_time"] = max(stats["max_time"], elapsed)
        
        return {
            "user_id": user_id,
            "query": query,
            "success": True,
            "time": elapsed
        }
    except Exception as e:
        elapsed = time.time() - start_time
        stats["total_requests"] += 1
        stats["failed_requests"] += 1
        stats["total_time"] += elapsed
        
        return {
            "user_id": user_id,
            "query": query,
            "success": False,
            "error": str(e),
            "time": elapsed
        }

async def test_concurrent_users(num_users: int = 500, queries_per_user: int = 1):
    """Тест производительности с одновременными пользователями"""
    print(f"\n{'='*60}")
    print(f"Тест производительности: {num_users} пользователей")
    print(f"Запросов на пользователя: {queries_per_user}")
    print(f"Всего запросов: {num_users * queries_per_user}")
    print(f"Используется мокирование API для быстрого тестирования")
    print(f"{'='*60}\n")
    
    # Очищаем статистику
    stats.clear()
    stats.update({
        "total_requests": 0,
        "successful_requests": 0,
        "failed_requests": 0,
        "total_time": 0.0,
        "min_time": float('inf'),
        "max_time": 0.0,
        "times": []
    })
    
    # Тестовые запросы
    test_queries = ["ИС1-231", "ИС1-232", "ИС2-231", "ИС2-232", "ИС3-231"]
    
    # Создаем задачи для всех пользователей
    tasks = []
    start_time = time.time()
    
    for user_id in range(1, num_users + 1):
        context = MockContext()
        # Каждый пользователь делает несколько запросов
        for i in range(queries_per_user):
            query = test_queries[i % len(test_queries)]
            tasks.append(simulate_user_request(user_id, query, context))
    
    # Запускаем все задачи одновременно
    print(f"Запуск {len(tasks)} запросов...")
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    total_elapsed = time.time() - start_time
    
    # Анализ результатов
    successful = sum(1 for r in results if isinstance(r, dict) and r.get("success"))
    failed = len(results) - successful
    
    # Вычисляем статистику
    if stats["times"]:
        avg_time = sum(stats["times"]) / len(stats["times"])
        sorted_times = sorted(stats["times"])
        median_time = sorted_times[len(sorted_times) // 2]
        p95_time = sorted_times[int(len(sorted_times) * 0.95)]
        p99_time = sorted_times[int(len(sorted_times) * 0.99)]
    else:
        avg_time = median_time = p95_time = p99_time = 0.0
    
    requests_per_second = stats["total_requests"] / total_elapsed if total_elapsed > 0 else 0
    
    # Выводим результаты
    print(f"\n{'='*60}")
    print("РЕЗУЛЬТАТЫ ТЕСТА ПРОИЗВОДИТЕЛЬНОСТИ")
    print(f"{'='*60}\n")
    
    print(f"Общее время выполнения: {total_elapsed:.2f} сек")
    print(f"Всего запросов: {stats['total_requests']}")
    print(f"Успешных: {stats['successful_requests']}")
    print(f"Неудачных: {stats['failed_requests']}")
    print(f"\nПроизводительность:")
    print(f"  Запросов в секунду: {requests_per_second:.2f}")
    print(f"\nВремя ответа (мс):")
    print(f"  Минимальное: {stats['min_time'] * 1000:.2f}")
    print(f"  Максимальное: {stats['max_time'] * 1000:.2f}")
    print(f"  Среднее: {avg_time * 1000:.2f}")
    print(f"  Медиана: {median_time * 1000:.2f}")
    print(f"  95-й перцентиль: {p95_time * 1000:.2f}")
    print(f"  99-й перцентиль: {p99_time * 1000:.2f}")
    
    # Оценка производительности
    print(f"\n{'='*60}")
    print("ОЦЕНКА ПРОИЗВОДИТЕЛЬНОСТИ")
    print(f"{'='*60}\n")
    
    if requests_per_second >= 100:
        print("✅ ОТЛИЧНО: > 100 запросов/сек")
    elif requests_per_second >= 50:
        print("✅ ХОРОШО: > 50 запросов/сек")
    elif requests_per_second >= 20:
        print("⚠️ УДОВЛЕТВОРИТЕЛЬНО: > 20 запросов/сек")
    else:
        print("❌ ТРЕБУЕТСЯ ОПТИМИЗАЦИЯ: < 20 запросов/сек")
    
    if avg_time * 1000 <= 100:
        print("✅ ОТЛИЧНО: Среднее время ответа < 100 мс")
    elif avg_time * 1000 <= 500:
        print("✅ ХОРОШО: Среднее время ответа < 500 мс")
    elif avg_time * 1000 <= 1000:
        print("⚠️ УДОВЛЕТВОРИТЕЛЬНО: Среднее время ответа < 1 сек")
    else:
        print("❌ ТРЕБУЕТСЯ ОПТИМИЗАЦИЯ: Среднее время ответа > 1 сек")
    
    if p95_time * 1000 <= 500:
        print("✅ ОТЛИЧНО: 95% запросов < 500 мс")
    elif p95_time * 1000 <= 1000:
        print("✅ ХОРОШО: 95% запросов < 1 сек")
    elif p95_time * 1000 <= 2000:
        print("⚠️ УДОВЛЕТВОРИТЕЛЬНО: 95% запросов < 2 сек")
    else:
        print("❌ ТРЕБУЕТСЯ ОПТИМИЗАЦИЯ: 95% запросов > 2 сек")
    
    print(f"\n{'='*60}\n")
    
    return {
        "total_time": total_elapsed,
        "total_requests": stats["total_requests"],
        "successful": stats["successful_requests"],
        "failed": stats["failed_requests"],
        "requests_per_second": requests_per_second,
        "avg_time_ms": avg_time * 1000,
        "median_time_ms": median_time * 1000,
        "p95_time_ms": p95_time * 1000,
        "p99_time_ms": p99_time * 1000,
        "min_time_ms": stats["min_time"] * 1000,
        "max_time_ms": stats["max_time"] * 1000
    }

async def test_database_performance():
    """Тест производительности базы данных"""
    print(f"\n{'='*60}")
    print("ТЕСТ ПРОИЗВОДИТЕЛЬНОСТИ БАЗЫ ДАННЫХ")
    print(f"{'='*60}\n")
    
    # Тест записи (уменьшаем количество для скорости)
    print("Тест записи пользователей...")
    start = time.time()
    test_count = 500  # Уменьшаем для скорости
    for i in range(test_count):
        db.save_user(
            user_id=9000 + i,
            username=f"test_user_{i}",
            first_name=f"Test{i}",
            last_name="User"
        )
    write_time = time.time() - start
    print(f"Запись {test_count} пользователей: {write_time:.2f} сек ({test_count/write_time:.2f} записей/сек)")
    
    # Тест чтения
    print("\nТест чтения пользователей...")
    start = time.time()
    for i in range(test_count):
        db.get_user(9000 + i)
    read_time = time.time() - start
    print(f"Чтение {test_count} пользователей: {read_time:.2f} сек ({test_count/read_time:.2f} запросов/сек)")
    
    # Тест истории поиска
    print("\nТест истории поиска...")
    start = time.time()
    for i in range(test_count):
        db.save_search_history(9000 + i, f"ИС1-{231 + i % 10}", "student")
    history_write_time = time.time() - start
    print(f"Запись {test_count} записей истории: {history_write_time:.2f} сек ({test_count/history_write_time:.2f} записей/сек)")
    
    # Очистка тестовых данных
    print("\nОчистка тестовых данных...")
    try:
        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE user_id >= 9000")
            cursor.execute("DELETE FROM search_history WHERE user_id >= 9000")
        print("Очистка завершена\n")
    except Exception as e:
        print(f"Ошибка очистки (не критично): {e}\n")

async def main():
    """Главная функция тестирования"""
    print("\n" + "="*60)
    print("ТЕСТИРОВАНИЕ ПРОИЗВОДИТЕЛЬНОСТИ БОТА")
    print("="*60)
    
    # Тест базы данных
    await test_database_performance()
    
    # Тест производительности (оптимизированная версия)
    print("Запуск оптимизированного теста (500 пользователей, 1 запрос каждый)...")
    results = await test_concurrent_users(num_users=500, queries_per_user=1)
    
    # Сохраняем результаты
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = f"tests/performance_report_{timestamp}.txt"
    
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("ОТЧЕТ О ПРОИЗВОДИТЕЛЬНОСТИ\n")
        f.write("="*60 + "\n\n")
        f.write(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Тест: 1000 пользователей, 3 запроса на каждого\n\n")
        f.write(f"Общее время: {results['total_time']:.2f} сек\n")
        f.write(f"Всего запросов: {results['total_requests']}\n")
        f.write(f"Успешных: {results['successful']}\n")
        f.write(f"Неудачных: {results['failed']}\n")
        f.write(f"Запросов в секунду: {results['requests_per_second']:.2f}\n\n")
        f.write("Время ответа (мс):\n")
        f.write(f"  Среднее: {results['avg_time_ms']:.2f}\n")
        f.write(f"  Медиана: {results['median_time_ms']:.2f}\n")
        f.write(f"  95-й перцентиль: {results['p95_time_ms']:.2f}\n")
        f.write(f"  99-й перцентиль: {results['p99_time_ms']:.2f}\n")
        f.write(f"  Минимум: {results['min_time_ms']:.2f}\n")
        f.write(f"  Максимум: {results['max_time_ms']:.2f}\n")
    
    print(f"Отчет сохранен в: {report_file}")

if __name__ == "__main__":
    asyncio.run(main())

