"""
Обработка отзывов от пользователей
"""
import logging
import asyncio
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes

from ..database import db
from ..constants import CTX_AWAITING_FEEDBACK, CTX_KEYBOARD_MESSAGE_ID
from ..state_manager import clear_temporary_states

logger = logging.getLogger(__name__)


async def process_feedback_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    """
    Обрабатывает отзыв от пользователя.
    Возвращает True если сообщение было обработано как отзыв, False иначе.
    """
    user_data = context.user_data
    user_id = update.effective_user.id if update.effective_user else None
    
    if not user_id:
        return False
    
    # Проверяем, ожидается ли отзыв
    if not user_data.get(CTX_AWAITING_FEEDBACK):
        return False
    
    # Проверяем, может ли пользователь оставить отзыв
    can_leave, seconds_left = db.can_leave_feedback(user_id)
    
    if not can_leave:
        # Если пользователю нельзя писать отзыв, мы ВЫКЛЮЧАЕМ режим ожидания
        # и говорим боту продолжить (return True), но теперь флаг удален
        user_data.pop(CTX_AWAITING_FEEDBACK, None)  # Сбрасываем флаг
        
        hours_left = seconds_left // 3600 if seconds_left else 0
        minutes_left = (seconds_left % 3600) // 60 if seconds_left else 0
        
        if hours_left > 0:
            time_msg = f"{hours_left} ч. {minutes_left} мин."
        else:
            time_msg = f"{minutes_left} мин."
        
        await update.message.reply_text(
            f"⏱️ Вы уже оставляли отзыв недавно.\n"
            f"Повторный отзыв можно оставить через {time_msg}."
        )
        clear_temporary_states(user_data)
        return True  # Оставляем True, чтобы текст группы не улетел в пустоту, но теперь флаг удален
    
    # Проверяем, что это не команда отмены
    lowered = text.lower().strip()
    # Обрабатываем как текстовый ввод "отмена", так и Reply-кнопку "❌ Отмена"
    # Убираем эмодзи и пробелы для проверки
    cleaned_text = lowered.replace("❌", "").replace("⛔", "").strip()
    if cleaned_text in {"отмена", "cancel", "/cancel"} or lowered in {"отмена", "cancel", "/cancel", "❌ отмена"}:
        user_data.pop(CTX_AWAITING_FEEDBACK, None)
        
        # Удаляем сообщение со стикером клавиатуры, если оно было отправлено
        keyboard_message_id = user_data.pop(CTX_KEYBOARD_MESSAGE_ID, None)
        if keyboard_message_id:
            try:
                await context.bot.delete_message(
                    chat_id=update.message.chat_id,
                    message_id=keyboard_message_id
                )
            except Exception as e:
                logger.debug(f"Ошибка при удалении сообщения со стикером: {e}")
        
        # Убираем Reply-кнопку отмены, отправляя пустое сообщение и сразу удаляя его
        try:
            temp_msg = await update.message.reply_text(" ", reply_markup=ReplyKeyboardRemove())
            await asyncio.sleep(0.2)
            try:
                await context.bot.delete_message(
                    chat_id=update.message.chat_id,
                    message_id=temp_msg.message_id
                )
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"Ошибка при удалении Reply-клавиатуры: {e}")
        
        return True
    
    # Сохраняем отзыв
    username = update.effective_user.username if update.effective_user else None
    first_name = update.effective_user.first_name if update.effective_user else None
    
    if db.save_feedback(user_id, text, username=username, first_name=first_name):
        await update.message.reply_text(
            "✅ Спасибо за ваш отзыв! Ваше мнение очень важно для нас.\n\n"
            "Мы обязательно его рассмотрим и учтем при дальнейшей разработке бота."
        )
        logger.info(f"Пользователь {user_id} оставил отзыв: {text[:50]}...")
    else:
        await update.message.reply_text(
            "❌ Произошла ошибка при сохранении отзыва. Попробуйте позже."
        )
    
    clear_temporary_states(user_data)
    return True

