"""
Менеджер состояний пользователя
Обеспечивает безопасную работу с состояниями и их очистку
"""
import logging
from typing import Dict, Any, Optional, Set
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# Ключи состояний, которые нужно очищать при ошибках
TEMPORARY_STATE_KEYS = {
    "ctx_is_busy",
    "ctx_awaiting_manual_date",
    "ctx_awaiting_default_query",
    "pending_admin_reply",
    "pending_query_",
    "awaiting_broadcast",
    "broadcast_message",
    "awaiting_maintenance_msg",
    "awaiting_admin_id",
    "awaiting_remove_admin_id",
    "awaiting_user_search",
    "awaiting_direct_message",
}

def clear_temporary_states(user_data: Dict[str, Any], exclude: Optional[Set[str]] = None) -> None:
    """
    Очищает временные состояния пользователя

    Args:
        user_data: Словарь user_data из context
        exclude: Множество ключей, которые не нужно очищать
    """
    exclude = exclude or set()
    keys_to_remove = []

    for key in user_data.keys():
        # Проверяем точное совпадение
        if key in TEMPORARY_STATE_KEYS and key not in exclude:
            keys_to_remove.append(key)
        # Проверяем префиксы
        elif any(key.startswith(prefix) for prefix in TEMPORARY_STATE_KEYS if prefix.endswith("_")) and key not in exclude:
            keys_to_remove.append(key)

    for key in keys_to_remove:
        user_data.pop(key, None)

    if keys_to_remove:
        logger.debug(f"Очищено временных состояний: {len(keys_to_remove)}")

import time

BUSY_TIMEOUT = 45  # 45 секунд таймаут для блокировки

def clear_user_busy_state(user_data: Dict[str, Any]) -> None:
    """Очищает флаг занятости пользователя"""
    user_data.pop("ctx_is_busy", None)
    user_data.pop("ctx_busy_timestamp", None)

def set_user_busy(user_data: Dict[str, Any], busy: bool = True) -> None:
    """Устанавливает флаг занятости пользователя"""
    if busy:
        user_data["ctx_is_busy"] = True
        user_data["ctx_busy_timestamp"] = time.time()
    else:
        clear_user_busy_state(user_data)

def is_user_busy(user_data: Dict[str, Any]) -> bool:
    """Проверяет, занят ли пользователь"""
    is_busy = user_data.get("ctx_is_busy", False)
    
    # Проверка таймаута блокировки
    if is_busy:
        timestamp = user_data.get("ctx_busy_timestamp", 0)
        if time.time() - timestamp > BUSY_TIMEOUT:
            # Блокировка устарела
            logger.warning(f"Сброс зависшей блокировки пользователя (time={time.time() - timestamp:.1f}s)")
            clear_user_busy_state(user_data)
            return False
            
    return is_busy

def validate_callback_data(data: str, max_length: int = 64) -> bool:
    """
    Валидирует данные callback query

    Args:
        data: Данные callback
        max_length: Максимальная длина

    Returns:
        True если данные валидны
    """
    if not data or not isinstance(data, str):
        return False
    if len(data) > max_length:
        logger.warning(f"Callback data слишком длинный: {len(data)} символов")
        return False
    # Проверка на опасные символы
    if any(char in data for char in ['\x00', '\n', '\r']):
        logger.warning(f"Callback data содержит опасные символы")
        return False
    return True

def safe_get_user_data(user_data: Dict[str, Any], key: str, default: Any = None) -> Any:
    """
    Безопасное получение данных из user_data с логированием

    Args:
        user_data: Словарь user_data
        key: Ключ
        default: Значение по умолчанию

    Returns:
        Значение или default
    """
    try:
        return user_data.get(key, default)
    except Exception as e:
        logger.error(f"Ошибка при получении user_data[{key}]: {e}")
        return default

