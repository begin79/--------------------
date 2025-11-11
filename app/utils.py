import html
from typing import List
import hashlib
import datetime

def escape_html(text: str) -> str:
    return html.escape(str(text))

def hash_schedule(pages: List[str]) -> str:
    content = "|".join(pages)
    return hashlib.md5(content.encode("utf-8")).hexdigest()

def get_next_weekday(date: datetime.date) -> datetime.date:
    """Получить следующий рабочий день (пропуская выходные)"""
    next_day = date + datetime.timedelta(days=1)
    # Если воскресенье (6) или суббота (5), переходим на понедельник
    while next_day.weekday() >= 5:  # 5 = суббота, 6 = воскресенье
        next_day += datetime.timedelta(days=1)
    return next_day


