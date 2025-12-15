import asyncio
import logging
import sys
from datetime import datetime, time, timezone
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, PicklePersistence, ContextTypes, filters, InlineQueryHandler
from telegram.error import TimedOut, Conflict, NetworkError

try:
    from .config import TOKEN, BOT_DATA_PATH
except ImportError:
    logging.error("Не удалось импортировать config.py")
    raise
from .handlers import (
    start_command,
    help_command_handler,
    settings_menu_callback,
    handle_text_message,
    callback_router,
)
from .jobs import check_schedule_changes_job
from .http import close_http_client
from .admin.database import admin_db
import os

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

# Вынесенные функции из build_app для улучшения производительности

async def text_message_with_admin_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений с проверкой админских команд"""
    if not update.effective_user:
        return

    user_id = update.effective_user.id
    text = update.message.text.strip() if update.message.text else ""

    # Проверяем, ожидает ли админ ввода
    from .admin.utils import is_admin
    from .admin.handlers import (
        handle_maintenance_message_input, handle_admin_id_input,
        handle_remove_admin_id_input, handle_broadcast_input,
        handle_user_search_input, handle_direct_message_input
    )

    if is_admin(user_id):
        # ВАЖНО: Если админ отправляет /start или "Старт", сбрасываем все флаги админ-панели
        if text == "/start" or text.startswith("/start") or text.strip().lower() == "старт":
            # Сбрасываем все флаги ожидания ввода админ-панели
            context.user_data.pop('awaiting_broadcast', None)
            context.user_data.pop('broadcast_message', None)
            context.user_data.pop('awaiting_maintenance_msg', None)
            context.user_data.pop('awaiting_admin_id', None)
            context.user_data.pop('awaiting_remove_admin_id', None)
            context.user_data.pop('awaiting_user_search', None)
            context.user_data.pop('awaiting_direct_message', None)
            context.user_data.pop('direct_message_target', None)
            logger.info(f"Админ {user_id} отправил /start - сброшены все флаги админ-панели")
            # Продолжаем обычную обработку команды /start
            await handle_text_message(update, context)
            return
        
        # Проверяем флаги ожидания ввода только если это не команда /start
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
        elif context.user_data.get('awaiting_direct_message'):
            await handle_direct_message_input(update, context)
            return

    # Обычная обработка сообщений
    await handle_text_message(update, context)

async def restore_users_from_activity_log(context: ContextTypes.DEFAULT_TYPE):
    """Автоматическое восстановление пользователей из логов активности при старте бота"""
    from .database import db
    import sqlite3

    try:
        # Проверяем количество пользователей в базе
        existing_users = db.get_all_users()
        existing_count = len(existing_users)

        # Если пользователей меньше 5, пытаемся восстановить из логов
        if existing_count < 5:
            logger.info(f"🔍 Обнаружено мало пользователей в базе ({existing_count}), запускаю восстановление из логов активности...")

            # Получаем все user_id из activity_log
            all_user_ids = db.get_all_known_user_ids(include_activity_log=True)
            existing_user_ids = {u['user_id'] for u in existing_users}
            users_to_add = [uid for uid in all_user_ids if uid not in existing_user_ids]

            if users_to_add:
                logger.info(f"📋 Найдено {len(users_to_add)} пользователей в логах для восстановления")

                # Получаем информацию из activity_log
                db_path = db.db_path
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                added_count = 0
                for user_id in users_to_add:
                    try:
                        # Пытаемся получить username из последней активности
                        cursor.execute('''
                            SELECT details
                            FROM activity_log
                            WHERE user_id = ?
                            ORDER BY timestamp DESC
                            LIMIT 1
                        ''', (user_id,))
                        row = cursor.fetchone()

                        username = None
                        if row and row['details']:
                            details = row['details']
                            if 'username=' in details:
                                try:
                                    username = details.split('username=')[1].split(',')[0].strip()
                                except:
                                    pass

                        # Добавляем пользователя
                        db.save_user(
                            user_id=user_id,
                            username=username,
                            first_name=None,
                            last_name=None,
                            default_query=None,
                            default_mode=None,
                            daily_notifications=False,
                            notification_time='21:00'
                        )
                        added_count += 1
                    except Exception as e:
                        logger.debug(f"Ошибка при восстановлении пользователя {user_id}: {e}")

                conn.close()

                if added_count > 0:
                    logger.info(f"✅ Восстановлено {added_count} пользователей из логов активности")
                else:
                    logger.info("ℹ️ Пользователи для восстановления не найдены")
            else:
                logger.info("ℹ️ Все пользователи из логов уже есть в базе данных")
        else:
            logger.debug(f"Пользователей в базе достаточно ({existing_count}), восстановление не требуется")
    except Exception as e:
        logger.warning(f"⚠️ Ошибка при восстановлении пользователей из логов: {e}")

async def initialize_active_users(context: ContextTypes.DEFAULT_TYPE):
    """Инициализирует список активных пользователей из БД при старте бота и восстанавливает задачи уведомлений"""
    from .database import db, DB_PATH
    from .constants import CTX_DEFAULT_QUERY, CTX_DEFAULT_MODE, CTX_DAILY_NOTIFICATIONS, CTX_NOTIFICATION_TIME
    from .jobs import daily_schedule_job
    from pathlib import Path

    # Проверяем базу данных при старте
    db_path = Path(DB_PATH)
    logger.info(f"📊 Проверка базы данных: {db_path}")
    logger.info(f"   Файл существует: {db_path.exists()}")
    if db_path.exists():
        size = db_path.stat().st_size
        logger.info(f"   Размер файла: {size / 1024:.2f} KB")

    # Получаем статистику по пользователям
    try:
        all_users = db.get_all_users()
        users_with_query = db.get_users_with_default_query()
        logger.info(f"📊 Статистика базы данных:")
        logger.info(f"   Всего пользователей в базе: {len(all_users)}")
        logger.info(f"   Пользователей с установленной группой/преподавателем: {len(users_with_query)}")

        if users_with_query:
            logger.info(f"   Список активных пользователей:")
            for user in users_with_query[:10]:  # Показываем первые 10
                logger.info(f"     - user_id={user['user_id']}, query={user.get('default_query')}, mode={user.get('default_mode')}")
            if len(users_with_query) > 10:
                logger.info(f"     ... и еще {len(users_with_query) - 10} пользователей")
    except Exception as e:
        logger.error(f"Ошибка при получении статистики: {e}", exc_info=True)

    # Сначала пытаемся восстановить пользователей из логов, если их мало
    await restore_users_from_activity_log(context)

    try:
        # Получаем пользователей с установленными группами/преподавателями
        users_with_query = db.get_users_with_default_query()
        logger.info(f"🔄 Инициализация активных пользователей: найдено {len(users_with_query)} пользователей с установленной группой/преподавателем")

        if 'active_users' not in context.bot_data:
            context.bot_data['active_users'] = set()
        if 'users_data_cache' not in context.bot_data:
            context.bot_data['users_data_cache'] = {}

        restored_jobs = 0
        for user_data in users_with_query:
            user_id = user_data['user_id']
            context.bot_data['active_users'].add(user_id)
            context.bot_data['users_data_cache'][user_id] = {
                CTX_DEFAULT_QUERY: user_data['default_query'],
                CTX_DEFAULT_MODE: user_data['default_mode'],
                CTX_DAILY_NOTIFICATIONS: bool(user_data.get('daily_notifications', False)),
                CTX_NOTIFICATION_TIME: user_data.get('notification_time', '21:00')
            }

            # Восстанавливаем задачи уведомлений для пользователей с включенными уведомлениями
            if user_data.get('daily_notifications', False) and user_data.get('default_query') and user_data.get('default_mode'):
                try:
                    time_str = user_data.get('notification_time', '21:00')
                    hour, minute = map(int, time_str.split(":"))
                    # МСК (UTC+3) -> UTC: вычитаем 3 часа
                    utc_hour = (hour - 3) % 24

                    job_name = f"daily_schedule_{user_id}"
                    job_data = {
                        "query": user_data['default_query'],
                        "mode": user_data['default_mode']
                    }

                    context.job_queue.run_daily(
                        daily_schedule_job,
                        time=time(utc_hour, minute, tzinfo=timezone.utc),
                        chat_id=user_id,
                        name=job_name,
                        data=job_data,
                    )
                    restored_jobs += 1
                    logger.debug(f"✅ Восстановлена задача уведомлений для пользователя {user_id} на {time_str} (UTC: {utc_hour:02d}:{minute:02d})")
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось восстановить задачу уведомлений для пользователя {user_id}: {e}")

        logger.info(f"✅ Инициализировано {len(context.bot_data['active_users'])} активных пользователей для проверки изменений расписания")
        if restored_jobs > 0:
            logger.info(f"✅ Восстановлено {restored_jobs} задач ежедневных уведомлений")
    except Exception as e:
        logger.error(f"Ошибка инициализации активных пользователей: {e}", exc_info=True)

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
    # Используем /data для сохранения данных между перезапусками (Docker)
    import os
    # Используем путь из конфига или переменную окружения
    pickle_path = os.getenv("BOT_DATA_PATH", BOT_DATA_PATH)
    persistence = PicklePersistence(filepath=pickle_path)

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
    from .admin.handlers import (
        admin_command,
        handle_maintenance_message_input,
        handle_admin_id_input,
        handle_remove_admin_id_input,
        handle_broadcast_input,
        handle_direct_message_input,
    )
    app.add_handler(CommandHandler("admin", admin_command))

    # Обработка текстовых сообщений (должен быть после команд, но команды уже обработаны)
    # Сначала проверяем админские команды
    from .admin.handlers import (
        handle_maintenance_message_input, handle_admin_id_input,
        handle_remove_admin_id_input, handle_broadcast_input, handle_user_search_input, handle_direct_message_input
    )
    from .admin.utils import is_admin

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

    # Добавляем задачу инициализации при старте (выполнится сразу после запуска)
    if app.job_queue:
        app.job_queue.run_once(initialize_active_users, when=0)

    return app

def main() -> None:
    if "YOUR_TOKEN" in TOKEN or len(TOKEN.split(":")[0]) < 8:
        logger.critical("Необходимо указать корректный токен бота!")
        return

    # Автоматическое добавление первого админа из конфига
    from .config import ADMIN_ID as config_admin_id

    # Используем значение из конфига (которое уже учитывает переменную окружения)
    if config_admin_id:
        try:
            admin_id = int(config_admin_id)
            # Проверяем, не добавлен ли уже этот админ
            if not admin_db.is_admin(admin_id):
                if admin_db.add_admin(admin_id, username=None, added_by="system_config"):
                    logger.info(f"✅ Администратор {admin_id} автоматически добавлен из конфигурации")
                else:
                    logger.warning(f"⚠️ Не удалось добавить администратора {admin_id} из конфигурации")
            else:
                logger.debug(f"Администратор {admin_id} уже существует")
        except ValueError:
            logger.warning(f"⚠️ Неверный формат ADMIN_ID в конфиге: {config_admin_id}. Должно быть число.")
    else:
        # Проверяем, есть ли хотя бы один админ
        admins = admin_db.get_all_admins()
        if not admins:
            logger.warning("⚠️ ВНИМАНИЕ: Нет ни одного администратора!")
            logger.warning("   Установите переменную окружения ADMIN_ID=<ваш_telegram_id> в панели Amvera")
            logger.warning("   Или пропишите ADMIN_ID в app/config.py")

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

if __name__ == "__main__":
    main()


