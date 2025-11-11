"""
Утилиты для админ-панели
"""
from .database import admin_db

def is_admin(user_id: int) -> bool:
    """Проверить, является ли пользователь администратором"""
    return admin_db.is_admin(user_id)

def is_bot_enabled() -> bool:
    """Проверить, включен ли бот"""
    status = admin_db.get_bot_status()
    return bool(status.get('is_enabled', True))

def get_maintenance_message() -> str:
    """Получить сообщение о техническом обслуживании"""
    status = admin_db.get_bot_status()
    return status.get('maintenance_message', 'Бот временно недоступен. Ведутся технические работы.')

def set_bot_status(is_enabled: bool, updated_by: int = None) -> bool:
    """Установить статус бота"""
    return admin_db.set_bot_status(is_enabled, updated_by=updated_by)

def set_maintenance_message(message: str, updated_by: int = None) -> bool:
    """Установить сообщение о техническом обслуживании"""
    return admin_db.set_maintenance_message(message, updated_by=updated_by)

