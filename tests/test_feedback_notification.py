#!/usr/bin/env python3
"""
Проверка всплывающего уведомления при попытке повторного отзыва.
Запускается без pytest:  python tests/test_feedback_notification.py
"""
import asyncio
import sys
from types import SimpleNamespace
from datetime import datetime

from app.handlers import feedback_callback


class DummyCallbackQuery:
    """Заглушка callback_query для проверки answer"""

    def __init__(self):
        self.answers = []

    async def answer(self, text: str = "", show_alert: bool = False):
        self.answers.append({"text": text, "show_alert": show_alert})

    # для совместимости с safe_edit_message_text (не используется здесь)
    async def edit_message_text(self, *args, **kwargs):
        return True


class DummyUpdate:
    def __init__(self, callback_query):
        self.callback_query = callback_query
        self.effective_user = SimpleNamespace(id=123, username="tester")
        self.effective_chat = SimpleNamespace(id=123)


class DummyContext:
    def __init__(self):
        self.user_data = {}


async def scenario(can_leave_feedback_result):
    """
    can_leave_feedback_result: tuple (can, seconds_left)
    """
    # Мокаем db.can_leave_feedback
    from app import handlers

    original = handlers.db.can_leave_feedback
    handlers.db.can_leave_feedback = lambda _: can_leave_feedback_result

    try:
        cq = DummyCallbackQuery()
        update = DummyUpdate(cq)
        ctx = DummyContext()
        await feedback_callback(update, ctx)
        return cq.answers
    finally:
        handlers.db.can_leave_feedback = original


async def main():
    print("== Проверка уведомления при повторном отзыве ==")
    answers = await scenario((False, 5 * 3600 + 23 * 60 + 45))  # 05:23:45
    if not answers:
        print("❌ Нет ответа на callback")
        sys.exit(1)
    ans = answers[0]
    # Печать без не-ASCII символов, чтобы не ломать cp1251
    # Убираем emoji из строки, чтобы не было проблем с cp1251
    clean_text = ans['text'].replace("⏳", "WAIT")
    print(f"Result: text='{clean_text}', show_alert={ans['show_alert']}")
    assert "05:23:45" in ans["text"], "Время не отформатировано"
    assert ans["show_alert"] is True, "Должно быть show_alert=True для видимого popup"
    print("OK: popup shown for repeated feedback")

    print("\n== Проверка первого отзыва (должно открыть форму) ==")
    answers = await scenario((True, None))
    # В этом случае feedback_callback не отвечает через answer; главное, что нет ошибок
    print("OK: first feedback - no errors, form should open")


if __name__ == "__main__":
    asyncio.run(main())

