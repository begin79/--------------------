"""
Расширение базы данных для админ-панели
"""
import sqlite3
import logging
import os
from typing import Optional, List, Dict, Any
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

# Используем ту же БД, что и основной бот
try:
    from ..database import DB_PATH as USERS_DB_PATH
except Exception:
    _db_path_env = os.getenv("USERS_DB_PATH")
    _db_dir_env = os.getenv("USERS_DB_DIR")
    if _db_path_env:
        USERS_DB_PATH = Path(_db_path_env).expanduser()
    elif _db_dir_env:
        USERS_DB_PATH = Path(_db_dir_env).expanduser() / "users.db"
    else:
        USERS_DB_PATH = Path("/data/users.db")

DB_PATH = USERS_DB_PATH

class AdminDatabase:
    """Класс для работы с админ-данными в базе данных"""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"Не удалось создать директорию для админ-БД {self.db_path.parent}: {e}")
        self.root_admin_id = self._resolve_root_admin_id()
        self._init_admin_tables()

    @staticmethod
    def _resolve_root_admin_id() -> Optional[int]:
        admin_id_env = os.getenv("ADMIN_ID")
        try:
            return int(admin_id_env) if admin_id_env else None
        except ValueError:
            logger.warning(f"Неверный формат ADMIN_ID: {admin_id_env}")
            return None

    def _init_admin_tables(self):
        """Инициализация таблиц для админ-панели"""
        try:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = conn.cursor()

            # Таблица админов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS admins (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    added_by INTEGER,
                    FOREIGN KEY (added_by) REFERENCES admins(user_id)
                )
            ''')

            # Таблица статуса бота
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bot_status (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    is_enabled BOOLEAN DEFAULT 1,
                    maintenance_message TEXT DEFAULT 'Бот временно недоступен. Ведутся технические работы.',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_by INTEGER,
                    FOREIGN KEY (updated_by) REFERENCES admins(user_id)
                )
            ''')

            # Вставляем дефолтный статус, если его нет
            cursor.execute('''
                INSERT OR IGNORE INTO bot_status (id, is_enabled, maintenance_message)
                VALUES (1, 1, 'Бот временно недоступен. Ведутся технические работы.')
            ''')

            # Таблица статистики (кеш для быстрого доступа)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS admin_stats (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    total_users INTEGER DEFAULT 0,
                    active_users_24h INTEGER DEFAULT 0,
                    total_requests INTEGER DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cursor.execute('''
                INSERT OR IGNORE INTO admin_stats (id, total_users, active_users_24h, total_requests)
                VALUES (1, 0, 0, 0)
            ''')

            conn.commit()
            conn.close()
            logger.info("Админские таблицы инициализированы")
        except Exception as e:
            logger.error(f"Ошибка инициализации админских таблиц: {e}", exc_info=True)

    def add_admin(self, user_id: int, username: Optional[str] = None, added_by: Optional[int] = None) -> bool:
        """Добавить администратора"""
        try:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = conn.cursor()

            cursor.execute('''
                INSERT OR REPLACE INTO admins (user_id, username, added_at, added_by)
                VALUES (?, ?, ?, ?)
            ''', (user_id, username, datetime.now().isoformat(), added_by))

            conn.commit()
            conn.close()
            logger.info(f"Администратор {user_id} добавлен")
            return True
        except Exception as e:
            logger.error(f"Ошибка добавления администратора {user_id}: {e}", exc_info=True)
            return False

    def remove_admin(self, user_id: int) -> bool:
        """Удалить администратора"""
        if self.root_admin_id and user_id == self.root_admin_id:
            logger.warning("Попытка удалить главного администратора отклонена")
            return False
        try:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = conn.cursor()

            cursor.execute('DELETE FROM admins WHERE user_id = ?', (user_id,))

            conn.commit()
            conn.close()
            logger.info(f"Администратор {user_id} удален")
            return True
        except Exception as e:
            logger.error(f"Ошибка удаления администратора {user_id}: {e}", exc_info=True)
            return False

    def is_admin(self, user_id: int) -> bool:
        """Проверить, является ли пользователь администратором"""
        try:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = conn.cursor()

            cursor.execute('SELECT user_id FROM admins WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()

            conn.close()
            return result is not None
        except Exception as e:
            logger.error(f"Ошибка проверки администратора {user_id}: {e}", exc_info=True)
            return False

    def get_all_admins(self) -> List[Dict[str, Any]]:
        """Получить список всех администраторов"""
        try:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('SELECT * FROM admins ORDER BY added_at DESC')
            rows = cursor.fetchall()

            conn.close()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Ошибка получения списка администраторов: {e}", exc_info=True)
            return []

    def get_bot_status(self) -> Dict[str, Any]:
        """Получить статус бота"""
        try:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('SELECT * FROM bot_status WHERE id = 1')
            row = cursor.fetchone()

            conn.close()
            if row:
                return dict(row)
            return {'is_enabled': True, 'maintenance_message': 'Бот временно недоступен. Ведутся технические работы.'}
        except Exception as e:
            logger.error(f"Ошибка получения статуса бота: {e}", exc_info=True)
            return {'is_enabled': True, 'maintenance_message': 'Бот временно недоступен. Ведутся технические работы.'}

    def set_bot_status(self, is_enabled: bool, maintenance_message: Optional[str] = None, updated_by: Optional[int] = None) -> bool:
        """Установить статус бота"""
        try:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = conn.cursor()

            if maintenance_message is None:
                # Получаем текущее сообщение
                cursor.execute('SELECT maintenance_message FROM bot_status WHERE id = 1')
                row = cursor.fetchone()
                maintenance_message = row[0] if row else 'Бот временно недоступен. Ведутся технические работы.'

            cursor.execute('''
                UPDATE bot_status
                SET is_enabled = ?, maintenance_message = ?, updated_at = ?, updated_by = ?
                WHERE id = 1
            ''', (int(is_enabled), maintenance_message, datetime.now().isoformat(), updated_by))

            conn.commit()
            conn.close()
            logger.info(f"Статус бота изменен: {'включен' if is_enabled else 'выключен'}")
            return True
        except Exception as e:
            logger.error(f"Ошибка установки статуса бота: {e}", exc_info=True)
            return False

    def set_maintenance_message(self, message: str, updated_by: Optional[int] = None) -> bool:
        """Установить сообщение о техническом обслуживании"""
        try:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = conn.cursor()

            cursor.execute('''
                UPDATE bot_status
                SET maintenance_message = ?, updated_at = ?, updated_by = ?
                WHERE id = 1
            ''', (message, datetime.now().isoformat(), updated_by))

            conn.commit()
            conn.close()
            logger.info("Сообщение о техническом обслуживании обновлено")
            return True
        except Exception as e:
            logger.error(f"Ошибка установки сообщения о техническом обслуживании: {e}", exc_info=True)
            return False

    def get_statistics(self) -> Dict[str, Any]:
        """Получить статистику (быстрый доступ из кеша)"""
        try:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Получаем статистику из кеша
            cursor.execute('SELECT * FROM admin_stats WHERE id = 1')
            stats_row = cursor.fetchone()

            # Получаем реальную статистику из БД
            cursor.execute('SELECT COUNT(*) as total FROM users')
            total_users = cursor.fetchone()[0]

            cursor.execute('''
                SELECT COUNT(DISTINCT user_id) as active_24h
                FROM activity_log
                WHERE timestamp > datetime('now', '-24 hours')
            ''')
            active_24h = cursor.fetchone()[0]

            cursor.execute('SELECT COUNT(*) as total_requests FROM activity_log')
            total_requests = cursor.fetchone()[0]

            conn.close()

            return {
                'total_users': total_users,
                'active_users_24h': active_24h,
                'total_requests': total_requests,
                'last_updated': stats_row['last_updated'] if stats_row else None
            }
        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}", exc_info=True)
            return {
                'total_users': 0,
                'active_users_24h': 0,
                'total_requests': 0,
                'last_updated': None
            }

    def update_statistics_cache(self):
        """Обновить кеш статистики"""
        try:
            stats = self.get_statistics()
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            cursor = conn.cursor()

            cursor.execute('''
                UPDATE admin_stats
                SET total_users = ?, active_users_24h = ?, total_requests = ?, last_updated = ?
                WHERE id = 1
            ''', (stats['total_users'], stats['active_users_24h'], stats['total_requests'], datetime.now().isoformat()))

            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Ошибка обновления кеша статистики: {e}", exc_info=True)

# Глобальный экземпляр админской БД
admin_db = AdminDatabase()

