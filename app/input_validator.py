"""
Валидация пользовательского ввода
Защита от невалидных и опасных данных
"""
import re
import logging
from typing import Tuple, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# Лимиты
MAX_QUERY_LENGTH = 100  # Максимальная длина названия группы/преподавателя
MAX_FEEDBACK_LENGTH = 5000  # Максимальная длина отзыва
MIN_QUERY_LENGTH = 1  # Минимальная длина запроса

# Паттерны для валидации
GROUP_NAME_PATTERN = re.compile(r'^[А-ЯA-Z0-9]+-\d{1,3}(?:-[А-ЯA-Z]+)?$', re.IGNORECASE)
TEACHER_NAME_PATTERN = re.compile(r'^[А-ЯA-ZЁ][а-яa-zё]+(?:\s+[А-ЯA-ZЁ][а-яa-zё]+){1,3}$')
DATE_PATTERNS = [
    r'^\d{1,2}\.\d{1,2}\.\d{4}$',  # DD.MM.YYYY
    r'^\d{4}-\d{2}-\d{2}$',  # YYYY-MM-DD
    r'^\d{1,2}\s+\d{1,2}\s+\d{4}$',  # DD MM YYYY
]


class ValidationError(Exception):
    """Исключение при валидации ввода"""
    pass


def validate_query(query: str, query_type: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """
    Валидирует запрос группы или преподавателя.
    
    Args:
        query: Запрос для валидации
        query_type: Тип запроса ('group' или 'teacher'), если известен
    
    Returns:
        (is_valid, error_message)
    """
    if not query or not isinstance(query, str):
        return False, "Запрос не может быть пустым"
    
    query = query.strip()
    
    # Проверка длины
    if len(query) < MIN_QUERY_LENGTH:
        return False, f"Запрос слишком короткий (минимум {MIN_QUERY_LENGTH} символ)"
    
    if len(query) > MAX_QUERY_LENGTH:
        return False, f"Запрос слишком длинный (максимум {MAX_QUERY_LENGTH} символов)"
    
    # Проверка на опасные символы (SQL injection, XSS и т.д.)
    dangerous_patterns = [
        r'[<>]',  # HTML теги
        r'[;\'"\\]',  # SQL injection символы
        r'[`$]',  # Command injection
    ]
    
    for pattern in dangerous_patterns:
        if re.search(pattern, query):
            logger.warning(f"Обнаружен опасный символ в запросе: {query[:50]}")
            return False, "Запрос содержит недопустимые символы"
    
    # Если известен тип, проверяем по паттерну
    if query_type == 'group':
        if not GROUP_NAME_PATTERN.match(query):
            # Мягкая валидация - только предупреждаем, но разрешаем
            logger.debug(f"Запрос группы не соответствует стандартному формату: {query}")
    elif query_type == 'teacher':
        if not TEACHER_NAME_PATTERN.match(query):
            # Мягкая валидация - только предупреждаем, но разрешаем
            logger.debug(f"Запрос преподавателя не соответствует стандартному формату: {query}")
    
    return True, None


def validate_feedback(feedback: str) -> Tuple[bool, Optional[str]]:
    """
    Валидирует отзыв пользователя.
    
    Args:
        feedback: Отзыв для валидации
    
    Returns:
        (is_valid, error_message)
    """
    if not feedback or not isinstance(feedback, str):
        return False, "Отзыв не может быть пустым"
    
    feedback = feedback.strip()
    
    # Проверка длины
    if len(feedback) < 1:
        return False, "Отзыв не может быть пустым"
    
    if len(feedback) > MAX_FEEDBACK_LENGTH:
        return False, f"Отзыв слишком длинный (максимум {MAX_FEEDBACK_LENGTH} символов)"
    
    # Проверка на спам (много повторяющихся символов)
    if len(set(feedback[:50])) < 3 and len(feedback) > 50:
        logger.warning(f"Подозрительный отзыв (много повторений): {feedback[:100]}")
        # Не блокируем, но логируем
    
    return True, None


def validate_date(date_str: str) -> Tuple[bool, Optional[str], Optional[datetime.date]]:
    """
    Валидирует дату.
    
    Args:
        date_str: Строка с датой
    
    Returns:
        (is_valid, error_message, parsed_date)
    """
    if not date_str or not isinstance(date_str, str):
        return False, "Дата не может быть пустой", None
    
    date_str = date_str.strip()
    
    # Пробуем различные форматы
    for pattern in DATE_PATTERNS:
        if re.match(pattern, date_str):
            try:
                # Парсим дату
                if '.' in date_str:
                    # DD.MM.YYYY
                    parts = date_str.split('.')
                    if len(parts) == 3:
                        day, month, year = map(int, parts)
                        parsed_date = datetime(year, month, day).date()
                elif '-' in date_str:
                    # YYYY-MM-DD
                    parsed_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                else:
                    # DD MM YYYY
                    parts = date_str.split()
                    if len(parts) == 3:
                        day, month, year = map(int, parts)
                        parsed_date = datetime(year, month, day).date()
                    else:
                        continue
                
                # Проверяем разумность даты (не слишком далеко в будущем/прошлом)
                today = datetime.now().date()
                years_diff = abs((parsed_date - today).days) / 365.25
                
                if years_diff > 5:
                    return False, "Дата слишком далеко от текущей", None
                
                return True, None, parsed_date
            except (ValueError, IndexError) as e:
                logger.debug(f"Ошибка парсинга даты {date_str}: {e}")
                continue
    
    return False, "Неверный формат даты. Используйте ДД.ММ.ГГГГ или ГГГГ-ММ-ДД", None


def sanitize_query(query: str) -> str:
    """
    Очищает запрос от потенциально опасных символов.
    
    Args:
        query: Запрос для очистки
    
    Returns:
        Очищенный запрос
    """
    if not query:
        return ""
    
    # Убираем начальные и конечные пробелы
    query = query.strip()
    
    # Заменяем множественные пробелы на один
    query = re.sub(r'\s+', ' ', query)
    
    # Ограничиваем длину
    if len(query) > MAX_QUERY_LENGTH:
        query = query[:MAX_QUERY_LENGTH]
    
    return query


def is_cancel_command(text: str) -> bool:
    """
    Проверяет, является ли текст командой отмены.
    
    Args:
        text: Текст для проверки
    
    Returns:
        True если это команда отмены
    """
    if not text:
        return False
    
    lowered = text.strip().lower()
    cleaned = lowered.replace("❌", "").replace("⛔", "").strip()
    
    cancel_commands = {"отмена", "cancel", "/cancel"}
    return cleaned in cancel_commands or lowered in {"отмена", "cancel", "/cancel", "❌ отмена", "❌отмена"}

