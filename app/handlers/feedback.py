"""
Обработчики отзывов
"""
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ..constants import CALLBACK_DATA_SETTINGS_MENU
from ..database import db
from .utils import safe_edit_message_text, safe_answer_callback_query

logger = logging.getLogger(__name__)


async def feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str = None):
    """Обработчик кнопки 'Оставить отзыв'"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"

    # Проверяем, можно ли оставить отзыв (1 раз в 24 часа)
    can_feedback, seconds_left = db.can_leave_feedback(user_id)

    if not can_feedback:
        # Вычисляем, сколько осталось ждать в формате чч:мм:сс
        hours_left = seconds_left // 3600
        minutes_left = (seconds_left % 3600) // 60
        seconds_remaining = seconds_left % 60

        # Форматируем время в формате чч:мм:сс
        time_str = f"{hours_left:02d}:{minutes_left:02d}:{seconds_remaining:02d}"

        # Показываем всплывающее уведомление. Используем show_alert=True,
        # чтобы сообщение гарантированно появилось (как системный popup в Telegram).
        await safe_answer_callback_query(
            update.callback_query,
            f"⏳ Повторите через {time_str}",
            show_alert=True
        )
        logger.info(f"⏳ [{user_id}] @{username} → Попытка оставить отзыв (ограничение: {time_str})")

        return

    # Устанавливаем флаг ожидания отзыва
    context.user_data["awaiting_feedback"] = True

    text = (
        "💬 <b>Оставить отзыв</b>\n\n"
        "Напишите ваш отзыв, пожелание или предложение по улучшению бота.\n\n"
        "📝 Просто отправьте сообщение в этот чат.\n\n"
        "<i>Отзыв можно оставлять 1 раз в сутки.</i>"
    )

    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Отмена", callback_data=CALLBACK_DATA_SETTINGS_MENU)]
    ])

    await safe_edit_message_text(update.callback_query, text, reply_markup=kbd, parse_mode=ParseMode.HTML)
    await safe_answer_callback_query(update.callback_query)
    logger.debug(f"💬 [{user_id}] @{username} → Открыл форму отзыва")


async def process_feedback_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    """
    Обработка текстового сообщения как отзыва.
    Возвращает True если сообщение было обработано как отзыв.
    """
    user_data = context.user_data

    if not user_data.get("awaiting_feedback"):
        return False

    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name

    # Сбрасываем флаг ожидания
    user_data.pop("awaiting_feedback", None)

    # Проверяем ещё раз лимит (на случай спама)
    can_feedback, _ = db.can_leave_feedback(user_id)
    if not can_feedback:
        await update.message.reply_text("⏳ Вы уже оставляли отзыв сегодня. Попробуйте завтра!")
        return True

    # Сохраняем отзыв
    db.save_feedback(
        user_id=user_id,
        username=username,
        first_name=first_name,
        last_name=update.effective_user.last_name,
        message=text
    )

    db.log_activity(user_id, "feedback_sent", f"length={len(text)}")

    await update.message.reply_text(
        "✅ Спасибо за ваш отзыв! Мы обязательно его учтём."
    )
    logger.info(f"💬 [{user_id}] @{username} → Отзыв сохранён ({len(text)} символов)")

    return True

