"""
Обработка диалогов пользователей с администраторами
"""
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.error import Forbidden, BadRequest

from ..database import db
from ..utils import escape_html
from ..admin.database import admin_db

logger = logging.getLogger(__name__)


def get_admin_reply_states(context: ContextTypes.DEFAULT_TYPE) -> dict:
    """
    Возвращает словарь состояний ожидания ответа пользователем администратору.
    Это обертка над функцией из admin/handlers.py для использования в handlers.
    """
    # Проверяем, есть ли функция в admin.handlers
    try:
        from ..admin.handlers import _get_admin_reply_states
        return _get_admin_reply_states(context)
    except ImportError:
        # Fallback: создаем словарь в bot_data
        if not hasattr(context, 'application') or not hasattr(context.application, 'bot_data'):
            return {}
        return context.application.bot_data.setdefault("admin_reply_states", {})


async def process_user_reply_to_admin_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    admin_id: int,
    text: str
) -> None:
    """
    Обрабатывает ответ пользователя администратору.
    
    Args:
        update: Обновление от Telegram
        context: Контекст приложения
        admin_id: ID администратора, которому отвечает пользователь
        text: Текст ответа пользователя
    """
    user_id = update.effective_user.id if update.effective_user else None
    
    if not user_id:
        logger.error("process_user_reply_to_admin_message вызван без user_id")
        return
    
    # Проверяем, что администратор существует
    if not admin_db.is_admin(admin_id):
        await update.message.reply_text(
            "❌ Ошибка: администратор не найден. Ответ не может быть отправлен."
        )
        logger.warning(f"Пользователь {user_id} пытался ответить несуществующему админу {admin_id}")
        return
    
    # Формируем сообщение для администратора
    username = update.effective_user.username or "без username"
    first_name = update.effective_user.first_name or "Без имени"
    
    admin_message = (
        f"💬 <b>Ответ от пользователя</b>\n\n"
        f"👤 Пользователь: {escape_html(first_name)} (@{escape_html(username)})\n"
        f"🆔 ID: <code>{user_id}</code>\n\n"
        f"💬 <b>Сообщение:</b>\n<i>{escape_html(text)}</i>"
    )
    
    # Кнопки для администратора
    admin_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💬 Ответить", callback_data=f"admin_message_user_{user_id}"),
            InlineKeyboardButton("👤 Профиль", callback_data=f"admin_user_details_{user_id}")
        ]
    ])
    
    try:
        # Отправляем сообщение администратору
        await context.bot.send_message(
            chat_id=admin_id,
            text=admin_message,
            parse_mode=ParseMode.HTML,
            reply_markup=admin_keyboard
        )
        
        # Подтверждаем пользователю
        await update.message.reply_text(
            "✅ Ваше сообщение отправлено администратору. "
            "Ожидайте ответа!"
        )
        
        # Логируем
        db.log_activity(user_id, "reply_to_admin", f"admin_id={admin_id}")
        admin_db.log_admin_action(
            admin_id, None,
            "received_user_reply",
            f"user_id={user_id}, message_length={len(text)}",
            target_user_id=user_id
        )
        
        logger.info(f"Пользователь {user_id} ответил администратору {admin_id}")
        
    except Forbidden:
        await update.message.reply_text(
            "⚠️ Администратор заблокировал бота. Сообщение не может быть доставлено."
        )
        logger.warning(f"Не удалось отправить ответ пользователя {user_id} администратору {admin_id}: Forbidden")
    except BadRequest as e:
        await update.message.reply_text(
            "❌ Ошибка при отправке сообщения. Попробуйте позже."
        )
        logger.error(f"Ошибка Telegram при отправке ответа администратору {admin_id}: {e}")
    except Exception as e:
        await update.message.reply_text(
            "❌ Произошла ошибка при отправке сообщения администратору."
        )
        logger.error(f"Ошибка при отправке ответа администратору {admin_id}: {e}", exc_info=True)

