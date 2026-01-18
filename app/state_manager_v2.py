"""
Улучшенный менеджер состояний пользователя
Централизованное управление состояниями с приоритетами и автоматической очисткой
"""
import logging
from typing import Dict, Any, Optional, Set, List
from enum import Enum
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


class StatePriority(Enum):
    """Приоритеты состояний (чем выше значение, тем выше приоритет)"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


class UserState(Enum):
    """Типы состояний пользователя"""
    # Временные состояния ожидания ввода
    AWAITING_DEFAULT_QUERY = ("ctx_awaiting_default_query", StatePriority.HIGH)
    AWAITING_FEEDBACK = ("ctx_awaiting_feedback", StatePriority.NORMAL)
    AWAITING_MANUAL_DATE = ("ctx_awaiting_manual_date", StatePriority.NORMAL)
    AWAITING_ADMIN_REPLY = ("pending_admin_reply", StatePriority.CRITICAL)
    
    # Состояния блокировки
    IS_BUSY = ("ctx_is_busy", StatePriority.CRITICAL)
    
    # Временные данные (для очистки)
    FOUND_ENTITIES = ("ctx_found_entities", StatePriority.LOW)
    KEYBOARD_MESSAGE_ID = ("ctx_keyboard_message_id", StatePriority.LOW)
    
    def __init__(self, key: str, priority: StatePriority):
        self.key = key
        self.priority = priority


class StateManager:
    """
    Централизованный менеджер состояний пользователя.
    Обеспечивает:
    - Автоматическую очистку конфликтующих состояний
    - Приоритетную обработку состояний
    - Безопасное управление жизненным циклом состояний
    """
    
    # Группы конфликтующих состояний (одновременно могут быть активны только одно из группы)
    CONFLICT_GROUPS: List[Set[UserState]] = [
        {
            UserState.AWAITING_DEFAULT_QUERY,
            UserState.AWAITING_FEEDBACK,
            UserState.AWAITING_MANUAL_DATE,
        }
    ]
    
    def __init__(self, user_data: Dict[str, Any]):
        self.user_data = user_data
    
    def set_state(self, state: UserState, value: Any = True) -> None:
        """
        Устанавливает состояние, автоматически очищая конфликтующие.
        
        Args:
            state: Состояние для установки
            value: Значение состояния (по умолчанию True)
        """
        # Находим конфликтующую группу
        conflict_group = None
        for group in self.CONFLICT_GROUPS:
            if state in group:
                conflict_group = group
                break
        
        # Очищаем конфликтующие состояния
        if conflict_group:
            for conflicting_state in conflict_group:
                if conflicting_state != state:
                    self.clear_state(conflicting_state)
        
        # Устанавливаем новое состояние
        self.user_data[state.key] = value
        logger.debug(f"Установлено состояние: {state.key} = {value}")
    
    def clear_state(self, state: UserState) -> None:
        """Очищает состояние"""
        if state.key in self.user_data:
            del self.user_data[state.key]
            logger.debug(f"Очищено состояние: {state.key}")
    
    def has_state(self, state: UserState) -> bool:
        """Проверяет, активно ли состояние"""
        return self.user_data.get(state.key, False) is not False
    
    def get_state(self, state: UserState, default: Any = None) -> Any:
        """Получает значение состояния"""
        return self.user_data.get(state.key, default)
    
    def clear_all_temporary(self, exclude: Optional[Set[UserState]] = None) -> None:
        """
        Очищает все временные состояния, кроме указанных.
        
        Args:
            exclude: Множество состояний, которые не нужно очищать
        """
        exclude = exclude or set()
        cleared_count = 0
        
        # Очищаем все временные состояния из групп конфликтов
        for group in self.CONFLICT_GROUPS:
            for state in group:
                if state not in exclude and self.has_state(state):
                    self.clear_state(state)
                    cleared_count += 1
        
        # Очищаем другие временные состояния
        temp_states = [
            UserState.FOUND_ENTITIES,
            UserState.KEYBOARD_MESSAGE_ID,
        ]
        
        for state in temp_states:
            if state not in exclude and self.has_state(state):
                self.clear_state(state)
                cleared_count += 1
        
        # Очищаем блокировку, если она не исключена
        if UserState.IS_BUSY not in exclude and self.has_state(UserState.IS_BUSY):
            self.clear_state(UserState.IS_BUSY)
            cleared_count += 1
        
        if cleared_count > 0:
            logger.debug(f"Очищено {cleared_count} временных состояний")
    
    def get_active_states(self) -> List[UserState]:
        """Возвращает список активных состояний"""
        active = []
        for state in UserState:
            if self.has_state(state):
                active.append(state)
        return active
    
    def clear_on_error(self, exclude: Optional[Set[UserState]] = None) -> None:
        """
        Очищает состояния при ошибке, сохраняя критичные состояния.
        
        Args:
            exclude: Множество состояний, которые не нужно очищать
        """
        exclude = exclude or set()
        
        # Сохраняем критичные состояния
        exclude.add(UserState.IS_BUSY)
        exclude.add(UserState.AWAITING_ADMIN_REPLY)
        
        self.clear_all_temporary(exclude)


# Функции-утилиты для обратной совместимости
def get_state_manager(user_data: Dict[str, Any]) -> StateManager:
    """Получает менеджер состояний для user_data"""
    return StateManager(user_data)


def set_awaiting_default_query(user_data: Dict[str, Any]) -> None:
    """Устанавливает состояние ожидания ввода группы/преподавателя"""
    manager = StateManager(user_data)
    manager.set_state(UserState.AWAITING_DEFAULT_QUERY)


def set_awaiting_feedback(user_data: Dict[str, Any]) -> None:
    """Устанавливает состояние ожидания отзыва"""
    manager = StateManager(user_data)
    manager.set_state(UserState.AWAITING_FEEDBACK)


def set_awaiting_manual_date(user_data: Dict[str, Any]) -> None:
    """Устанавливает состояние ожидания ввода даты"""
    manager = StateManager(user_data)
    manager.set_state(UserState.AWAITING_MANUAL_DATE)


def clear_all_temporary_states(user_data: Dict[str, Any], exclude: Optional[Set[str]] = None) -> None:
    """
    Очищает все временные состояния (обратная совместимость).
    
    Args:
        user_data: Словарь user_data
        exclude: Множество ключей, которые не нужно очищать
    """
    manager = StateManager(user_data)
    
    # Преобразуем строковые ключи в UserState, если нужно
    exclude_states = set()
    if exclude:
        key_to_state = {state.key: state for state in UserState}
        for key in exclude:
            if key in key_to_state:
                exclude_states.add(key_to_state[key])
    
    manager.clear_all_temporary(exclude_states)

