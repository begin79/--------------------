"""
Обработчик команды /help
"""
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ..constants import (
    CALLBACK_DATA_SETTINGS_MENU,
    CALLBACK_DATA_BACK_TO_START,
)
from .utils import safe_edit_message_text

logger = logging.getLogger(__name__)


async def help_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    logger.info(f"👤 [{user_id}] @{username} → Команда /help")

    text = (
        "ℹ️ <b>Справка</b>\n\n"
        "<b>Справка по боту ВГЛТУ Расписание</b>\n\n"
        "<b>📋 Основные команды:</b>\n"
        "🔹 <b>/start</b> - Главное меню\n"
        "🔹 <b>/settings</b> - Настройки и уведомления\n"
        "🔹 <b>/help</b> - Эта справка\n\n"
        "<b>🎓 Как пользоваться:</b>\n"
        "1️⃣ Выберите режим (студент/преподаватель)\n"
        "2️⃣ Введите группу или ФИО преподавателя\n"
        "3️⃣ Установите расписание по умолчанию\n"
        "4️⃣ Включите уведомления (опционально)\n\n"
        "<b>📱 Inline режим:</b>\n"
        "Используйте бота в любом чате! Начните вводить:\n"
        "<code>@Vgltu25_bot ИС1-231</code> - поиск группы\n"
        "<code>@Vgltu25_bot п Иванов</code> - поиск преподавателя\n\n"
        "<b>📤 Экспорт:</b>\n"
        "📄 PDF - для печати\n"
        "🖼 Изображение - для быстрого просмотра\n\n"
        "💡 <i>Совет: Установите группу по умолчанию для быстрого доступа!</i>"
    )
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Настройки", callback_data=CALLBACK_DATA_SETTINGS_MENU)],
        [InlineKeyboardButton("🏠 В начало", callback_data=CALLBACK_DATA_BACK_TO_START)]
    ])
    if update.callback_query:
        if not await safe_edit_message_text(update.callback_query, text, reply_markup=reply_markup, parse_mode=ParseMode.HTML):
            try:
                await update.callback_query.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            except Exception as e:
                logger.debug(f"Ошибка при отправке сообщения: {e}", exc_info=True)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

