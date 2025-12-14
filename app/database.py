"""
Модуль для работы с базой данных пользователей
Использует SQLite для хранения данных пользователей
"""
import os
import sqlite3
import logging
import threading
from contextlib import contextmanager
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
from datetime import datetime
from cachetools import TTLCache

logger = logging.getLogger(__name__)

try:
    from .config import DB_PATH
except ImportError:
    # Fallback на случай проблем с импортом, но в норме config должен работать
    DEFAULT_DB_PATH = "/data/users.db" if os.path.exists("/data") else "data/users.db"
    DB_PATH = Path(DEFAULT_DB_PATH)

# Ensure DB_PATH is a Path object
if isinstance(DB_PATH, str):
    DB_PATH = Path(DB_PATH)

class UserDatabase:
    """Класс для работы с базой данных пользователей"""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()  # Блокировка для thread-safety
        # ОПТИМИЗАЦИЯ: Кеш пользователей в памяти (5 минут TTL, до 1000 пользователей)
        self._user_cache: TTLCache = TTLCache(maxsize=1000, ttl=300)
        # ОПТИМИЗАЦИЯ: Батч-очередь для логов активности (записываем пачками)
        self._activity_queue: List[Tuple[int, str, Optional[str]]] = []
        self._activity_lock = threading.Lock()
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.warning(f"Не удалось создать директорию для БД {self.db_path.parent}: {exc}")
        logger.info(f"Используется файл базы данных: {self.db_path}")
        self._init_database()

    @contextmanager
    def _get_connection(self):
        """Context manager для безопасной работы с БД"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10.0)
            conn.row_factory = sqlite3.Row
            # Настройки производительности
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=NORMAL')
            conn.execute('PRAGMA cache_size=-64000')
            conn.execute('PRAGMA temp_store=MEMORY')
            conn.execute('PRAGMA busy_timeout=5000')  # Таймаут для ожидания блокировки
            yield conn
            conn.commit()
        except sqlite3.Error as e:
            if conn:
                conn.rollback()
            logger.error(f"Ошибка БД: {e}", exc_info=True)
            raise
        finally:
            if conn:
                conn.close()

    def _init_database(self):
        """Инициализация базы данных и создание таблиц"""
        try:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            # Включаем WAL режим для лучшей производительности при конкурентном доступе
            conn.execute('PRAGMA journal_mode=WAL')
            # Оптимизируем настройки для производительности
            conn.execute('PRAGMA synchronous=NORMAL')  # Быстрее чем FULL, но безопаснее чем OFF
            conn.execute('PRAGMA cache_size=-64000')  # 64MB кеш
            conn.execute('PRAGMA temp_store=MEMORY')
            cursor = conn.cursor()

            # Таблица пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    default_query TEXT,
                    default_mode TEXT,
                    daily_notifications BOOLEAN DEFAULT 0,
                    notification_time TEXT DEFAULT '21:00',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Таблица истории активности
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS activity_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    action TEXT,
                    details TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')

            # Таблица отзывов пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    username TEXT,
                    first_name TEXT,
                    message TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')

            # Таблица истории поиска пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS search_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    query TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')

            # Создаем индексы для быстрого поиска
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_activity_user_id ON activity_log(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_activity_timestamp ON activity_log(timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_last_active ON users(last_active)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_default_query ON users(default_query) WHERE default_query IS NOT NULL')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_username ON users(username) WHERE username IS NOT NULL')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_feedback_user_id ON feedback(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_feedback_created_at ON feedback(created_at)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_search_history_user_id ON search_history(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_search_history_created_at ON search_history(created_at)')

            conn.commit()
            conn.close()
            logger.info(f"База данных инициализирована: {self.db_path}")
        except Exception as e:
            logger.error(f"Ошибка инициализации базы данных: {e}", exc_info=True)

    def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Получить данные пользователя (с кешированием в памяти)"""
        # ОПТИМИЗАЦИЯ: Сначала проверяем кеш
        if user_id in self._user_cache:
            return self._user_cache[user_id]

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT user_id, username, first_name, last_name, default_query,
                           default_mode, daily_notifications, notification_time,
                           created_at, last_active
                    FROM users WHERE user_id = ?
                ''', (user_id,))
                row = cursor.fetchone()
                if row:
                    result = dict(row)
                    # ОПТИМИЗАЦИЯ: Сохраняем в кеш
                    self._user_cache[user_id] = result
                    return result
                return None
        except Exception as e:
            logger.error(f"Ошибка получения пользователя {user_id}: {e}", exc_info=True)
            return None

    def save_user(self, user_id: int, username: Optional[str] = None,
                  first_name: Optional[str] = None, last_name: Optional[str] = None,
                  default_query: Optional[str] = None, default_mode: Optional[str] = None,
                  daily_notifications: Optional[bool] = None,
                  notification_time: Optional[str] = None):
        """Сохранить или обновить данные пользователя"""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    # Проверяем, существует ли пользователь
                    cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
                    exists = cursor.fetchone()

                    if exists:
                        # Обновляем существующего пользователя
                        updates = []
                        params = []

                        if username is not None:
                            updates.append("username = ?")
                            params.append(username)
                        if first_name is not None:
                            updates.append("first_name = ?")
                            params.append(first_name)
                        if last_name is not None:
                            updates.append("last_name = ?")
                            params.append(last_name)
                        if default_query is not None:
                            updates.append("default_query = ?")
                            params.append(default_query)
                        if default_mode is not None:
                            updates.append("default_mode = ?")
                            params.append(default_mode)
                        if daily_notifications is not None:
                            updates.append("daily_notifications = ?")
                            params.append(int(daily_notifications))
                        if notification_time is not None:
                            updates.append("notification_time = ?")
                            params.append(notification_time)

                        updates.append("last_active = ?")
                        params.append(datetime.now().isoformat())
                        params.append(user_id)

                        if updates:
                            query = f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?"
                            cursor.execute(query, params)
                    else:
                        # Создаем нового пользователя
                        cursor.execute('''
                            INSERT INTO users (user_id, username, first_name, last_name,
                                             default_query, default_mode, daily_notifications,
                                             notification_time, created_at, last_active)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (user_id, username, first_name, last_name, default_query, default_mode,
                              int(daily_notifications) if daily_notifications else 0,
                              notification_time or '21:00',
                              datetime.now().isoformat(), datetime.now().isoformat()))
                    logger.debug(f"Данные пользователя {user_id} сохранены")
                    # ОПТИМИЗАЦИЯ: Инвалидируем кеш после сохранения
                    self._user_cache.pop(user_id, None)
            except Exception as e:
                logger.error(f"Ошибка сохранения пользователя {user_id}: {e}", exc_info=True)

    def log_activity(self, user_id: int, action: str, details: Optional[str] = None):
        """
        Записать действие пользователя в лог (батч-режим для производительности).
        ОПТИМИЗАЦИЯ: Добавляем в очередь вместо немедленной записи.
        """
        with self._activity_lock:
            self._activity_queue.append((user_id, action, details))
            # Если накопилось 10+ записей, сбрасываем на диск
            if len(self._activity_queue) >= 10:
                self._flush_activity_log_internal()

    def _flush_activity_log_internal(self):
        """Внутренний метод: запись батча логов в БД (вызывается под _activity_lock)"""
        if not self._activity_queue:
            return
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.executemany('''
                    INSERT INTO activity_log (user_id, action, details)
                    VALUES (?, ?, ?)
                ''', self._activity_queue)
            self._activity_queue.clear()
        except Exception as e:
            # Не критично, просто логируем
            logger.debug(f"Ошибка пакетной записи активности: {e}")

    def flush_activity_log(self):
        """Принудительно записать все накопленные логи в БД"""
        with self._activity_lock:
            self._flush_activity_log_internal()

    def get_all_users(self) -> list:
        """Получить список всех пользователей"""
        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM users ORDER BY last_active DESC')
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Ошибка получения списка пользователей: {e}", exc_info=True)
            return []

    def get_all_known_user_ids(self, include_activity_log: bool = True) -> list:
        """
        Получить множество всех известных user_id.
        Включает пользователей из основной таблицы users и (опционально) user_id из журнала активности.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                user_ids = set()

                cursor.execute('SELECT user_id FROM users')
                user_ids.update(row[0] for row in cursor.fetchall() if row and row[0])

                if include_activity_log:
                    cursor.execute('SELECT DISTINCT user_id FROM activity_log WHERE user_id IS NOT NULL')
                    user_ids.update(row[0] for row in cursor.fetchall() if row and row[0])

                # Возвращаем отсортированный список для предсказуемого порядка обхода
                return sorted(user_ids)
        except Exception as e:
            logger.error(f"Ошибка получения списка user_id: {e}", exc_info=True)
            return []

    def get_user_activity(self, user_id: int, limit: int = 10) -> list:
        """Получить историю активности пользователя"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT action, details, timestamp
                    FROM activity_log
                    WHERE user_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                ''', (user_id, limit))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Ошибка получения активности пользователя {user_id}: {e}", exc_info=True)
            return []

    def get_users_with_default_query(self) -> list:
        """Получить список пользователей с установленными группами/преподавателями"""
        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT user_id, default_query, default_mode, daily_notifications, notification_time
                    FROM users
                    WHERE default_query IS NOT NULL AND default_query != ''
                      AND default_mode IS NOT NULL AND default_mode != ''
                ''')
                rows = cursor.fetchall()
                result = [dict(row) for row in rows]
                logger.debug(f"Найдено {len(result)} пользователей с установленной группой/преподавателем")
                return result
        except Exception as e:
            logger.error(f"Ошибка получения пользователей с установленными группами: {e}", exc_info=True)
            return []

    def delete_user(self, user_id: int):
        """Удалить пользователя из базы данных"""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
                    cursor.execute('DELETE FROM activity_log WHERE user_id = ?', (user_id,))
                    logger.info(f"Пользователь {user_id} удален из базы данных")
            except Exception as e:
                logger.error(f"Ошибка удаления пользователя {user_id}: {e}", exc_info=True)

    def get_last_feedback_time(self, user_id: int) -> Optional[str]:
        """Получить время последнего отзыва пользователя"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT created_at FROM feedback
                    WHERE user_id = ?
                    ORDER BY created_at DESC LIMIT 1
                ''', (user_id,))
                row = cursor.fetchone()
                if row:
                    return row['created_at']
                return None
        except Exception as e:
            logger.error(f"Ошибка получения времени последнего отзыва: {e}", exc_info=True)
            return None

    def can_leave_feedback(self, user_id: int) -> Tuple[bool, Optional[int]]:
        """
        Проверить, может ли пользователь оставить отзыв (1 раз в 24 часа).
        Возвращает (True, None) если можно, (False, seconds_left) если нужно подождать.
        """
        from datetime import datetime, timedelta
        try:
            last_feedback = self.get_last_feedback_time(user_id)
            if not last_feedback:
                return (True, None)

            # Парсим время последнего отзыва
            if isinstance(last_feedback, str):
                last_time = datetime.fromisoformat(last_feedback.replace('Z', '+00:00'))
            else:
                last_time = last_feedback

            # Убираем timezone для сравнения
            if last_time.tzinfo:
                last_time = last_time.replace(tzinfo=None)

            next_allowed = last_time + timedelta(hours=24)
            now = datetime.utcnow()

            if now >= next_allowed:
                return (True, None)

            seconds_left = int((next_allowed - now).total_seconds())
            return (False, seconds_left)
        except Exception as e:
            logger.error(f"Ошибка проверки возможности оставить отзыв: {e}", exc_info=True)
            return (True, None)  # В случае ошибки разрешаем

    def save_feedback(self, user_id: int, message: str,
                      username: Optional[str] = None, first_name: Optional[str] = None) -> bool:
        """Сохранить отзыв пользователя"""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO feedback (user_id, username, first_name, message)
                        VALUES (?, ?, ?, ?)
                    ''', (user_id, username, first_name, message))
                    logger.info(f"Сохранен отзыв от пользователя {user_id}")
                    return True
            except Exception as e:
                logger.error(f"Ошибка сохранения отзыва: {e}", exc_info=True)
                return False

    def get_all_feedback(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Получить все отзывы (для администратора)"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, user_id, username, first_name, message, created_at
                    FROM feedback
                    ORDER BY created_at DESC
                    LIMIT ?
                ''', (limit,))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Ошибка получения отзывов: {e}", exc_info=True)
            return []

    def get_last_feedback(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Получить последний отзыв пользователя"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, user_id, username, first_name, message, created_at
                    FROM feedback
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                ''', (user_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Ошибка получения последнего отзыва: {e}", exc_info=True)
            return None

    def get_last_activity(self, user_id: int, action_pattern: str = None) -> Optional[Dict[str, Any]]:
        """Получить последнюю активность пользователя (поиск, запрос расписания и т.д.)"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if action_pattern:
                    cursor.execute('''
                        SELECT user_id, action, details, timestamp
                        FROM activity_log
                        WHERE user_id = ? AND action LIKE ?
                        ORDER BY timestamp DESC
                        LIMIT 1
                    ''', (user_id, f"%{action_pattern}%"))
                else:
                    cursor.execute('''
                        SELECT user_id, action, details, timestamp
                        FROM activity_log
                        WHERE user_id = ?
                        ORDER BY timestamp DESC
                        LIMIT 1
                    ''', (user_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Ошибка получения последней активности: {e}", exc_info=True)
            return None

    def save_search_history(self, user_id: int, query: str, mode: str):
        """Сохранить запрос в историю поиска"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Удаляем старые записи (оставляем последние 20 для каждого пользователя)
                cursor.execute('''
                    DELETE FROM search_history
                    WHERE user_id = ? AND id NOT IN (
                        SELECT id FROM search_history
                        WHERE user_id = ?
                        ORDER BY created_at DESC
                        LIMIT 20
                    )
                ''', (user_id, user_id))
                # Добавляем новую запись
                cursor.execute('''
                    INSERT INTO search_history (user_id, query, mode, created_at)
                    VALUES (?, ?, ?, ?)
                ''', (user_id, query, mode, datetime.now().isoformat()))
        except Exception as e:
            logger.error(f"Ошибка сохранения истории поиска: {e}", exc_info=True)

    def get_search_history(self, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Получить историю поиска пользователя"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT query, mode, created_at
                    FROM search_history
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                ''', (user_id, limit))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Ошибка получения истории поиска: {e}", exc_info=True)
            return []

# Глобальный экземпляр базы данных
db = UserDatabase()

