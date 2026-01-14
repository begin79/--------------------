import logging
from collections import defaultdict
from time import time
from typing import Tuple, Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RateLimitStats:
    """Статистика rate limiting"""
    total_requests: int
    blocked_requests: int
    active_users: int
    top_offenders: list  # [(user_id, blocked_count), ...]


class RateLimiter:
    """Улучшенный rate limiter на основе sliding window с статистикой"""

    def __init__(self):
        self.requests = defaultdict(list)  # user_id: [timestamp1, timestamp2, ...]
        self.blocked_count = defaultdict(int)  # user_id: количество заблокированных запросов
        self.total_requests_count = 0
        self.total_blocked_count = 0

    def check_limit(
        self,
        user_id: int,
        max_requests: int = 10,
        window: int = 60
    ) -> Tuple[bool, int]:
        """
        Проверка лимита запросов

        Args:
            user_id: ID пользователя
            max_requests: Максимум запросов в окне
            window: Размер окна в секундах

        Returns:
            (allowed, seconds_to_wait)
        """
        now = time()
        user_requests = self.requests[user_id]
        self.total_requests_count += 1

        # Очистить старые запросы
        user_requests = [t for t in user_requests if now - t < window]

        if len(user_requests) >= max_requests:
            # Вычислить время ожидания
            oldest_request = user_requests[0]
            seconds_to_wait = int(window - (now - oldest_request)) + 1
            self.blocked_count[user_id] += 1
            self.total_blocked_count += 1
            logger.debug(f"Rate limit: пользователь {user_id} заблокирован на {seconds_to_wait}с")
            return False, seconds_to_wait

        # Добавить новый запрос
        user_requests.append(now)
        self.requests[user_id] = user_requests

        return True, 0
    
    def get_stats(self) -> RateLimitStats:
        """Получить статистику rate limiting"""
        # Топ нарушителей (по количеству заблокированных запросов)
        top_offenders = sorted(
            self.blocked_count.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]
        
        return RateLimitStats(
            total_requests=self.total_requests_count,
            blocked_requests=self.total_blocked_count,
            active_users=len(self.requests),
            top_offenders=top_offenders
        )
    
    def reset_stats(self):
        """Сбросить статистику (но не данные о запросах)"""
        self.total_requests_count = 0
        self.total_blocked_count = 0
        self.blocked_count.clear()

    def cleanup(self, max_age: int = 300):
        """Очистка старых данных (вызывать периодически)"""
        now = time()
        users_to_remove = []

        for user_id, timestamps in self.requests.items():
            # Удалить пользователей без активности > max_age секунд
            if not timestamps or (now - timestamps[-1]) > max_age:
                users_to_remove.append(user_id)
            else:
                # Очистить старые timestamps
                self.requests[user_id] = [
                    t for t in timestamps if (now - t) < max_age
                ]

        for user_id in users_to_remove:
            del self.requests[user_id]

        if users_to_remove:
            logger.debug(f"Rate limiter: очищено {len(users_to_remove)} неактивных пользователей")


# Глобальный экземпляр
rate_limiter = RateLimiter()