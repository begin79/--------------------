"""
Модуль для работы с базой данных пользователей
Использует SQLite для хранения данных пользователей
"""
import os
import sqlite3
import logging
from typing import Optional, Dict, Any
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "/data/users.db"
DB_PATH: Path

_db_path_env = os.getenv("USERS_DB_PATH")
_db_dir_env = os.getenv("USERS_DB_DIR")

if _db_path_env:
    DB_PATH = Path(_db_path_env).expanduser()
elif _db_dir_env:
    DB_PATH = Path(_db_dir_env).expanduser() / "users.db"
else:
    DB_PATH = Path(DEFAULT_DB_PATH)

class UserDatabase:
    """Класс для работы с базой данных пользователей"""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.warning(f"Не удалось создать директорию для БД {self.db_path.parent}: {exc}")
        logger.info(f"Используется файл базы данных: {self.db_path}")
        self._init_database()

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

            # Создаем индексы для быстрого поиска
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_activity_user_id ON activity_log(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_activity_timestamp ON activity_log(timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_last_active ON users(last_active)')

            conn.commit()
            conn.close()
            logger.info(f"База данных инициализирована: {self.db_path}")
        except Exception as e:
            logger.error(f"Ошибка инициализации базы данных: {e}", exc_info=True)

    def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Получить данные пользователя"""
        try:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            # Оптимизация: используем только нужные поля вместо SELECT *
            cursor = conn.cursor()

            cursor.execute('''
                SELECT user_id, username, first_name, last_name, default_query,
                       default_mode, daily_notifications, notification_time,
                       created_at, last_active
                FROM users WHERE user_id = ?
            ''', (user_id,))

            row = cursor.fetchone()
            conn.close()

            if row:
                return dict(row)
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
        try:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
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

            conn.commit()
            conn.close()
            logger.debug(f"Данные пользователя {user_id} сохранены")
        except Exception as e:
            logger.error(f"Ошибка сохранения пользователя {user_id}: {e}", exc_info=True)

    def log_activity(self, user_id: int, action: str, details: Optional[str] = None):
        """Записать действие пользователя в лог"""
        try:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = conn.cursor()

            cursor.execute('''
                INSERT INTO activity_log (user_id, action, details)
                VALUES (?, ?, ?)
            ''', (user_id, action, details))

            conn.commit()
            conn.close()
        except Exception as e:
            # Не логируем ошибки записи активности как критичные - это не должно ломать работу бота
            logger.debug(f"Ошибка записи активности пользователя {user_id}: {e}")

    def get_all_users(self) -> list:
        """Получить список всех пользователей"""
        try:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('SELECT * FROM users ORDER BY last_active DESC')
            rows = cursor.fetchall()
            conn.close()

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
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = conn.cursor()

            user_ids = set()

            cursor.execute('SELECT user_id FROM users')
            user_ids.update(row[0] for row in cursor.fetchall() if row and row[0])

            if include_activity_log:
                cursor.execute('SELECT DISTINCT user_id FROM activity_log WHERE user_id IS NOT NULL')
                user_ids.update(row[0] for row in cursor.fetchall() if row and row[0])

            conn.close()

            # Возвращаем отсортированный список для предсказуемого порядка обхода
            return sorted(user_ids)
        except Exception as e:
            logger.error(f"Ошибка получения списка user_id: {e}", exc_info=True)
            return []

    def delete_user(self, user_id: int):
        """Удалить пользователя из базы данных"""
        try:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = conn.cursor()

            cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
            cursor.execute('DELETE FROM activity_log WHERE user_id = ?', (user_id,))

            conn.commit()
            conn.close()
            logger.info(f"Пользователь {user_id} удален из базы данных")
        except Exception as e:
            logger.error(f"Ошибка удаления пользователя {user_id}: {e}", exc_info=True)

# Глобальный экземпляр базы данных
db = UserDatabase()

