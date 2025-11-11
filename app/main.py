import asyncio
import logging
import sys
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, PicklePersistence, ContextTypes, filters, InlineQueryHandler
from telegram.error import TimedOut, Conflict, NetworkError

from .config import TOKEN
from .handlers import (
    start_command,
    help_command_handler,
    settings_menu_callback,
    handle_text_message,
    callback_router,
)
from .jobs import check_schedule_changes_job
from .http import close_http_client

# Настройка подробного логирования с поддержкой Unicode для Windows
# Создаем StreamHandler с правильной кодировкой для Windows
if sys.platform == 'win32':
    # Для Windows используем UTF-8 с обработкой ошибок
    class UnicodeStreamHandler(logging.StreamHandler):
        def __init__(self, stream=None):
            super().__init__(stream)
            # Устанавливаем UTF-8 кодировку для stdout/stderr
            if hasattr(sys.stdout, 'reconfigure'):
                try:
                    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
                except Exception:
                    pass
            if hasattr(sys.stderr, 'reconfigure'):
                try:
                    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
                except Exception:
                    pass

        def emit(self, record):
            try:
                msg = self.format(record)
                stream = self.stream
                # Пытаемся записать как есть
                stream.write(msg + self.terminator)
                self.flush()
            except (UnicodeEncodeError, UnicodeError):
                # Если не получается, заменяем проблемные символы
                try:
                    msg = self.format(record)
                    import re
                    # Заменяем эмодзи и специальные символы на текстовые альтернативы
                    msg = re.sub(r'[\U0001F300-\U0001F9FF]', '[E]', msg)  # Эмодзи
                    msg = re.sub(r'[\u2600-\u27BF]', '[S]', msg)  # Разные символы
                    msg = re.sub(r'[\u2192]', '->', msg)  # Стрелка вправо
                    stream = self.stream
                    stream.write(msg + self.terminator)
                    self.flush()
                except Exception:
                    # В крайнем случае просто пишем без форматирования
                    try:
                        stream.write(f"{record.levelname}: {record.getMessage()}\n")
                        self.flush()
                    except Exception:
                        self.handleError(record)
            except Exception:
                self.handleError(record)

    handler = UnicodeStreamHandler(sys.stdout)
else:
    handler = logging.StreamHandler(sys.stdout)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[handler],
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Специальная обработка для Conflict - не выводим полный traceback
    if isinstance(context.error, Conflict):
        logger.warning("⚠️ Обнаружен конфликт: уже запущен другой экземпляр бота. "
                      "Убедитесь, что запущен только один экземпляр бота.")
        return

    # Специальная обработка для TimedOut
    if isinstance(context.error, TimedOut):
        logger.warning("⏱️ Сетевой таймаут при обращении к API Telegram.")
        return

    # Специальная обработка для NetworkError (включая ConnectError)
    if isinstance(context.error, NetworkError):
        error_msg = str(context.error)
        if "ConnectError" in error_msg or "Connection" in error_msg:
            logger.warning("🌐 Ошибка подключения к сети. Бот продолжит работу после восстановления соединения.")
        else:
            logger.warning(f"🌐 Сетевая ошибка: {error_msg}")
        # Не прерываем выполнение - обработчики сами должны обрабатывать сетевые ошибки с повторными попытками
        return

    # Для остальных ошибок выводим полный traceback
    logger.error("Произошла ошибка:", exc_info=context.error)

def build_app() -> Application:
    # Оптимизированная настройка приложения для высокой нагрузки
    persistence = PicklePersistence(filepath="bot_data.pickle")

    # Включаем параллельную обработку обновлений для многопоточности
    app = (
        Application.builder()
        .token(TOKEN)
        .persistence(persistence)
        .concurrent_updates(True)  # Разрешаем обработку нескольких апдейтов одновременно
        .build()
    )

    # Оптимизируем настройки для работы с большим количеством пользователей
    # concurrent_updates уже включен, что позволяет обрабатывать несколько запросов параллельно

    # Команды (обрабатываются первыми)
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command_handler))
    app.add_handler(CommandHandler("settings", settings_menu_callback))

    # Админ-панель
    from .admin.handlers import admin_command, handle_maintenance_message_input, handle_admin_id_input, handle_remove_admin_id_input, handle_broadcast_input
    app.add_handler(CommandHandler("admin", admin_command))

    # Обработка текстовых сообщений (должен быть после команд, но команды уже обработаны)
    # Сначала проверяем админские команды
    from .admin.handlers import (
        handle_maintenance_message_input, handle_admin_id_input,
        handle_remove_admin_id_input, handle_broadcast_input, handle_user_search_input
    )
    from .admin.utils import is_admin

    async def text_message_with_admin_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user:
            return

        user_id = update.effective_user.id

        # Проверяем, ожидает ли админ ввода
        if is_admin(user_id):
            if context.user_data.get('awaiting_maintenance_msg'):
                await handle_maintenance_message_input(update, context)
                return
            elif context.user_data.get('awaiting_admin_id'):
                await handle_admin_id_input(update, context)
                return
            elif context.user_data.get('awaiting_remove_admin_id'):
                await handle_remove_admin_id_input(update, context)
                return
            elif context.user_data.get('awaiting_broadcast'):
                await handle_broadcast_input(update, context)
                return
            elif context.user_data.get('awaiting_user_search'):
                await handle_user_search_input(update, context)
                return

        # Обычная обработка сообщений
        await handle_text_message(update, context)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_with_admin_check))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_error_handler(error_handler)
    # Inline режим (поиск через @username)
    from .handlers import inline_query_handler
    app.add_handler(InlineQueryHandler(inline_query_handler))

    if app.job_queue:
        app.job_queue.run_repeating(
            check_schedule_changes_job, interval=5400, first=60, name="check_schedule_changes"
        )
    return app

def main() -> None:
    if "YOUR_TOKEN" in TOKEN or len(TOKEN.split(":")[0]) < 8:
        logger.critical("Необходимо указать корректный токен бота!")
        return

    app = build_app()
    logger.info("Бот запускается...")
    logger.info("💡 Совет: Если видите ошибку 'Conflict', значит уже запущен другой экземпляр бота.")
    logger.info("   Закройте все другие экземпляры и запустите бота снова.")
    try:
        app.run_polling()
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")
    finally:
        # Закрываем HTTP клиент, если он был создан
        # Используем try-except, так как event loop может быть уже закрыт
        try:
            # Пытаемся получить текущий event loop
            try:
                loop = asyncio.get_running_loop()
                # Если loop работает, пропускаем закрытие (он закроется сам)
                logger.info("Event loop все еще активен, HTTP клиент закроется автоматически")
            except RuntimeError:
                # Нет активного loop, можно создать новый для закрытия
                try:
                    asyncio.run(close_http_client())
                    logger.info("HTTP клиент успешно закрыт")
                except RuntimeError:
                    # Event loop уже закрыт или не может быть создан
                    logger.info("Event loop закрыт, пропускаем закрытие HTTP клиента")
        except Exception as e:
            logger.warning(f"Ошибка при закрытии HTTP клиента: {e}")


