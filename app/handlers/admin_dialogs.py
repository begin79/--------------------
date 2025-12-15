"""
Обработчики диалогов администратора с пользователями
"""
import datetime
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from ..database import db
from ..utils import escape_html
from ..admin.handlers import (
    CALLBACK_ADMIN_MESSAGE_USER_PREFIX,
    CALLBACK_ADMIN_USER_DETAILS_PREFIX,
)
from .utils import get_admin_dialog_storage, get_admin_reply_states

logger = logging.getLogger(__name__)


async def start_user_reply_to_admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    admin_id: int,
):
    """Подготовить пользователя к отправке ответа администратору"""
    user_data = context.user_data
    user_id = update.effective_user.id if update.effective_user else None
    user_data["pending_admin_reply"] = admin_id

    dialogs = get_admin_dialog_storage(context)
    if user_id is not None:
        entry = dialogs.get(user_id, {})
        entry.update({"admin_id": admin_id, "last_prompt_at": datetime.datetime.utcnow().isoformat()})
        dialogs[user_id] = entry

    try:
        await update.callback_query.edit_message_reply_markup(reply_markup=None)
    except Exception as e:
        logger.debug(f"Ошибка при редактировании reply_markup: {e}", exc_info=True)

    await update.callback_query.answer("Напишите ответ администратору.", show_alert=False)
    await update.callback_query.message.reply_text(
        "✏️ Напишите ваш ответ администратору. Чтобы отменить, отправьте 'отмена' или /cancel."
    )


async def handle_user_dismiss_admin_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    admin_id: int,
):
    """Пользователь закрыл уведомление администратора"""
    user_data = context.user_data
    user_id = update.effective_user.id if update.effective_user else None
    if user_data.get("pending_admin_reply") == admin_id:
        user_data.pop("pending_admin_reply", None)
        reply_states = get_admin_reply_states(context)
        if user_id is not None:
            reply_states.pop(user_id, None)
    dialogs = get_admin_dialog_storage(context)
    if user_id is not None:
        dialogs.pop(user_id, None)

    try:
        await update.callback_query.edit_message_reply_markup(reply_markup=None)
    except Exception as e:
        logger.debug(f"Ошибка при редактировании reply_markup: {e}", exc_info=True)

    await update.callback_query.answer("Уведомление закрыто.", show_alert=False)
    await update.callback_query.message.reply_text("Если потребуется, вы всегда можете открыть /settings и связаться с администратором ещё раз.")


async def process_user_reply_to_admin_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    admin_id: int,
    text: str,
):
    """Отправить ответ пользователя администратору"""
    user_data = context.user_data
    user_id = update.effective_user.id if update.effective_user else None
    username = update.effective_user.username if update.effective_user else None
    full_name = update.effective_user.full_name if update.effective_user else (update.effective_user.first_name if update.effective_user else "")

    user_data.pop("pending_admin_reply", None)
    reply_states = get_admin_reply_states(context)
    reply_states.pop(user_id, None)

    dialogs = get_admin_dialog_storage(context)
    if user_id is not None:
        dialogs[user_id] = {
            "admin_id": admin_id,
            "last_reply_at": datetime.datetime.utcnow().isoformat()
        }

    username_display = f"@{escape_html(username)}" if username else "без username"
    full_name_display = escape_html(full_name) if full_name else "не указано"

    admin_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✉️ Ответить пользователю", callback_data=f"{CALLBACK_ADMIN_MESSAGE_USER_PREFIX}{user_id}")],
        [InlineKeyboardButton("👤 Профиль пользователя", callback_data=f"{CALLBACK_ADMIN_USER_DETAILS_PREFIX}{user_id}")],
    ])

    admin_message = (
        "📥 <b>Ответ от пользователя</b>\n\n"
        f"ID: <code>{user_id}</code>\n"
        f"Username: {username_display}\n"
        f"Имя: {full_name_display}\n\n"
        f"{escape_html(text)}"
    )

    try:
        await context.bot.send_message(
            chat_id=admin_id,
            text=admin_message,
            parse_mode=ParseMode.HTML,
            reply_markup=admin_keyboard
        )
        if user_id:
            db.log_activity(user_id, "admin_reply_sent", f"to={admin_id}")
    except Forbidden:
        logger.warning(f"Админ {admin_id} недоступен для получения ответа пользователя {user_id}")
    except BadRequest as e:
        logger.error(f"Ошибка телеграма при доставке ответа пользователя {user_id} админу {admin_id}: {e}")
    except Exception as e:
        logger.error(f"Ошибка при доставке ответа пользователя {user_id} админу {admin_id}: {e}", exc_info=True)

    await update.message.reply_text("✅ Ваш ответ отправлен администратору.")

