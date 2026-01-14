import logging
import asyncio
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

class ParserMonitor:
    def __init__(self):
        self.error_count = 0
        self.last_alert_time: Optional[datetime] = None
        self.error_threshold = 3  # После скольких ошибок подряд бить тревогу
        self.alert_cooldown = 3600  # Не спамить админа чаще раза в час (в секундах)
        self.is_broken = False  # Флаг глобальной поломки
        
        # Метрики производительности
        self.request_times: deque = deque(maxlen=100)  # Последние 100 запросов
        self.success_count = 0
        self.total_requests = 0
        self.start_time = datetime.now()
        
        # Статистика по типам запросов
        self.requests_by_type: Dict[str, int] = defaultdict(int)
        self.errors_by_type: Dict[str, int] = defaultdict(int)
        
        # Логирование пользовательских запросов
        self.user_requests: deque = deque(maxlen=1000)  # Последние 1000 запросов пользователей

    async def report_success(self, request_type: str = "unknown", duration: Optional[float] = None):
        """
        Сброс счетчика ошибок при успешном парсинге
        
        Args:
            request_type: Тип запроса (Group, Teacher)
            duration: Время выполнения запроса в секундах
        """
        self.success_count += 1
        self.total_requests += 1
        self.requests_by_type[request_type] += 1
        
        if duration is not None:
            self.request_times.append(duration)
            logger.debug(f"✅ Запрос {request_type} выполнен за {duration:.2f}с")
        
        if self.error_count > 0:
            self.error_count = 0
            if self.is_broken:
                self.is_broken = False
                logger.info("✅ Парсер восстановился!")

    async def report_failure(self, bot, admin_id: int, error_text: str, context_info: str, request_type: str = "unknown"):
        """
        Регистрация ошибки парсинга
        
        Args:
            bot: Объект бота для отправки алертов
            admin_id: ID администратора
            error_text: Текст ошибки
            context_info: Контекстная информация об ошибке
            request_type: Тип запроса (Group, Teacher)
        """
        self.error_count += 1
        self.total_requests += 1
        self.errors_by_type[request_type] += 1
        self.requests_by_type[request_type] += 1
        
        logger.warning(f"⚠️ Ошибка парсинга #{self.error_count} ({request_type}): {error_text} | Контекст: {context_info}")

        # Если ошибок слишком много, считаем, что сайт лег или сменил верстку
        if self.error_count >= self.error_threshold:
            self.is_broken = True
            await self._alert_admin(bot, admin_id, error_text, context_info)

    def log_user_request(self, user_id: int, query: str, entity_type: str, date: str, success: bool = True):
        """
        Логирует запрос пользователя для статистики
        
        Args:
            user_id: ID пользователя
            query: Запрос (группа/преподаватель)
            entity_type: Тип сущности (Group/Teacher)
            date: Дата запроса
            success: Успешность запроса
        """
        request_info = {
            "timestamp": datetime.now().isoformat(),
            "user_id": user_id,
            "query": query,
            "entity_type": entity_type,
            "date": date,
            "success": success
        }
        self.user_requests.append(request_info)
        logger.info(f"📊 Запрос пользователя {user_id}: {entity_type} '{query}' на {date} - {'✅' if success else '❌'}")

    def get_statistics(self) -> Dict:
        """
        Возвращает статистику работы парсера
        
        Returns:
            Словарь со статистикой
        """
        uptime = (datetime.now() - self.start_time).total_seconds()
        avg_request_time = sum(self.request_times) / len(self.request_times) if self.request_times else 0
        
        return {
            "uptime_seconds": uptime,
            "total_requests": self.total_requests,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "success_rate": (self.success_count / self.total_requests * 100) if self.total_requests > 0 else 0,
            "avg_request_time": avg_request_time,
            "requests_by_type": dict(self.requests_by_type),
            "errors_by_type": dict(self.errors_by_type),
            "is_broken": self.is_broken,
            "recent_user_requests": len(self.user_requests)
        }

    async def _alert_admin(self, bot, admin_id: int, error_text: str, context_info: str):
        """Отправка уведомления админу"""
        now = datetime.now()

        # Проверяем кулдаун (чтобы не заспамить личку)
        if self.last_alert_time and (now - self.last_alert_time).total_seconds() < self.alert_cooldown:
            return

        # Добавляем статистику в алерт
        stats = self.get_statistics()
        stats_text = (
            f"\n\n📊 <b>Статистика:</b>\n"
            f"Всего запросов: {stats['total_requests']}\n"
            f"Успешных: {stats['success_count']} ({stats['success_rate']:.1f}%)\n"
            f"Ошибок: {stats['error_count']}\n"
            f"Время работы: {stats['uptime_seconds']/3600:.1f}ч"
        )

        alert_msg = (
            f"🚨 <b>КРИТИЧЕСКАЯ ОШИБКА ПАРСЕРА</b> 🚨\n\n"
            f"Бот не может прочитать расписание {self.error_count} раз подряд.\n"
            f"Возможно, <b>на сайте ВГЛТУ изменилась верстка</b>.\n\n"
            f"🔍 <b>Детали:</b>\n"
            f"Запрос: {context_info}\n"
            f"Ошибка: {error_text}"
            f"{stats_text}\n\n"
            f"🛠 <i>Требуется вмешательство разработчика!</i>"
        )

        try:
            from telegram.constants import ParseMode
            await bot.send_message(chat_id=admin_id, text=alert_msg, parse_mode=ParseMode.HTML)
            self.last_alert_time = now
            logger.error(f"🚨 АЛЕРТ ОТПРАВЛЕН АДМИНУ {admin_id}")
        except Exception as e:
            logger.error(f"Не удалось отправить алерт админу: {e}")

# Глобальный инстанс монитора
monitor = ParserMonitor()