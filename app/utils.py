"""
Вспомогательные утилиты
"""
import html
import hashlib
import json
import re
import datetime
from typing import List, Dict, Any, Optional


def escape_html(text: str) -> str:
    """
    Экранирует HTML-символы в тексте для безопасного отображения в Telegram
    """
    return html.escape(str(text))


def hash_schedule(pages: List[str]) -> str:
    """
    Создает хеш расписания для сравнения версий
    """
    if not pages:
        return ""
    content = "\n".join(pages)
    return hashlib.md5(content.encode('utf-8')).hexdigest()


def compare_schedules(old_schedule: Optional[Dict], new_schedule: Optional[Dict]) -> List[Dict[str, Any]]:
    """
    Сравнивает два расписания и возвращает список изменений
    """
    changes = []
    
    if not old_schedule or not new_schedule:
        return changes
    
    old_pairs = old_schedule.get("pairs", [])
    new_pairs = new_schedule.get("pairs", [])
    
    # Создаем словари для быстрого поиска
    old_dict = {f"{p.get('time', '')}_{p.get('subject', '')}": p for p in old_pairs}
    new_dict = {f"{p.get('time', '')}_{p.get('subject', '')}": p for p in new_pairs}
    
    # Находим добавленные пары
    for key, pair in new_dict.items():
        if key not in old_dict:
            changes.append({"type": "added", "pair": pair})
    
    # Находим удаленные пары
    for key, pair in old_dict.items():
        if key not in new_dict:
            changes.append({"type": "removed", "pair": pair})
    
    # Находим измененные пары
    for key in old_dict:
        if key in new_dict:
            old_pair = old_dict[key]
            new_pair = new_dict[key]
            if old_pair != new_pair:
                changes.append({"type": "modified", "old": old_pair, "new": new_pair})
    
    return changes


def detect_pair_type(subject: str) -> str:
    """
    Определяет тип пары по названию предмета.
    Возвращает ключ типа для использования с PAIR_TYPE_EMOJIS.
    
    Args:
        subject: Название предмета
        
    Returns:
        Ключ типа пары (лекция, практика, лабораторная, семинар, зачет, экзамен, консультация, default)
    """
    if not subject:
        return "default"
    
    subject_lower = subject.lower()
    
    # Паттерны для определения типа пары
    patterns = {
        "лекция": [r"\bлекц\w*", r"\bл\.", r"\bл\b"],
        "практика": [r"\bпракт\w*", r"\bпр\.", r"\bпр\b"],
        "лабораторная": [r"\bлаб\w*", r"\bлабораторн\w*", r"\bл\.р\.", r"\bлр\b"],
        "семинар": [r"\bсеминар\w*", r"\bсем\w*"],
        "зачет": [r"\bзачет\w*", r"\bзач\w*"],
        "экзамен": [r"\bэкзамен\w*", r"\bэкз\w*"],
        "консультация": [r"\bконсультац\w*", r"\bконс\w*"],
    }
    
    # Проверяем паттерны в порядке приоритета
    for pair_type, type_patterns in patterns.items():
        for pattern in type_patterns:
            if re.search(pattern, subject_lower):
                return pair_type
    
    return "default"


def get_pair_type_emoji(subject: str) -> str:
    """
    Возвращает эмодзи для типа пары на основе названия предмета.
    
    Args:
        subject: Название предмета
        
    Returns:
        Эмодзи для типа пары
    """
    from .constants import PAIR_TYPE_EMOJIS
    pair_type = detect_pair_type(subject)
    return PAIR_TYPE_EMOJIS.get(pair_type, PAIR_TYPE_EMOJIS["default"])


def get_next_weekday(date: datetime.date) -> datetime.date:
    """
    Получить следующий рабочий день (понедельник-суббота)
    
    Args:
        date: Текущая дата
        
    Returns:
        Следующий рабочий день
    """
    next_day = date + datetime.timedelta(days=1)
    # Если следующий день - воскресенье, возвращаем понедельник
    if next_day.weekday() == 6:  # Воскресенье
        return next_day + datetime.timedelta(days=1)
    return next_day


def format_schedule_changes(changes: List[Dict[str, Any]], date_str: str, query: str) -> str:
    """
    Форматирует список изменений в читаемое сообщение
    """
    if not changes:
        return f"🔔 <b>Расписание изменилось</b>\n\nРасписание для {escape_html(query)} было обновлено."
    
    msg = f"🔔 <b>Изменения в расписании</b>\n\n"
    msg += f"📅 Дата: {date_str}\n"
    msg += f"📌 {escape_html(query)}\n\n"
    
    added = [c for c in changes if c.get("type") == "added"]
    removed = [c for c in changes if c.get("type") == "removed"]
    modified = [c for c in changes if c.get("type") == "modified"]
    
    if added:
        msg += "➕ <b>Добавлено:</b>\n"
        for change in added[:5]:  # Ограничиваем количество
            pair = change.get("pair", {})
            time = pair.get("time", "")
            subject = pair.get("subject", "")
            msg += f"  • {time} - {escape_html(subject)}\n"
        if len(added) > 5:
            msg += f"  ... и еще {len(added) - 5}\n"
        msg += "\n"
    
    if removed:
        msg += "➖ <b>Удалено:</b>\n"
        for change in removed[:5]:
            pair = change.get("pair", {})
            time = pair.get("time", "")
            subject = pair.get("subject", "")
            msg += f"  • {time} - {escape_html(subject)}\n"
        if len(removed) > 5:
            msg += f"  ... и еще {len(removed) - 5}\n"
        msg += "\n"
    
    if modified:
        msg += "🔄 <b>Изменено:</b>\n"
        for change in modified[:3]:
            old_pair = change.get("old", {})
            new_pair = change.get("new", {})
            msg += f"  • {old_pair.get('time', '')} - {escape_html(old_pair.get('subject', ''))} → {escape_html(new_pair.get('subject', ''))}\n"
        if len(modified) > 3:
            msg += f"  ... и еще {len(modified) - 3}\n"
    
    return msg

