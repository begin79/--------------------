"""
Вспомогательные функции для обработчиков
"""
import asyncio
import logging
from typing import Optional
from contextlib import contextmanager
from telegram import Message
from telegram.error import BadRequest, NetworkError, TimedOut
from telegram.ext import ContextTypes

from ..state_manager import set_user_busy

logger = logging.getLogger(__name__)


async def safe_answer_callback_query(callback_query, text: str = "", show_alert: bool = False) -> bool:
    """
    Безопасно отвечает на callback query с обработкой ошибок timeout
    Возвращает True если ответ успешен, False если callback query истек
    """
    try:
        await callback_query.answer(text, show_alert=show_alert)
        return True
    except BadRequest as e:
        if "query is too old" in str(e).lower() or "query id is invalid" in str(e).lower():
            logger.debug(f"Callback query истек: {e}")
            return False
        else:
            logger.debug(f"Ошибка при ответе на callback query: {e}")
            return False
    except (NetworkError, TimedOut) as e:
        logger.debug(f"Сетевая ошибка при ответе на callback query: {e}")
        return False
    except Exception as e:
        logger.debug(f"Неожиданная ошибка при ответе на callback query: {e}", exc_info=True)
        return False


async def safe_edit_message_text(callback_query, text: str, reply_markup=None, parse_mode=None) -> bool:
    """
    Безопасно редактирует сообщение с обработкой ошибок
    Возвращает True если редактирование успешно, False если произошла ошибка
    """
    try:
        await callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        return True
    except BadRequest as e:
        error_str = str(e).lower()
        if "message is not modified" in error_str:
            # Сообщение уже имеет такой же текст - это не ошибка
            return True
        elif "message to edit not found" in error_str or "chat not found" in error_str:
            logger.debug(f"Сообщение не найдено для редактирования: {e}")
            return False
        elif "no text in the message" in error_str:
            # Сообщение не содержит текста (например, только фото) - отправляем новое
            try:
                await callback_query.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
                return True
            except Exception as reply_error:
                logger.debug(f"Ошибка при отправке нового сообщения: {reply_error}", exc_info=True)
                return False
        else:
            logger.debug(f"Ошибка при редактировании сообщения: {e}")
            return False
    except (NetworkError, TimedOut) as e:
        logger.debug(f"Сетевая ошибка при редактировании сообщения: {e}")
        return False
    except Exception as e:
        logger.debug(f"Неожиданная ошибка при редактировании сообщения: {e}", exc_info=True)
        return False


@contextmanager
def user_busy_context(user_data: dict):
    """
    Context Manager для автоматического управления блокировкой пользователя.

    Использование:
        with user_busy_context(context.user_data):
            # Делаем долгую работу
            await do_heavy_task()
        # Блокировка снимется автоматически
    """
    set_user_busy(user_data, True)
    try:
        yield
    finally:
        set_user_busy(user_data, False)


class ExportProgress:
    """Текстовый индикатор прогресса для долгих операций экспорта"""

    def __init__(self, parent_message: Optional[Message]):
        self.parent_message = parent_message
        self.message: Optional[Message] = None
        self.current_percent = 0
        self.current_text = ""

    @staticmethod
    def _format(text: str, percent: int) -> str:
        blocks = 10
        filled = max(0, min(blocks, round(percent / 10)))
        bar = "█" * filled + "░" * (blocks - filled)
        return f"{text}\n{bar} {percent}%"

    async def start(self, text: str) -> None:
        if not self.parent_message:
            logger.warning("ExportProgress.start: parent_message is None")
            return
        try:
            initial_percent = 5
            self.current_percent = initial_percent
            self.current_text = text
            self.message = await self.parent_message.reply_text(self._format(text, initial_percent))
            logger.debug(f"ExportProgress.start: Сообщение прогресса отправлено (message_id={self.message.message_id if self.message else None})")
        except Exception as e:
            logger.error(f"ExportProgress.start: Ошибка при запуске прогресса: {e}", exc_info=True)
            self.message = None

    async def update(self, percent: int, text: Optional[str] = None) -> None:
        if not self.message:
            return
        percent = max(0, min(100, percent))
        update_text = text or self.current_text or "⏳ Генерирую..."
        if abs(percent - self.current_percent) < 3 and update_text == self.current_text:
            return
        self.current_percent = percent
        self.current_text = update_text
        try:
            await self.message.edit_text(self._format(update_text, percent))
        except Exception as e:
            logger.debug(f"Ошибка при обновлении прогресса: {e}", exc_info=True)

    async def finish(self, text: str = "✅ Экспорт готов!", delete_after: float = 5.0) -> None:
        if not self.message:
            logger.warning("ExportProgress.finish: self.message is None")
            return
        try:
            await self.message.edit_text(text)
            if delete_after and self.message.get_bot():
                bot = self.message.get_bot()
                asyncio.create_task(
                    _delete_message_after_delay(bot, self.message.chat_id, self.message.message_id, delete_after)
                )
        except Exception as e:
            logger.error(f"ExportProgress.finish: Ошибка при завершении: {e}", exc_info=True)


async def _delete_message_after_delay(bot, chat_id: int, message_id: int, delay: float):
    """Удаляет сообщение через указанную задержку"""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.debug(f"Ошибка при удалении сообщения: {e}", exc_info=True)


def get_admin_dialog_storage(context: ContextTypes.DEFAULT_TYPE) -> dict:
    """Возвращает словарь активных диалогов админ ↔ пользователь"""
    return context.application.bot_data.setdefault("admin_dialogs", {})


def get_admin_reply_states(context: ContextTypes.DEFAULT_TYPE) -> dict:
    """Хранит состояния ожидания ответа пользователем администратору"""
    return context.application.bot_data.setdefault("admin_reply_states", {})


def load_user_data_from_db(user_id: int, user_data: dict):
    """Загружает данные пользователя из БД в user_data"""
    from ..database import db
    from ..constants import (
        CTX_DEFAULT_QUERY, CTX_DEFAULT_MODE,
        CTX_DAILY_NOTIFICATIONS, CTX_NOTIFICATION_TIME
    )
    import logging
    logger = logging.getLogger(__name__)

    try:
        user_db = db.get_user(user_id)
        if user_db:
            if user_db.get('default_query'):
                user_data[CTX_DEFAULT_QUERY] = user_db['default_query']
            if user_db.get('default_mode'):
                user_data[CTX_DEFAULT_MODE] = user_db['default_mode']
            if user_db.get('daily_notifications') is not None:
                user_data[CTX_DAILY_NOTIFICATIONS] = bool(user_db['daily_notifications'])
            if user_db.get('notification_time'):
                user_data[CTX_NOTIFICATION_TIME] = user_db['notification_time']
            logger.debug(f"Данные пользователя {user_id} загружены из БД")
    except Exception as e:
        logger.error(f"Ошибка загрузки данных пользователя {user_id} из БД: {e}", exc_info=True)


def save_user_data_to_db(user_id: int, username: str, first_name: str, last_name: str, user_data: dict):
    """Сохраняет данные пользователя из user_data в БД (только если данные изменились)"""
    from ..database import db
    from ..constants import (
        CTX_DEFAULT_QUERY, CTX_DEFAULT_MODE,
        CTX_DAILY_NOTIFICATIONS, CTX_NOTIFICATION_TIME
    )
    import logging
    logger = logging.getLogger(__name__)

    try:
        # 1. Получаем текущее состояние
        existing = db.get_user(user_id)

        # 2. Данные для сохранения
        new_query = user_data.get(CTX_DEFAULT_QUERY)
        new_mode = user_data.get(CTX_DEFAULT_MODE)
        new_notif = bool(user_data.get(CTX_DAILY_NOTIFICATIONS, False))
        new_time = user_data.get(CTX_NOTIFICATION_TIME, '21:00')

        # 3. Сравниваем. Если пользователь уже есть и данные те же — выходим.
        if existing:
            if (existing.get('default_query') == new_query and
                existing.get('default_mode') == new_mode and
                bool(existing.get('daily_notifications')) == new_notif and
                existing.get('notification_time') == new_time):
                return  # ИЗМЕНЕНИЙ НЕТ

        # 4. Пишем только если есть изменения
        db.save_user(
            user_id=user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            default_query=new_query,
            default_mode=new_mode,
            daily_notifications=new_notif,
            notification_time=new_time
        )
        logger.debug(f"Данные пользователя {user_id} сохранены в БД")
    except Exception as e:
        logger.error(f"Ошибка БД: {e}", exc_info=True)


def get_default_reply_keyboard():
    """Создает стандартную клавиатуру с кнопками 'Старт' и 'Настройки'"""
    from telegram import ReplyKeyboardMarkup, KeyboardButton
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("Старт"), KeyboardButton("Настройки")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )

