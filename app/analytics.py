"""
Модуль для сбора и анализа данных об использовании бота
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict, Counter
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class UserAnalytics:
    """Аналитика по пользователю"""
    user_id: int
    username: Optional[str]
    first_name: Optional[str]
    total_requests: int
    requests_last_24h: int
    requests_last_7d: int
    favorite_query: Optional[str]
    favorite_mode: Optional[str]
    last_active: Optional[str]
    created_at: Optional[str]
    has_notifications: bool


@dataclass
class UsageStats:
    """Общая статистика использования"""
    total_users: int
    active_users_24h: int
    active_users_7d: int
    total_requests_24h: int
    total_requests_7d: int
    popular_queries: List[Tuple[str, int]]
    popular_modes: Dict[str, int]
    requests_by_hour: Dict[int, int]
    peak_hour: int


class AnalyticsCollector:
    """Сборщик аналитики использования бота"""
    
    def __init__(self, database, monitoring):
        """
        Args:
            database: Экземпляр UserDatabase
            monitoring: Экземпляр ParserMonitor
        """
        self.db = database
        self.monitoring = monitoring
    
    def get_user_analytics(self, user_id: int) -> Optional[UserAnalytics]:
        """Получить аналитику по конкретному пользователю"""
        try:
            user = self.db.get_user(user_id)
            if not user:
                return None
            
            # Получаем статистику запросов из мониторинга
            now = datetime.now()
            last_24h = now - timedelta(hours=24)
            last_7d = now - timedelta(days=7)
            
            # Подсчитываем запросы пользователя из логов мониторинга
            user_requests_24h = 0
            user_requests_7d = 0
            total_requests = 0
            
            for req in self.monitoring.user_requests:
                if req.get('user_id') == user_id:
                    total_requests += 1
                    req_time = datetime.fromisoformat(req.get('timestamp', now.isoformat()))
                    if req_time >= last_24h:
                        user_requests_24h += 1
                    if req_time >= last_7d:
                        user_requests_7d += 1
            
            # Получаем самую популярную группу/преподавателя из activity_log
            favorite_query = user.get('default_query')
            favorite_mode = user.get('default_mode')
            
            return UserAnalytics(
                user_id=user_id,
                username=user.get('username'),
                first_name=user.get('first_name'),
                total_requests=total_requests,
                requests_last_24h=user_requests_24h,
                requests_last_7d=user_requests_7d,
                favorite_query=favorite_query,
                favorite_mode=favorite_mode,
                last_active=user.get('last_active'),
                created_at=user.get('created_at'),
                has_notifications=bool(user.get('daily_notifications'))
            )
        except Exception as e:
            logger.error(f"Ошибка получения аналитики пользователя {user_id}: {e}", exc_info=True)
            return None
    
    def get_usage_stats(self, days: int = 7) -> UsageStats:
        """Получить общую статистику использования"""
        try:
            all_users = self.db.get_all_users()
            now = datetime.now()
            last_24h = now - timedelta(hours=24)
            last_7d = now - timedelta(days=7)
            
            # Активные пользователи
            active_24h = set()
            active_7d = set()
            
            # Статистика запросов
            requests_24h = 0
            requests_7d = 0
            requests_by_hour = defaultdict(int)
            popular_queries = Counter()
            popular_modes = Counter()
            
            # Анализируем запросы из мониторинга
            for req in self.monitoring.user_requests:
                req_time = datetime.fromisoformat(req.get('timestamp', now.isoformat()))
                user_id = req.get('user_id')
                
                if req_time >= last_24h:
                    requests_24h += 1
                    active_24h.add(user_id)
                    hour = req_time.hour
                    requests_by_hour[hour] += 1
                
                if req_time >= last_7d:
                    requests_7d += 1
                    active_7d.add(user_id)
                
                # Популярные запросы и режимы
                query = req.get('query')
                entity_type = req.get('entity_type')
                if query:
                    popular_queries[query] += 1
                if entity_type:
                    popular_modes[entity_type] += 1
            
            # Находим пиковый час
            peak_hour = max(requests_by_hour.items(), key=lambda x: x[1])[0] if requests_by_hour else 0
            
            # Топ-10 популярных запросов
            top_queries = popular_queries.most_common(10)
            
            return UsageStats(
                total_users=len(all_users),
                active_users_24h=len(active_24h),
                active_users_7d=len(active_7d),
                total_requests_24h=requests_24h,
                total_requests_7d=requests_7d,
                popular_queries=top_queries,
                popular_modes=dict(popular_modes),
                requests_by_hour=dict(requests_by_hour),
                peak_hour=peak_hour
            )
        except Exception as e:
            logger.error(f"Ошибка получения статистики использования: {e}", exc_info=True)
            # Возвращаем пустую статистику при ошибке
            return UsageStats(
                total_users=0,
                active_users_24h=0,
                active_users_7d=0,
                total_requests_24h=0,
                total_requests_7d=0,
                popular_queries=[],
                popular_modes={},
                requests_by_hour={},
                peak_hour=0
            )
    
    def get_growth_stats(self, days: int = 30) -> Dict:
        """Получить статистику роста пользовательской базы"""
        try:
            all_users = self.db.get_all_users()
            now = datetime.now()
            
            # Группируем пользователей по дате регистрации
            users_by_date = defaultdict(int)
            for user in all_users:
                created_at = user.get('created_at')
                if created_at:
                    try:
                        if isinstance(created_at, str):
                            user_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                        else:
                            user_date = created_at
                        date_key = user_date.date().isoformat()
                        users_by_date[date_key] += 1
                    except Exception:
                        continue
            
            # Сортируем по дате
            sorted_dates = sorted(users_by_date.items())
            
            # Вычисляем накопленную сумму
            cumulative = 0
            growth_data = []
            for date_str, count in sorted_dates:
                cumulative += count
                growth_data.append({
                    'date': date_str,
                    'new_users': count,
                    'total_users': cumulative
                })
            
            return {
                'growth_data': growth_data[-days:],  # Последние N дней
                'total_users': len(all_users),
                'new_users_last_7d': sum(count for _, count in sorted_dates[-7:]),
                'new_users_last_30d': sum(count for _, count in sorted_dates[-30:])
            }
        except Exception as e:
            logger.error(f"Ошибка получения статистики роста: {e}", exc_info=True)
            return {
                'growth_data': [],
                'total_users': 0,
                'new_users_last_7d': 0,
                'new_users_last_30d': 0
            }
    
    def format_usage_report(self) -> str:
        """Форматировать отчет об использовании для администратора"""
        stats = self.get_usage_stats()
        growth = self.get_growth_stats()
        
        report = (
            f"📊 <b>Отчет об использовании бота</b>\n\n"
            f"👥 <b>Пользователи:</b>\n"
            f"   • Всего: {stats.total_users}\n"
            f"   • Активных за 24ч: {stats.active_users_24h}\n"
            f"   • Активных за 7 дней: {stats.active_users_7d}\n"
            f"   • Новых за 7 дней: {growth['new_users_last_7d']}\n"
            f"   • Новых за 30 дней: {growth['new_users_last_30d']}\n\n"
            f"📈 <b>Активность:</b>\n"
            f"   • Запросов за 24ч: {stats.total_requests_24h}\n"
            f"   • Запросов за 7 дней: {stats.total_requests_7d}\n"
            f"   • Пиковый час: {stats.peak_hour}:00\n\n"
        )
        
        if stats.popular_queries:
            report += f"🔥 <b>Популярные запросы:</b>\n"
            for query, count in stats.popular_queries[:5]:
                report += f"   • {query}: {count}\n"
            report += "\n"
        
        if stats.popular_modes:
            report += f"📚 <b>Режимы использования:</b>\n"
            for mode, count in stats.popular_modes.items():
                report += f"   • {mode}: {count}\n"
        
        return report

# Глобальный экземпляр будет создан при инициализации
analytics = None

def init_analytics(database, monitoring):
    """Инициализировать глобальный экземпляр аналитики"""
    global analytics
    analytics = AnalyticsCollector(database, monitoring)
    return analytics

