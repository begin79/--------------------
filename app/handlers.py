import datetime
import logging
import hashlib
import re
import asyncio
from dateutil.parser import parse as parse_date
from typing import Optional, Tuple
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, Message, InlineQueryResultArticle, InputTextMessageContent, InputMediaPhoto
from telegram.constants import ParseMode, ChatAction
from telegram.error import BadRequest, NetworkError, TimedOut, Forbidden
from telegram.ext import ContextTypes

from .constants import (
    CTX_MODE, CTX_SELECTED_DATE, CTX_AWAITING_MANUAL_DATE, CTX_LAST_QUERY, CTX_SCHEDULE_PAGES,
    CTX_CURRENT_PAGE_INDEX, CTX_AWAITING_DEFAULT_QUERY, CTX_DEFAULT_QUERY, CTX_DEFAULT_MODE,
    CTX_DAILY_NOTIFICATIONS, CTX_NOTIFICATION_TIME, CTX_IS_BUSY,
    CALLBACK_DATA_MODE_STUDENT, CALLBACK_DATA_MODE_TEACHER, CALLBACK_DATA_SETTINGS_MENU,
    CALLBACK_DATA_BACK_TO_START, CALLBACK_DATA_TOGGLE_DAILY,
    CALLBACK_DATA_CANCEL_INPUT, CALLBACK_DATA_DATE_TODAY, CALLBACK_DATA_DATE_TOMORROW,
    CALLBACK_DATA_PREV_SCHEDULE_PREFIX, CALLBACK_DATA_NEXT_SCHEDULE_PREFIX,
    CALLBACK_DATA_REFRESH_SCHEDULE_PREFIX,
    CALLBACK_DATA_EXPORT_WEEK_IMAGE, CALLBACK_DATA_EXPORT_WEEK_FILE, CALLBACK_DATA_EXPORT_MENU,
    CALLBACK_DATA_EXPORT_DAYS_IMAGES,
    API_TYPE_GROUP, API_TYPE_TEACHER, GROUP_NAME_PATTERN, CallbackData,
)
from .utils import escape_html
from .schedule import get_schedule, search_entities
from .database import db
from .admin.utils import is_bot_enabled, get_maintenance_message
from .admin.handlers import (
    CALLBACK_ADMIN_MESSAGE_USER_PREFIX,
    CALLBACK_ADMIN_USER_DETAILS_PREFIX,
    CALLBACK_USER_REPLY_ADMIN_PREFIX,
    CALLBACK_USER_DISMISS_ADMIN_PREFIX,
)

logger = logging.getLogger(__name__)

# Вспомогательные функции
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
            logger.debug(f"Callback query истек: {e}")  # Изменено с warning на debug
            return False
        else:
            logger.debug(f"Ошибка при ответе на callback query: {e}")  # Изменено с error на debug
            return False
    except (NetworkError, TimedOut) as e:
        logger.debug(f"Сетевая ошибка при ответе на callback query: {e}")
        return False
    except Exception as e:
        logger.debug(f"Неожиданная ошибка при ответе на callback query: {e}")  # Изменено с error на debug
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
                logger.debug(f"Ошибка при отправке нового сообщения: {reply_error}")
                return False
        else:
            logger.debug(f"Ошибка при редактировании сообщения: {e}")
            return False
    except (NetworkError, TimedOut) as e:
        logger.debug(f"Сетевая ошибка при редактировании сообщения: {e}")
        return False
    except Exception as e:
        logger.debug(f"Неожиданная ошибка при редактировании сообщения: {e}")
        return False

def check_user_busy(user_data: dict) -> bool:
    """Проверяет, занят ли пользователь обработкой запроса"""
    return user_data.get(CTX_IS_BUSY, False)

def set_user_busy(user_data: dict, busy: bool = True):
    """Устанавливает флаг занятости пользователя"""
    if busy:
        user_data[CTX_IS_BUSY] = True
    else:
        user_data.pop(CTX_IS_BUSY, None)


def _get_admin_dialog_storage(context: ContextTypes.DEFAULT_TYPE) -> dict:
    """Возвращает словарь активных диалогов админ ↔ пользователь"""
    return context.application.bot_data.setdefault("admin_dialogs", {})


def _schedule_daily_notifications(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_data: dict):
    """Перенастраивает ежедневное уведомление согласно текущим настройкам пользователя"""
    if not context.job_queue or not chat_id:
        return

    job_name = f"daily_schedule_{chat_id}"
    for job in context.job_queue.get_jobs_by_name(job_name):
        try:
            job.schedule_removal()
        except Exception:
            pass

    query = user_data.get(CTX_DEFAULT_QUERY)
    mode = user_data.get(CTX_DEFAULT_MODE)
    if not query or not mode:
        return

    time_str = user_data.get(CTX_NOTIFICATION_TIME, "21:00") or "21:00"
    try:
        hour, minute = map(int, time_str.split(":"))
    except ValueError:
        hour, minute = 21, 0
        time_str = "21:00"
        user_data[CTX_NOTIFICATION_TIME] = time_str

    utc_hour = (hour - 3) % 24
    job_data = {"query": query, "mode": mode}
    context.job_queue.run_daily(
        __import__("app.jobs").jobs.daily_schedule_job,
        time=datetime.time(utc_hour, minute, tzinfo=datetime.timezone.utc),
        chat_id=chat_id,
        name=job_name,
        data=job_data,
    )


async def _apply_default_selection(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chosen: str,
    mode: str,
    source: str = "message",
):
    """Финализирует установку расписания по умолчанию и включает уведомления"""
    user_data = context.user_data
    user_id = update.effective_user.id if update.effective_user else None
    username = update.effective_user.username if update.effective_user else None
    first_name = update.effective_user.first_name if update.effective_user else None
    last_name = update.effective_user.last_name if update.effective_user else None

    user_data[CTX_DEFAULT_QUERY] = chosen
    user_data[CTX_DEFAULT_MODE] = mode
    if not user_data.get(CTX_NOTIFICATION_TIME):
        user_data[CTX_NOTIFICATION_TIME] = "21:00"

    notifications_were_enabled = bool(user_data.get(CTX_DAILY_NOTIFICATIONS, False))
    user_data[CTX_DAILY_NOTIFICATIONS] = True

    save_user_data_to_db(
        user_id=user_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        user_data=user_data,
    )
    if user_id:
        db.log_activity(user_id, "set_default_query", f"mode={mode}, query={chosen}")
        if not notifications_were_enabled:
            db.log_activity(user_id, "auto_enable_notifications", f"mode={mode}")

    chat_id = update.effective_chat.id if update.effective_chat else user_id
    _schedule_daily_notifications(context, chat_id, user_data)

    # Добавляем пользователя в список активных для проверки изменений расписания
    if user_id:
        if 'active_users' not in context.bot_data:
            context.bot_data['active_users'] = set()
        if 'users_data_cache' not in context.bot_data:
            context.bot_data['users_data_cache'] = {}

        context.bot_data['active_users'].add(user_id)
        # Обновляем кеш данных пользователя для проверки изменений
        context.bot_data['users_data_cache'][user_id] = {
            CTX_DEFAULT_QUERY: chosen,
            CTX_DEFAULT_MODE: mode,
            CTX_DAILY_NOTIFICATIONS: True,
            CTX_NOTIFICATION_TIME: user_data.get(CTX_NOTIFICATION_TIME, "21:00")
        }

    time_str = user_data.get(CTX_NOTIFICATION_TIME, "21:00")
    notif_line = (
        f"🔔 Ежедневные уведомления уже были включены на {time_str}."
        if notifications_were_enabled
        else f"🔔 Ежедневные уведомления автоматически включены на {time_str}."
    )
    reply_keyboard = get_default_reply_keyboard()
    info_text = (
        f"✅ Установлено по умолчанию: <b>{escape_html(chosen)}</b>\n"
        f"{notif_line}"
    )

    if source == "message" and update.message:
        await update.message.reply_text(
            info_text,
            reply_markup=reply_keyboard,
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.effective_chat.send_message(
            info_text,
            reply_markup=reply_keyboard,
            parse_mode=ParseMode.HTML,
        )


async def start_user_reply_to_admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    admin_id: int,
):
    """Подготовить пользователя к отправке ответа администратору"""
    user_data = context.user_data
    user_id = update.effective_user.id if update.effective_user else None
    user_data["pending_admin_reply"] = admin_id

    dialogs = _get_admin_dialog_storage(context)
    if user_id is not None:
        entry = dialogs.get(user_id, {})
        entry.update({"admin_id": admin_id, "last_prompt_at": datetime.datetime.utcnow().isoformat()})
        dialogs[user_id] = entry

    try:
        await update.callback_query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

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
    if user_data.get("pending_admin_reply") == admin_id:
        user_data.pop("pending_admin_reply", None)

    user_id = update.effective_user.id if update.effective_user else None
    dialogs = _get_admin_dialog_storage(context)
    if user_id is not None:
        dialogs.pop(user_id, None)

    try:
        await update.callback_query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

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

    dialogs = _get_admin_dialog_storage(context)
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

async def safe_get_schedule(date: str, query: str, api_type: str, timeout: float = 15.0):
    """Безопасное получение расписания с таймаутом (оптимизировано для быстрых ответов)"""
    try:
        return await asyncio.wait_for(
            get_schedule(date, query, api_type),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        logger.warning(f"Таймаут при получении расписания для {query} на {date}")
        return None, "Превышено время ожидания ответа от сервера. Попробуйте позже."
    except Exception as e:
        logger.error(f"Ошибка при получении расписания: {e}", exc_info=True)
        return None, f"Ошибка при получении расписания: {str(e)}"

def load_user_data_from_db(user_id: int, user_data: dict):
    """Загружает данные пользователя из БД в user_data"""
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
        logger.error(f"Ошибка загрузки данных пользователя {user_id} из БД: {e}")

def save_user_data_to_db(user_id: int, username: Optional[str], first_name: Optional[str],
                         last_name: Optional[str], user_data: dict):
    """Сохраняет данные пользователя из user_data в БД"""
    try:
        db.save_user(
            user_id=user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            default_query=user_data.get(CTX_DEFAULT_QUERY),
            default_mode=user_data.get(CTX_DEFAULT_MODE),
            daily_notifications=user_data.get(CTX_DAILY_NOTIFICATIONS, False),
            notification_time=user_data.get(CTX_NOTIFICATION_TIME, '21:00')
        )
        logger.debug(f"Данные пользователя {user_id} сохранены в БД")
    except Exception as e:
        logger.error(f"Ошибка сохранения данных пользователя {user_id} в БД: {e}")

def detect_query_type(text: str) -> Optional[Tuple[str, str]]:
    """
    Определяет тип запроса (группа/преподаватель) по тексту
    Возвращает (mode, text) или None
    """
    text = text.strip()

    # Проверяем, похоже ли на название группы
    if re.match(GROUP_NAME_PATTERN, text, re.IGNORECASE):
        return ("student", text)

    # Проверяем, похоже ли на ФИО преподавателя (два слова с заглавной буквы)
    words = text.split()
    if len(words) >= 2 and all(word[0].isupper() for word in words if word):
        # Может быть преподаватель
        return ("teacher", text)

    return None

def get_default_reply_keyboard() -> ReplyKeyboardMarkup:
    """Создает стандартную клавиатуру с кнопками 'Старт' и 'Меню'"""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("Старт"), KeyboardButton("Меню")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )

async def _delete_message_after_delay(bot, chat_id: int, message_id: int, delay: float):
    """Удаляет сообщение через указанную задержку"""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass  # Игнорируем ошибки при удалении

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        logger.error("start_command вызван без effective_user")
        return

    # Проверяем статус бота (с обработкой ошибок, чтобы не блокировать работу при проблемах с БД)
    try:
        if not is_bot_enabled():
            maintenance_msg = get_maintenance_message()
            try:
                if update.message:
                    await update.message.reply_text(maintenance_msg)
                elif update.callback_query:
                    await safe_edit_message_text(update.callback_query, maintenance_msg)
            except Exception as e:
                logger.warning(f"Не удалось отправить сообщение о техническом обслуживании: {e}")
            return
    except Exception as e:
        logger.warning(f"Ошибка при проверке статуса бота, продолжаем работу: {e}")
        # Продолжаем работу, если не удалось проверить статус

    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    first_name = update.effective_user.first_name or "без имени"
    last_name = update.effective_user.last_name
    logger.info(f"👤 [{user_id}] @{username} ({first_name}) → Команда /start")

    # Проверяем, новый ли это пользователь (первый запуск) - проверяем ДО сохранения
    user_db_before_save = db.get_user(user_id)
    is_first_time = user_db_before_save is None

    # Загружаем данные из БД
    load_user_data_from_db(user_id, context.user_data)

    # Очищаем временные ключи
    temp_keys = [CTX_MODE, CTX_SELECTED_DATE, CTX_AWAITING_MANUAL_DATE, CTX_LAST_QUERY,
                 CTX_SCHEDULE_PAGES, CTX_CURRENT_PAGE_INDEX, CTX_AWAITING_DEFAULT_QUERY, CTX_IS_BUSY]
    for key in temp_keys:
        context.user_data.pop(key, None)

    # Сохраняем информацию о пользователе в БД
    save_user_data_to_db(user_id, username, first_name, last_name, context.user_data)

    # Обновляем кеш активных пользователей, если у пользователя есть установленная группа/преподаватель
    default_query = context.user_data.get(CTX_DEFAULT_QUERY)
    default_mode = context.user_data.get(CTX_DEFAULT_MODE)
    if default_query and default_mode:
        if 'active_users' not in context.bot_data:
            context.bot_data['active_users'] = set()
        if 'users_data_cache' not in context.bot_data:
            context.bot_data['users_data_cache'] = {}

        context.bot_data['active_users'].add(user_id)
        context.bot_data['users_data_cache'][user_id] = {
            CTX_DEFAULT_QUERY: default_query,
            CTX_DEFAULT_MODE: default_mode,
            CTX_DAILY_NOTIFICATIONS: context.user_data.get(CTX_DAILY_NOTIFICATIONS, False),
            CTX_NOTIFICATION_TIME: context.user_data.get(CTX_NOTIFICATION_TIME, '21:00')
        }

    # Логируем активность
    db.log_activity(user_id, "start_command", f"username={username}")

    # Проверяем, есть ли у пользователя установленное расписание по умолчанию
    default_query = context.user_data.get(CTX_DEFAULT_QUERY)
    default_mode = context.user_data.get(CTX_DEFAULT_MODE)

    # Для новых пользователей без установленной группы показываем выбор режима
    if is_first_time and not default_query:
        text = "👋 Привет! Я бот для получения расписания ВГЛТУ 📅\n\n"
        text += "Кто вы?"

        keyboard_rows = [
            [InlineKeyboardButton("🎓 Студент", callback_data=CALLBACK_DATA_MODE_STUDENT)],
            [InlineKeyboardButton("🧑‍🏫 Преподаватель", callback_data=CALLBACK_DATA_MODE_TEACHER)]
        ]
    else:
        text = "👋 Привет! Я бот для получения расписания ВГЛТУ 📅\n\n"
        keyboard_rows = []

        # Если есть расписание по умолчанию, показываем быстрый доступ
        if default_query and default_mode:
            text += f"📌 Ваше расписание: <b>{escape_html(default_query)}</b>\n\n"
            # Быстрые кнопки для расписания по умолчанию
            keyboard_rows.append([
                InlineKeyboardButton("📅 Сегодня", callback_data=f"{CALLBACK_DATA_DATE_TODAY}_quick_{default_mode}"),
                InlineKeyboardButton("📅 Завтра", callback_data=f"{CALLBACK_DATA_DATE_TOMORROW}_quick_{default_mode}")
            ])
            keyboard_rows.append([
                InlineKeyboardButton(
                    f"📋 Все расписание ({default_query[:18]}{'...' if len(default_query) > 18 else ''})",
                    callback_data=f"quick_schedule_{default_mode}"
                )
            ])
            keyboard_rows.append([])  # Пустая строка для разделения

        text += "Выберите режим или перейдите в настройки:"

        keyboard_rows.extend([
            [InlineKeyboardButton("🎓 Студента", callback_data=CALLBACK_DATA_MODE_STUDENT)],
            [InlineKeyboardButton("🧑‍🏫 Преподавателя", callback_data=CALLBACK_DATA_MODE_TEACHER)],
            [InlineKeyboardButton("⚙️ Настройки", callback_data=CALLBACK_DATA_SETTINGS_MENU)],
            [InlineKeyboardButton("ℹ️ Помощь", callback_data=CallbackData.HELP_COMMAND_INLINE.value)]
        ])

    keyboard = InlineKeyboardMarkup(keyboard_rows)

    # Устанавливаем стандартную клавиатуру для всех сообщений
    reply_keyboard = get_default_reply_keyboard()

    if update.message:
        # Устанавливаем клавиатуру в основном сообщении с обработкой сетевых ошибок
        max_retries = 3
        for attempt in range(max_retries):
            try:
                await update.message.reply_text(
                    text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )
                break  # Успешно отправлено
            except (NetworkError, TimedOut) as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Экспоненциальная задержка: 1, 2, 4 секунды
                    logger.warning(f"⚠️ [{user_id}] Сетевая ошибка при отправке /start (попытка {attempt + 1}/{max_retries}): {e}. Повтор через {wait_time} сек.")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"❌ [{user_id}] Не удалось отправить /start после {max_retries} попыток: {e}")
                    # Пытаемся отправить хотя бы простое сообщение без форматирования
                    try:
                        await update.message.reply_text(
                            "👋 Привет! Я бот для получения расписания ВГЛТУ 📅\n\nВыберите режим:",
                            reply_markup=keyboard
                        )
                    except Exception as final_error:
                        logger.error(f"❌ [{user_id}] Критическая ошибка при отправке сообщения: {final_error}")
            except Exception as e:
                logger.error(f"❌ [{user_id}] Неожиданная ошибка при отправке /start: {e}", exc_info=True)
                break  # Для других ошибок не повторяем

        # Устанавливаем ReplyKeyboardMarkup только для новых пользователей с подсказкой
        if is_first_time:
            # Для новых пользователей показываем подсказку и удаляем через 5 секунд
            try:
                help_msg = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="💡 Используйте кнопки ниже для быстрой навигации",
                    reply_markup=reply_keyboard
                )
                # Удаляем сообщение через 5 секунд
                asyncio.create_task(_delete_message_after_delay(context.bot, help_msg.chat_id, help_msg.message_id, 5.0))
            except Exception as e:
                logger.debug(f"Не удалось установить клавиатуру: {e}")
        # Для существующих пользователей клавиатура устанавливается при следующем ответе бота (через reply_markup)
    elif update.callback_query:
        if not await safe_edit_message_text(update.callback_query, text, reply_markup=keyboard, parse_mode=ParseMode.HTML):
            # Если редактирование не удалось, пытаемся отправить новое сообщение
            try:
                await update.callback_query.message.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.debug(f"Не удалось отправить новое сообщение: {e}")

async def help_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    logger.info(f"👤 [{user_id}] @{username} → Команда /help")

    text = (
        "<b>ℹ️ Справка по боту:</b>\n\n"
        "🔹 <b>/start</b> - Главное меню.\n"
        "🔹 <b>/settings</b> - Настройки уведомлений и группы по умолчанию.\n"
        "🔹 <b>/help</b> - Эта справка.\n\n"
        "<b>📱 Inline режим:</b>\n"
        "Используйте бота в любом чате! Просто начните вводить:\n"
        "<code>@Vgltu25_bot группа</code> или <code>@Vgltu25_bot препод</code>\n\n"
        "Примеры:\n"
        "• <code>@Vgltu25_bot ИС1-227</code> - поиск группы\n"
        "• <code>@Vgltu25_bot п Иванов</code> - поиск преподавателя\n"
        "• <code>@Vgltu25_bot г ИС1</code> - поиск группы (с префиксом)\n\n"
        "Выберите нужный вариант из списка, и расписание отправится в чат!"
    )
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В начало", callback_data=CALLBACK_DATA_BACK_TO_START)]])
    if update.callback_query:
        if not await safe_edit_message_text(update.callback_query, text, reply_markup=reply_markup, parse_mode=ParseMode.HTML):
            try:
                await update.callback_query.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            except Exception:
                pass
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

async def settings_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        logger.error("settings_menu_callback вызван без effective_user")
        return

    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    source = "команда /settings" if update.message else "callback"
    logger.info(f"👤 [{user_id}] @{username} → Открыл настройки ({source})")

    user_data = context.user_data

    # Перед загрузкой из БД очищаем устаревшие значения
    for key in [CTX_DEFAULT_QUERY, CTX_DEFAULT_MODE, CTX_DAILY_NOTIFICATIONS, CTX_NOTIFICATION_TIME]:
        user_data.pop(key, None)

    # Загружаем актуальные данные из БД
    load_user_data_from_db(user_id, user_data)

    query = user_data.get(CTX_DEFAULT_QUERY, "Не задано")
    is_daily = user_data.get(CTX_DAILY_NOTIFICATIONS, False)
    notification_time = user_data.get(CTX_NOTIFICATION_TIME, "21:00")
    logger.info(f"📊 [{user_id}] Текущие настройки: группа/преподаватель='{query}', уведомления={'вкл' if is_daily else 'выкл'}, время={notification_time}")
    text = f"<b>⚙️ Настройки</b>\n\nТекущая группа/преподаватель:\n<code>{escape_html(query)}</code>\n\nВремя уведомлений: <code>{notification_time}</code>"
    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("Установить/изменить группу", callback_data="set_default_mode_student")],
        [InlineKeyboardButton("Установить/изменить преподавателя", callback_data="set_default_mode_teacher")],
        [InlineKeyboardButton(f"{'✅' if is_daily else '❌'} Ежедневные уведомления", callback_data=CALLBACK_DATA_TOGGLE_DAILY)],
        [InlineKeyboardButton("⏰ Изменить время уведомлений", callback_data="set_notification_time")],
        [InlineKeyboardButton("♻️ Сбросить настройки", callback_data="reset_settings")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_DATA_BACK_TO_START)]
    ])
    try:
        if update.callback_query:
            if not await safe_edit_message_text(update.callback_query, text, reply_markup=kbd, parse_mode=ParseMode.HTML):
                try:
                    await update.callback_query.message.reply_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
                except Exception:
                    pass
        else:
            await update.effective_message.reply_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logger.info("Меню настроек не изменилось.")
        else:
            logger.error(f"Не удалось обновить меню настроек: {e}")

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        logger.error("handle_text_message вызван без effective_user или message")
        return

    user_data = context.user_data
    user_id = update.effective_user.id

    # Проверяем статус бота (кроме админов)
    from .admin.utils import is_admin
    if not is_admin(user_id) and not is_bot_enabled():
        maintenance_msg = get_maintenance_message()
        await update.message.reply_text(maintenance_msg)
        return

    username = update.effective_user.username or "без username"
    first_name = update.effective_user.first_name or "без имени"
    text = update.message.text.strip()

    logger.info(f"💬 [{user_id}] @{username} ({first_name}) → Текстовое сообщение: '{text[:50]}{'...' if len(text) > 50 else ''}'")

    pending_admin_id = user_data.get("pending_admin_reply")
    if pending_admin_id:
        lowered = text.lower()
        if lowered in {"отмена", "cancel", "/cancel"}:
            user_data.pop("pending_admin_reply", None)
            await update.message.reply_text("✅ Ответ администратору отменён.")
        else:
            await process_user_reply_to_admin_message(update, context, pending_admin_id, text)
        return

    # Проверяем, не занят ли пользователь
    if check_user_busy(user_data):
        await update.message.reply_text("⏳ Пожалуйста, подождите, я обрабатываю предыдущий запрос...")
        return

    # Команда /start или "Старт" обрабатывается CommandHandler, но на случай если пришла как текст
    if text == "/start" or text.startswith("/start") or text.strip().lower() == "старт":
        await start_command(update, context)
        return

    # Обработка кнопки "Меню"
    if text.strip().lower() == "меню":
        await start_command(update, context)
        return

    # Загружаем данные из БД при первом обращении
    if not user_data.get(CTX_DEFAULT_QUERY):
        load_user_data_from_db(user_id, user_data)

    # Умный холодный старт: если режим не выбран, пытаемся определить по тексту
    if not user_data.get(CTX_MODE) and not user_data.get(CTX_AWAITING_DEFAULT_QUERY) and not user_data.get(CTX_AWAITING_MANUAL_DATE):
        detected = detect_query_type(text)
        if detected:
            mode, query_text = detected
            mode_text = "группу" if mode == "student" else "преподавателя"
            user_data[CTX_MODE] = mode

            # Предлагаем пользователю подтвердить выбор
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Да, это правильный режим", callback_data=f"confirm_mode_{mode}_{hashlib.md5(query_text.encode()).hexdigest()[:8]}"),
                    InlineKeyboardButton("❌ Нет, выбрать другой", callback_data=CALLBACK_DATA_BACK_TO_START)
                ]
            ])
            user_data[f"pending_query_{mode}"] = query_text
            await update.message.reply_text(
                f"🔍 Я определил, что вы ищете {mode_text}: <b>{escape_html(query_text)}</b>\n\n"
                f"Правильно?",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
            return
        else:
            # Не удалось определить, предлагаем выбрать режим
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎓 Я студент", callback_data=CALLBACK_DATA_MODE_STUDENT)],
                [InlineKeyboardButton("🧑‍🏫 Я преподаватель", callback_data=CALLBACK_DATA_MODE_TEACHER)],
                [InlineKeyboardButton("❓ Не знаю", callback_data=CallbackData.HELP_COMMAND_INLINE.value)]
            ])
            await update.message.reply_text(
                "🤔 Я не могу определить, что вы ищете. Пожалуйста, выберите режим:",
                reply_markup=keyboard
            )
            return

    if user_data.get(CTX_AWAITING_DEFAULT_QUERY):
        await handle_default_query_input(update, context, text)
    elif user_data.get(CTX_AWAITING_MANUAL_DATE):
        await handle_manual_date_input(update, context, text)
    else:
        await handle_schedule_search(update, context, text)

async def handle_default_query_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    if not update.effective_user:
        logger.error("handle_default_query_input вызван без effective_user")
        return

    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    user_data = context.user_data

    # Устанавливаем блокировку
    set_user_busy(user_data, True)

    try:
        mode = user_data[CTX_MODE]
        mode_text = "группу" if mode == "student" else "преподавателя"
        logger.info(f"⚙️ [{user_id}] @{username} → Устанавливает {mode_text} по умолчанию: '{text}'")

        api_type = API_TYPE_GROUP if mode == "student" else API_TYPE_TEACHER
        found, err = await search_entities(text, api_type)

        if found:
            logger.info(f"✅ [{user_id}] Найдено {len(found)} вариантов для '{text}'")
        else:
            logger.warning(f"❌ [{user_id}] Не найдено вариантов для '{text}': {err}")

        if err or not found:
            kbd = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_DATA_SETTINGS_MENU)]])
            await update.message.reply_text("Не удалось найти. Попробуйте еще раз.", reply_markup=kbd)
            return

        match = next((e for e in found if e.lower() == text.lower()), None)
        if match:
            logger.info(f"✅ [{user_id}] @{username} → Установлено по умолчанию: '{match}' (режим: {mode_text})")
            user_data.pop(CTX_AWAITING_DEFAULT_QUERY, None)

            # Проверяем, новый ли это пользователь (первый запуск)
            is_new_user = user_data.get(CTX_DEFAULT_QUERY) is None

            await _apply_default_selection(update, context, match, mode, source="message")

            if is_new_user:
                # Для новых пользователей показываем сообщение об успешной установке и главное меню
                success_msg = await update.message.reply_text(
                    f"✅ Вы установили {mode_text}: <b>{escape_html(match)}</b>",
                    parse_mode=ParseMode.HTML
                )
                # Удаляем сообщение через 3 секунды
                asyncio.create_task(_delete_message_after_delay(context.bot, success_msg.chat_id, success_msg.message_id, 3.0))
                # Показываем главное меню
                await start_command(update, context)
            else:
                await settings_menu_callback(update, context)
            return

        # Если точного совпадения нет, предлагаем варианты на выбор кнопками (без текстового списка)
        max_options = 30
        options = found[:max_options]
        user_data[f"default_options_{mode}"] = options

        # Формируем клавиатуру сеткой по 3 в ряд
        rows = []
        row = []
        for idx, option in enumerate(options):
            row.append(InlineKeyboardButton(option, callback_data=f"choose_default_{mode}_{idx}"))
            if len(row) == 3:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_DATA_SETTINGS_MENU)])

        await update.message.reply_text(
            "🔎 Нашёл несколько вариантов. Выберите из списка ниже:",
            reply_markup=InlineKeyboardMarkup(rows)
        )
    finally:
        # Снимаем блокировку
        set_user_busy(user_data, False)

async def handle_manual_date_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_data = context.user_data
    # Устанавливаем стандартную клавиатуру
    reply_keyboard = get_default_reply_keyboard()
    try:
        date_obj = parse_date(text, dayfirst=True).date()
        user_data[CTX_SELECTED_DATE] = date_obj.strftime("%Y-%m-%d")
        user_data.pop(CTX_AWAITING_MANUAL_DATE)
        await update.message.reply_text(f"📅 Дата установлена: {date_obj.strftime('%d.%m.%Y')}.", reply_markup=reply_keyboard)
        if user_data.get(CTX_MODE) and user_data.get(CTX_LAST_QUERY):
            msg = await update.message.reply_text("Обновляю расписание...")
            await fetch_and_display_schedule(update, context, user_data[CTX_LAST_QUERY], msg_to_edit=msg)
    except (ValueError, TypeError):
        kbd = InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data=CALLBACK_DATA_CANCEL_INPUT)]])
        await update.message.reply_text("Не могу распознать дату. Попробуйте формат ДД.ММ.ГГГГ или ГГГГ-ММ-ДД.", reply_markup=kbd)

async def handle_schedule_search(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    if not update.effective_user:
        logger.error("handle_schedule_search вызван без effective_user")
        return

    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    user_data = context.user_data

    # Устанавливаем блокировку
    set_user_busy(user_data, True)

    try:
        if not user_data.get(CTX_MODE):
            logger.warning(f"⚠️ [{user_id}] @{username} → Попытка поиска без выбора режима")
            await update.message.reply_text("Сначала выберите режим через /start.")
            return

        mode = user_data[CTX_MODE]
        mode_text = "группу" if mode == "student" else "преподавателя"
        logger.info(f"🔍 [{user_id}] @{username} → Ищет {mode_text}: '{text}'")

        await update.message.reply_chat_action(ChatAction.TYPING)
        api_type = API_TYPE_GROUP if mode == "student" else API_TYPE_TEACHER
        p_name, s_name, verb, not_found = ("группы", "группа", "Найдена", "Группы не найдены.") if mode == 'student' else ("преподаватели", "преподаватель", "Найден", "Преподаватели не найдены.")

        found, err = await search_entities(text, api_type)

        if found:
            logger.info(f"✅ [{user_id}] Найдено {len(found)} {p_name} для запроса '{text}'")
            if len(found) == 1:
                logger.info(f"📅 [{user_id}] Загружаю расписание для: {found[0]}")
        else:
            logger.warning(f"❌ [{user_id}] {not_found} для запроса '{text}': {err}")

        if err or not found:
            suggestion = "Попробуйте ввести более точное название или хотя бы первые 3-4 буквы."
            # Устанавливаем стандартную клавиатуру
            reply_keyboard = get_default_reply_keyboard()
            await update.message.reply_text(err or f"{not_found} {suggestion}", reply_markup=reply_keyboard)
            return

        # Устанавливаем стандартную клавиатуру
        reply_keyboard = get_default_reply_keyboard()

        if len(found) == 1:
            await update.message.reply_text(
                f"{verb} {s_name}: {found[0]}.\nЗагружаю...",
                reply_markup=reply_keyboard
            )
            await fetch_and_display_schedule(update, context, found[0])
        else:
            kbd = [[KeyboardButton(e)] for e in found[:20]]
            msg = f"Найдено несколько {p_name}. Выберите вариант:" if len(found) <= 20 else f"Найдено слишком много ({len(found)}). Показаны первые 20:"
            await update.message.reply_text(
                msg,
                reply_markup=ReplyKeyboardMarkup(kbd, resize_keyboard=True, one_time_keyboard=True)
            )
    finally:
        # Снимаем блокировку
        set_user_busy(user_data, False)

async def fetch_and_display_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str, msg_to_edit: Optional[Message] = None):
    if not update.effective_user:
        logger.error("fetch_and_display_schedule вызван без effective_user")
        return

    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    user_data = context.user_data

    # Устанавливаем блокировку
    set_user_busy(user_data, True)

    try:
        mode = user_data.get(CTX_MODE)
        api_type = API_TYPE_GROUP if mode == "student" else API_TYPE_TEACHER
        date = user_data.setdefault(CTX_SELECTED_DATE, datetime.date.today().strftime("%Y-%m-%d"))
        user_data[CTX_LAST_QUERY] = query

        mode_text = "группы" if mode == "student" else "преподавателя"
        logger.debug(f"📥 [{user_id}] @{username} → Загружаю расписание {mode_text} '{query}' на {date}")

        pages, err = await safe_get_schedule(date, query, api_type)

        if pages:
            logger.debug(f"✅ [{user_id}] Получено расписание: {len(pages)} страниц")
        else:
            logger.warning(f"❌ [{user_id}] Ошибка получения расписания: {err}")

        if err or not pages:
            reply_keyboard = get_default_reply_keyboard()
            target = msg_to_edit or update.effective_message
            if target:
                await target.reply_text(err or "Не удалось получить расписание.", reply_markup=reply_keyboard)
            return

        if "Расписание не найдено" in pages[0]:
            kbd = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В начало", callback_data=CALLBACK_DATA_BACK_TO_START)]])
            target = msg_to_edit or (update.callback_query and update.callback_query.message)
            if target:
                try:
                    await target.edit_text(pages[0], reply_markup=kbd)
                except BadRequest as e:
                    if "no text in the message" in str(e).lower():
                        # Сообщение содержит фото/документ, отправляем новое
                        await target.reply_text(pages[0], reply_markup=kbd)
                    else:
                        raise
            else:
                await update.effective_message.reply_text(pages[0], reply_markup=kbd)
            return

        user_data[CTX_SCHEDULE_PAGES], user_data[CTX_CURRENT_PAGE_INDEX] = pages, 0
        await send_schedule_with_pagination(update, context, msg_to_edit=msg_to_edit)

        # Логируем активность
        db.log_activity(user_id, "view_schedule", f"mode={mode}, query={query}, date={date}")
    finally:
        # Снимаем блокировку
        set_user_busy(user_data, False)

async def send_schedule_with_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE, msg_to_edit: Optional[Message] = None):
    user_data = context.user_data
    pages, idx, mode, query = user_data.get(CTX_SCHEDULE_PAGES), user_data.get(CTX_CURRENT_PAGE_INDEX, 0), user_data.get(CTX_MODE), user_data.get(CTX_LAST_QUERY)

    # Проверяем, что есть страницы и запрос
    if not pages or len(pages) == 0:
        logger.warning("Нет страниц для отображения")
        kbd = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В начало", callback_data=CALLBACK_DATA_BACK_TO_START)]])
        target = msg_to_edit or (update.callback_query and update.callback_query.message) or update.effective_message
        if target:
            await target.reply_text("Расписание не найдено.", reply_markup=kbd)
        return

    if not query:
        logger.warning("Нет запроса для отображения")
        kbd = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В начало", callback_data=CALLBACK_DATA_BACK_TO_START)]])
        target = msg_to_edit or (update.callback_query and update.callback_query.message) or update.effective_message
        if target:
            await target.reply_text("Запрос не найден.", reply_markup=kbd)
        return

    # Проверяем mode
    if not mode:
        mode = "student"  # Значение по умолчанию
        user_data[CTX_MODE] = mode

    # Проверяем индекс страницы
    if idx < 0:
        idx = 0
    if idx >= len(pages):
        idx = len(pages) - 1
    user_data[CTX_CURRENT_PAGE_INDEX] = idx

    # Логирование только если есть update с пользователем
    if update.effective_user:
        user_id = update.effective_user.id
        username = update.effective_user.username or "без username"
        logger.debug(f"📋 [{user_id}] @{username} → Отображение расписания '{query}' (страница {idx + 1}/{len(pages)})")  # Изменено с INFO на DEBUG

    entity = "группы" if mode == "student" else "преподавателя"
    text = f"Расписание для {entity}: <b>{escape_html(query)}</b>\n📅 Стр. {idx + 1}/{len(pages)}:\n\n{pages[idx]}"

    # Создаем кнопки навигации - ВСЕГДА показываем кнопки, если страниц больше одной
    kbd_row = []

    # Логируем состояние для диагностики
    logger.debug(f"Создание кнопок навигации: idx={idx}, len(pages)={len(pages)}, mode={mode}")

    # Первая строка: навигация по страницам
    nav_row = []
    if idx > 0:
        prev_callback = f"{CALLBACK_DATA_PREV_SCHEDULE_PREFIX}{mode}_{idx-1}"
        nav_row.append(InlineKeyboardButton("⬅️ Назад", callback_data=prev_callback))

    refresh_callback = f"{CALLBACK_DATA_REFRESH_SCHEDULE_PREFIX}{mode}_{idx}"
    nav_row.append(InlineKeyboardButton("🔄 Обновить", callback_data=refresh_callback))

    if idx < len(pages) - 1:
        next_callback = f"{CALLBACK_DATA_NEXT_SCHEDULE_PREFIX}{mode}_{idx+1}"
        nav_row.append(InlineKeyboardButton("Вперед ➡️", callback_data=next_callback))

    kbd_rows = [nav_row] if nav_row else []

    # Вторая строка: экспорт
    if query:
        query_hash = hashlib.md5(query.encode('utf-8')).hexdigest()[:12]
        user_data[f"export_{mode}_{query_hash}"] = query
        kbd_rows.append([InlineKeyboardButton("📤 Экспорт", callback_data=f"{CALLBACK_DATA_EXPORT_MENU}_{mode}_{query_hash}")])

    # Последняя строка: возврат в начало
    kbd_rows.append([InlineKeyboardButton("🏠 В начало", callback_data=CALLBACK_DATA_BACK_TO_START)])
    kbd = InlineKeyboardMarkup(kbd_rows)

    # Логируем созданную клавиатуру для диагностики
    logger.debug(f"✅ Создана клавиатура с {len(kbd_rows)} строками: {[len(row) for row in kbd_rows]} кнопок в каждой")
    if nav_row:
        logger.debug(f"   Первая строка содержит {len(nav_row)} кнопок: {[btn.text for btn in nav_row]}")

    try:
        target = msg_to_edit or (update.callback_query and update.callback_query.message)
        if target:
            try:
                logger.debug("Отправка сообщения с клавиатурой через edit_text")
                await target.edit_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
                logger.debug("✅ Сообщение успешно обновлено с клавиатурой")
            except BadRequest as e:
                if "no text in the message" in str(e).lower():
                    # Сообщение содержит фото/документ, отправляем новое
                    await target.reply_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
                elif "Message is not modified" not in str(e):
                    logger.error(f"Ошибка при обновлении расписания: {e}")
        else:
            await update.effective_message.reply_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
    except BadRequest as e:
        if "Message is not modified" not in str(e) and "no text in the message" not in str(e).lower():
            logger.error(f"Ошибка при обновлении расписания: {e}")

async def show_notification_time_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "⏰ Выберите время для ежедневных уведомлений:"
    # Улучшенное расположение кнопок в 2 колонки для удобства на мобильных
    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("07:00", callback_data="set_time_07:00"), InlineKeyboardButton("18:00", callback_data="set_time_18:00")],
        [InlineKeyboardButton("19:00", callback_data="set_time_19:00"), InlineKeyboardButton("20:00", callback_data="set_time_20:00")],
        [InlineKeyboardButton("21:00", callback_data="set_time_21:00"), InlineKeyboardButton("22:00", callback_data="set_time_22:00")],
        [InlineKeyboardButton("23:00", callback_data="set_time_23:00")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_DATA_SETTINGS_MENU)]
    ])
    await safe_edit_message_text(update.callback_query, text, reply_markup=kbd)

async def set_notification_time(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    first_name = update.effective_user.first_name
    last_name = update.effective_user.last_name
    time_str = data.replace("set_time_", "")
    logger.info(f"⏰ [{user_id}] @{username} → Установлено время уведомлений: {time_str}")

    user_data = context.user_data
    user_data[CTX_NOTIFICATION_TIME] = time_str

    # Обновляем задачу уведомлений, если она активна
    chat_id = update.effective_chat.id
    if user_data.get(CTX_DAILY_NOTIFICATIONS) and context.job_queue and user_data.get(CTX_DEFAULT_QUERY):
        job_name = f"daily_schedule_{chat_id}"
        # Удаляем старую задачу
        for job in context.job_queue.get_jobs_by_name(job_name):
            job.schedule_removal()

        # Создаем новую задачу с новым временем
        hour, minute = map(int, time_str.split(":"))
        utc_hour = (hour - 3) % 24
        job_data = {"query": user_data[CTX_DEFAULT_QUERY], "mode": user_data[CTX_DEFAULT_MODE]}
        context.job_queue.run_daily(
            __import__("app.jobs").jobs.daily_schedule_job,
            time=datetime.time(utc_hour, minute, tzinfo=datetime.timezone.utc),
            chat_id=chat_id,
            name=job_name,
            data=job_data,
        )

    # Сохраняем в БД
    save_user_data_to_db(user_id, username, first_name, last_name, user_data)
    db.log_activity(user_id, "set_notification_time", f"time={time_str}")

    await safe_answer_callback_query(update.callback_query, f"Время уведомлений установлено: {time_str}")
    await settings_menu_callback(update, context)

async def toggle_daily_notifications_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    first_name = update.effective_user.first_name
    last_name = update.effective_user.last_name
    chat_id, user_data = update.effective_chat.id, context.user_data
    current_state = user_data.get(CTX_DAILY_NOTIFICATIONS, False)
    new_state = not current_state
    logger.info(f"🔔 [{user_id}] @{username} → {'Включены' if new_state else 'Выключены'} ежедневные уведомления")

    if not context.job_queue:
        await safe_answer_callback_query(update.callback_query, "Функция уведомлений неактивна.", show_alert=True)
        return
    if not user_data.get(CTX_DEFAULT_QUERY):
        await safe_answer_callback_query(update.callback_query, "Сначала установите группу/преподавателя!", show_alert=True)
        return

    job_name = f"daily_schedule_{chat_id}"
    for job in context.job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()

    if user_data.get(CTX_DAILY_NOTIFICATIONS, False):
        user_data[CTX_DAILY_NOTIFICATIONS] = False
        await safe_answer_callback_query(update.callback_query, "Ежедневные уведомления отключены.")
    else:
        user_data[CTX_DAILY_NOTIFICATIONS] = True
        time_str = user_data.get(CTX_NOTIFICATION_TIME, "21:00")
        hour, minute = map(int, time_str.split(":"))
        utc_hour = (hour - 3) % 24
        job_data = {"query": user_data[CTX_DEFAULT_QUERY], "mode": user_data[CTX_DEFAULT_MODE]}
        context.job_queue.run_daily(
            __import__("app.jobs").jobs.daily_schedule_job,
            time=datetime.time(utc_hour, minute, tzinfo=datetime.timezone.utc),
            chat_id=chat_id,
            name=job_name,
            data=job_data,
        )
        await safe_answer_callback_query(update.callback_query, f"Ежедневные уведомления включены на {time_str}!")

    # Сохраняем в БД
    save_user_data_to_db(user_id, username, first_name, last_name, user_data)
    db.log_activity(user_id, "toggle_daily_notifications", f"enabled={new_state}")

    await settings_menu_callback(update, context)

async def handle_quick_date_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Обработка быстрых кнопок 'Сегодня/Завтра' из главного меню или расписания"""
    user_data = context.user_data
    user_id = update.effective_user.id if update.effective_user else None

    # Определяем дату
    if "today" in data:
        date = datetime.date.today()
        date_text = "сегодня"
    else:
        date = datetime.date.today() + datetime.timedelta(days=1)
        date_text = "завтра"

    # Извлекаем режим из callback_data
    mode = None
    if "_quick_" in data:
        mode = data.split("_quick_")[-1]
    elif data.startswith(f"{CALLBACK_DATA_DATE_TODAY}_") or data.startswith(f"{CALLBACK_DATA_DATE_TOMORROW}_"):
        # Новый формат: pick_date_today_student или pick_date_tomorrow_student
        parts = data.split("_", 3)  # Разбиваем на 4 части: pick_date_today/tomorrow_mode
        if len(parts) >= 4:
            mode = parts[3]
        elif len(parts) >= 3:
            mode = parts[2]
    elif data.startswith("pick_date_"):
        # Старый формат: pick_date_today_student или pick_date_tomorrow_student
        parts = data.split("_")
        if len(parts) >= 4:
            mode = parts[3]  # student или teacher

    # Если режим не найден, используем сохраненный или дефолтный
    if not mode:
        mode = user_data.get(CTX_MODE) or user_data.get(CTX_DEFAULT_MODE) or "student"

    # Получаем query
    query = user_data.get(CTX_LAST_QUERY) or user_data.get(CTX_DEFAULT_QUERY)

    if not query:
        await safe_answer_callback_query(update.callback_query, "❌ Не указана группа/преподаватель. Выберите в настройках.", show_alert=True)
        await start_command(update, context)
        return

    user_data[CTX_SELECTED_DATE] = date.strftime("%Y-%m-%d")
    user_data[CTX_MODE] = mode
    user_data[CTX_LAST_QUERY] = query

    await safe_answer_callback_query(update.callback_query, f"📅 Загружаю расписание на {date_text}...")

    # Загружаем расписание
    api_type = API_TYPE_GROUP if mode == "student" else API_TYPE_TEACHER
    set_user_busy(user_data, True)
    try:
        pages, err = await safe_get_schedule(date.strftime("%Y-%m-%d"), query, api_type)
        if err or not pages:
            await update.callback_query.message.reply_text(
                f"❌ Не удалось получить расписание на {date_text} для '{escape_html(query)}': {err or 'Расписание не найдено'}",
                parse_mode=ParseMode.HTML
            )
            return

        user_data[CTX_SCHEDULE_PAGES] = pages
        user_data[CTX_CURRENT_PAGE_INDEX] = 0
        await send_schedule_with_pagination(update, context)
    finally:
        set_user_busy(user_data, False)

async def handle_date_from_notification(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    if "today" in data:
        date = datetime.date.today()
    else:
        date = datetime.date.today() + datetime.timedelta(days=1)
    context.user_data[CTX_SELECTED_DATE] = date.strftime("%Y-%m-%d")
    context.user_data[CTX_MODE] = context.user_data.get(CTX_DEFAULT_MODE, "student")
    query = context.user_data.get(CTX_DEFAULT_QUERY)
    if query:
        await update.callback_query.answer("Загружаю расписание...")
        await fetch_and_display_schedule(update, context, query)
    else:
        await update.callback_query.answer("Сначала установите группу в настройках!", show_alert=True)

async def handle_refresh_from_notification(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    mode = data.replace("refresh_from_notif_", "")
    context.user_data[CTX_MODE] = mode
    context.user_data[CTX_SELECTED_DATE] = datetime.date.today().strftime("%Y-%m-%d")
    query = context.user_data.get(CTX_DEFAULT_QUERY)
    if query:
        await update.callback_query.answer("🔄 Обновляю...")
        await fetch_and_display_schedule(update, context, query)
    else:
        await update.callback_query.answer("Сначала установите группу в настройках!", show_alert=True)

async def schedule_navigation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    query_obj, data = update.callback_query, update.callback_query.data
    try:
        action, mode, page_str = data.split("_", 2)
        context.user_data[CTX_MODE] = mode
        if action + "_" == CALLBACK_DATA_REFRESH_SCHEDULE_PREFIX:
            logger.info(f"🔄 [{user_id}] @{username} → Обновление расписания")
            await query_obj.answer("🔄 Обновляю...")
            await fetch_and_display_schedule(update, context, context.user_data[CTX_LAST_QUERY])
        else:
            page_num = int(page_str)
            direction = "← Назад" if action == "prev" else "→ Вперед"
            logger.info(f"📄 [{user_id}] @{username} → Навигация: {direction} (страница {page_num + 1})")
            context.user_data[CTX_CURRENT_PAGE_INDEX] = page_num
            await send_schedule_with_pagination(update, context)
    except Exception as e:
        logger.error(f"❌ [{user_id}] Ошибка навигации: {e}")
        await query_obj.answer("Ошибка навигации.", show_alert=True)

async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Инлайн-поиск групп/преподавателей и вставка расписания на сегодня.
    Форматы запроса:
    - "г <текст>" или без префикса — поиск групп
    - "п <текст>" — поиск преподавателей
    """
    user_id = update.inline_query.from_user.id

    # Проверяем статус бота (кроме админов)
    from .admin.utils import is_admin
    if not is_admin(user_id) and not is_bot_enabled():
        await update.inline_query.answer([], cache_time=1, is_personal=True)
        return

    username = update.inline_query.from_user.username or "без username"
    query_text = (update.inline_query.query or "").strip()

    if not query_text:
        await update.inline_query.answer([], cache_time=5, is_personal=True)
        return

    logger.info(f"🔍 [{user_id}] @{username} → Inline поиск: '{query_text[:50]}{'...' if len(query_text) > 50 else ''}'")

    # Умное определение типа сущности
    entity_type = None
    search_text = query_text
    found = None
    err = None

    # Сначала пробуем определить автоматически через detect_query_type
    query_type_result = detect_query_type(query_text)
    if query_type_result:
        entity_type = API_TYPE_GROUP if query_type_result[0] == "student" else API_TYPE_TEACHER
        search_text = query_type_result[1]
        found, err = await search_entities(search_text, entity_type)
        # Если не нашли с определенным типом, пробуем противоположный
        if not found or err:
            entity_type = API_TYPE_TEACHER if entity_type == API_TYPE_GROUP else API_TYPE_GROUP
            found, err = await search_entities(search_text, entity_type)
    else:
        # Если не удалось определить автоматически, пробуем оба варианта
        # Сначала группы (более частый случай)
        found, err = await search_entities(query_text, API_TYPE_GROUP)
        if found and not err:
            entity_type = API_TYPE_GROUP
        else:
            # Пробуем преподавателей
            found, err = await search_entities(query_text, API_TYPE_TEACHER)
            if found and not err:
                entity_type = API_TYPE_TEACHER

    # Если все еще не нашли, пробуем поиск по префиксу
    if (not found or err) and len(query_text.split()) > 1:
        words = query_text.split(maxsplit=1)
        prefix = words[0].lower()
        if prefix in {"п", "пр", "преп", "teacher", "преподаватель"}:
            entity_type = API_TYPE_TEACHER
            found, err = await search_entities(words[1], entity_type)
        elif prefix in {"г", "гр", "group", "группа"}:
            entity_type = API_TYPE_GROUP
            found, err = await search_entities(words[1], entity_type)

    if err or not found or not entity_type:
        if query_text:
            logger.warning(f"❌ [{user_id}] Inline поиск: ничего не найдено для '{query_text}'")
        await update.inline_query.answer([], cache_time=5, is_personal=True)
        return

    logger.info(f"✅ [{user_id}] Inline поиск: найдено {len(found)} результатов (тип: {entity_type})")
    today = datetime.date.today().strftime("%Y-%m-%d")
    results = []
    for name in found[:10]:
        pages, _ = await safe_get_schedule(today, name, entity_type, timeout=10.0)  # Меньший таймаут для inline запросов
        schedule_text = pages[0] if pages else "Расписание не найдено"
        title_prefix = "Группа" if entity_type == API_TYPE_GROUP else "Преподаватель"
        content = InputTextMessageContent(
            f"{title_prefix}: <b>{escape_html(name)}</b>\n\n{schedule_text}", parse_mode=ParseMode.HTML
        )
        results.append(
            InlineQueryResultArticle(
                id=f"{entity_type}_{hash(name)}_{today}",
                title=f"{name} — сегодня",
                description=f"Расписание на сегодня ({title_prefix.lower()})",
                input_message_content=content,
            )
        )

    await update.inline_query.answer(results, cache_time=30, is_personal=True)

async def show_export_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Показать меню экспорта"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    logger.info(f"📤 [{user_id}] @{username} → Открыл меню экспорта")

    # data format: "export_menu_{mode}_{query_hash}"
    mode, query_hash = parse_export_callback_data(data, CALLBACK_DATA_EXPORT_MENU)
    if not mode or not query_hash:
        await update.callback_query.answer("Ошибка данных", show_alert=True)
        return
    user_data = context.user_data
    entity_name = user_data.get(f"export_{mode}_{query_hash}")

    if not entity_name:
        await update.callback_query.answer("Ошибка: данные не найдены", show_alert=True)
        return

    # Сохраняем состояние для возврата к расписанию
    user_data["export_back_mode"] = mode
    user_data["export_back_query"] = entity_name
    export_date = user_data.get(CTX_SELECTED_DATE)
    if not export_date:
        export_date = datetime.date.today().strftime("%Y-%m-%d")
    user_data["export_back_date"] = export_date
    if user_data.get(CTX_SCHEDULE_PAGES):
        user_data["export_back_pages"] = user_data[CTX_SCHEDULE_PAGES]
        user_data["export_back_page_index"] = user_data.get(CTX_CURRENT_PAGE_INDEX, 0)

    entity_label = "преподавателя" if mode == "teacher" else "группы"

    text = f"📤 <b>Экспорт расписания для {entity_label}:</b>\n<code>{escape_html(entity_name)}</code>\n\nВыберите формат экспорта:"

    kbd_rows = []

    if mode == "student":
        # Для студентов: неделя картинкой, неделя файлом (PDF), по дням картинками
        kbd_rows.extend([
            [InlineKeyboardButton("🖼 Неделя (картинка)", callback_data=f"{CALLBACK_DATA_EXPORT_WEEK_IMAGE}_{mode}_{query_hash}")],
            [InlineKeyboardButton("📄 Неделя (PDF)", callback_data=f"{CALLBACK_DATA_EXPORT_WEEK_FILE}_{mode}_{query_hash}")],
            [InlineKeyboardButton("📸 По дням (картинки)", callback_data=f"{CALLBACK_DATA_EXPORT_DAYS_IMAGES}_{mode}_{query_hash}")],
        ])
    else:
        # Для преподавателей: неделя картинкой, неделя файлом (PDF)
        kbd_rows.extend([
            [InlineKeyboardButton("🖼 Неделя (картинка)", callback_data=f"{CALLBACK_DATA_EXPORT_WEEK_IMAGE}_{mode}_{query_hash}")],
            [InlineKeyboardButton("📄 Неделя (PDF)", callback_data=f"{CALLBACK_DATA_EXPORT_WEEK_FILE}_{mode}_{query_hash}")],
        ])

    # Кнопка "Назад" должна возвращать к расписанию, а не в начало
    kbd_rows.append([InlineKeyboardButton("⬅️ Назад к расписанию", callback_data="back_to_schedule_from_export")])

    kbd = InlineKeyboardMarkup(kbd_rows)
    if not await safe_edit_message_text(update.callback_query, text, reply_markup=kbd, parse_mode=ParseMode.HTML):
        try:
            await update.callback_query.message.reply_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
        except Exception:
            pass

def parse_export_callback_data(data: str, prefix: str) -> Tuple[Optional[str], Optional[str]]:
    """Парсит callback data для экспорта: возвращает (mode, query_hash)"""
    # data format: "{prefix}_{mode}_{query_hash}"
    try:
        parts = data.replace(prefix + "_", "", 1).split("_", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return None, None
    except Exception:
        return None, None

async def export_week_schedule_image(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Экспорт расписания на неделю картинкой"""
    if not update.callback_query:
        return

    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    logger.info(f"📤 [{user_id}] @{username} → Экспорт расписания: неделя (картинка)")

    # Парсим callback data с возможным week_offset
    week_offset = 0
    if data.endswith("_week0"):
        week_offset = 0
        data = data[:-6]  # Убираем "_week0"
    elif data.endswith("_week1"):
        week_offset = 1
        data = data[:-6]  # Убираем "_week1"

    mode, query_hash = parse_export_callback_data(data, CALLBACK_DATA_EXPORT_WEEK_IMAGE)
    if not mode or not query_hash:
        await safe_answer_callback_query(update.callback_query, "Ошибка данных", show_alert=True)
        return

    user_data = context.user_data
    entity_name = user_data.get(f"export_{mode}_{query_hash}")
    if not entity_name:
        await safe_answer_callback_query(update.callback_query, "Ошибка: данные не найдены", show_alert=True)
        return

    # Отвечаем на callback сразу, чтобы избежать timeout
    await safe_answer_callback_query(update.callback_query, "Генерирую картинку...")

    # Устанавливаем блокировку
    set_user_busy(user_data, True)

    try:
        entity_type = API_TYPE_TEACHER if mode == "teacher" else API_TYPE_GROUP
        from .export import get_week_schedule_structured, generate_schedule_image

        # Получаем расписание для выбранной недели
        week_schedule = await get_week_schedule_structured(entity_name, entity_type, week_offset=week_offset)

        # Если week_offset не был указан (0) и на текущей неделе нет пар, проверяем следующую неделю
        if week_offset == 0 and not week_schedule:
            next_week_schedule = await get_week_schedule_structured(entity_name, entity_type, week_offset=1)
            if next_week_schedule:
                # На следующей неделе есть пары - спрашиваем у пользователя
                today = datetime.date.today()
                days_since_monday = today.weekday()
                if days_since_monday == 6:
                    current_monday = today + datetime.timedelta(days=1)
                else:
                    current_monday = today - datetime.timedelta(days=days_since_monday)
                next_monday = current_monday + datetime.timedelta(days=7)

                text = (
                    f"📅 На текущей неделе ({current_monday.strftime('%d.%m.%Y')} - {(current_monday + datetime.timedelta(days=5)).strftime('%d.%m.%Y')}) "
                    f"нет занятий.\n\n"
                    f"На следующей неделе ({next_monday.strftime('%d.%m.%Y')} - {(next_monday + datetime.timedelta(days=5)).strftime('%d.%m.%Y')}) "
                    f"есть занятия.\n\n"
                    f"Какую неделю экспортировать?"
                )
                kbd = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📅 Текущая неделя", callback_data=f"{CALLBACK_DATA_EXPORT_WEEK_IMAGE}_{mode}_{query_hash}_week0")],
                    [InlineKeyboardButton("📅 Следующая неделя", callback_data=f"{CALLBACK_DATA_EXPORT_WEEK_IMAGE}_{mode}_{query_hash}_week1")],
                    [InlineKeyboardButton("⬅️ Назад", callback_data=f"{CALLBACK_DATA_EXPORT_MENU}_{mode}_{query_hash}")]
                ])
                await update.callback_query.message.edit_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
                set_user_busy(user_data, False)
                return

        # Если нет расписания для выбранной недели
        if not week_schedule:
            await update.callback_query.message.reply_text(
                "❌ На выбранной неделе нет занятий."
            )
            set_user_busy(user_data, False)
            return

        # Генерируем картинку (это может занять время)
        img_bytes = await generate_schedule_image(week_schedule, entity_name, entity_type)

        if img_bytes:
            entity_label = "преподавателя" if mode == "teacher" else "группы"
            # Сохраняем состояние для возврата (используем текущую дату из расписания)
            user_data["export_back_mode"] = mode
            user_data["export_back_query"] = entity_name
            # Сохраняем текущую дату из расписания, если она есть
            export_date = user_data.get(CTX_SELECTED_DATE)
            if not export_date:
                export_date = datetime.date.today().strftime("%Y-%m-%d")
            user_data["export_back_date"] = export_date
            # Также сохраняем страницы расписания для быстрого возврата
            if user_data.get(CTX_SCHEDULE_PAGES):
                user_data["export_back_pages"] = user_data[CTX_SCHEDULE_PAGES]
                user_data["export_back_page_index"] = user_data.get(CTX_CURRENT_PAGE_INDEX, 0)

            back_kbd = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад к расписанию", callback_data=CallbackData.BACK_TO_SCHEDULE.value)],
                [InlineKeyboardButton("🏠 В начало", callback_data=CALLBACK_DATA_BACK_TO_START)]
            ])
            await update.callback_query.message.reply_photo(
                photo=img_bytes,
                caption=f"📅 Расписание на неделю для {entity_label}: {escape_html(entity_name)}",
                reply_markup=back_kbd
            )
        else:
            from .export import format_week_schedule_text
            text = format_week_schedule_text(week_schedule, entity_name, entity_type)
            await update.callback_query.message.reply_text(text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Ошибка при генерации картинки: {e}", exc_info=True)
        try:
            await update.callback_query.message.reply_text(
                "❌ Произошла ошибка при генерации картинки. Попробуйте позже."
            )
        except Exception:
            pass
    finally:
        # Снимаем блокировку
        set_user_busy(user_data, False)

async def export_week_schedule_file(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Экспорт расписания на неделю файлом"""
    if not update.callback_query:
        return

    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    logger.info(f"📤 [{user_id}] @{username} → Экспорт расписания: неделя (PDF)")

    # Парсим callback data с возможным week_offset
    week_offset = 0
    if data.endswith("_week0"):
        week_offset = 0
        data = data[:-6]  # Убираем "_week0"
    elif data.endswith("_week1"):
        week_offset = 1
        data = data[:-6]  # Убираем "_week1"

    mode, query_hash = parse_export_callback_data(data, CALLBACK_DATA_EXPORT_WEEK_FILE)
    if not mode or not query_hash:
        await safe_answer_callback_query(update.callback_query, "Ошибка данных", show_alert=True)
        return

    user_data = context.user_data
    entity_name = user_data.get(f"export_{mode}_{query_hash}")
    if not entity_name:
        await safe_answer_callback_query(update.callback_query, "Ошибка: данные не найдены", show_alert=True)
        return

    # Отвечаем на callback сразу
    await safe_answer_callback_query(update.callback_query, "Генерирую файл...")

    # Устанавливаем блокировку
    set_user_busy(user_data, True)

    try:
        entity_type = API_TYPE_TEACHER if mode == "teacher" else API_TYPE_GROUP
        from .export import get_week_schedule_structured, generate_week_schedule_file

        # Получаем расписание для выбранной недели
        week_schedule = await get_week_schedule_structured(entity_name, entity_type, week_offset=week_offset)

        # Если week_offset не был указан (0) и на текущей неделе нет пар, проверяем следующую неделю
        if week_offset == 0 and not week_schedule:
            next_week_schedule = await get_week_schedule_structured(entity_name, entity_type, week_offset=1)
            if next_week_schedule:
                # На следующей неделе есть пары - спрашиваем у пользователя
                today = datetime.date.today()
                days_since_monday = today.weekday()
                if days_since_monday == 6:
                    current_monday = today + datetime.timedelta(days=1)
                else:
                    current_monday = today - datetime.timedelta(days=days_since_monday)
                next_monday = current_monday + datetime.timedelta(days=7)

                text = (
                    f"📅 На текущей неделе ({current_monday.strftime('%d.%m.%Y')} - {(current_monday + datetime.timedelta(days=5)).strftime('%d.%m.%Y')}) "
                    f"нет занятий.\n\n"
                    f"На следующей неделе ({next_monday.strftime('%d.%m.%Y')} - {(next_monday + datetime.timedelta(days=5)).strftime('%d.%m.%Y')}) "
                    f"есть занятия.\n\n"
                    f"Какую неделю экспортировать?"
                )
                kbd = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📅 Текущая неделя", callback_data=f"{CALLBACK_DATA_EXPORT_WEEK_FILE}_{mode}_{query_hash}_week0")],
                    [InlineKeyboardButton("📅 Следующая неделя", callback_data=f"{CALLBACK_DATA_EXPORT_WEEK_FILE}_{mode}_{query_hash}_week1")],
                    [InlineKeyboardButton("⬅️ Назад", callback_data=f"{CALLBACK_DATA_EXPORT_MENU}_{mode}_{query_hash}")]
                ])
                await update.callback_query.message.edit_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
                set_user_busy(user_data, False)
                return

        # Если нет расписания для выбранной недели
        if not week_schedule:
            await update.callback_query.message.reply_text(
                "❌ На выбранной неделе нет занятий."
            )
            set_user_busy(user_data, False)
            return
        file_bytes = await generate_week_schedule_file(week_schedule, entity_name, entity_type)

        if file_bytes:
            entity_label = "преподавателя" if mode == "teacher" else "группы"
            filename = f"raspisanie_{entity_name.replace(' ', '_')[:30]}.pdf"
            # Сохраняем состояние для возврата (используем текущую дату из расписания)
            user_data["export_back_mode"] = mode
            user_data["export_back_query"] = entity_name
            # Сохраняем текущую дату из расписания, если она есть
            export_date = user_data.get(CTX_SELECTED_DATE)
            if not export_date:
                export_date = datetime.date.today().strftime("%Y-%m-%d")
            user_data["export_back_date"] = export_date
            # Также сохраняем страницы расписания для быстрого возврата
            if user_data.get(CTX_SCHEDULE_PAGES):
                user_data["export_back_pages"] = user_data[CTX_SCHEDULE_PAGES]
                user_data["export_back_page_index"] = user_data.get(CTX_CURRENT_PAGE_INDEX, 0)

            back_kbd = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад к расписанию", callback_data=CallbackData.BACK_TO_SCHEDULE.value)],
                [InlineKeyboardButton("🏠 В начало", callback_data=CALLBACK_DATA_BACK_TO_START)]
            ])
            await update.callback_query.message.reply_document(
                document=file_bytes,
                filename=filename,
                caption=f"📄 Расписание на неделю для {entity_label}: {escape_html(entity_name)}",
                reply_markup=back_kbd
            )
        else:
            try:
                await update.callback_query.message.reply_text("❌ Ошибка при генерации файла. Попробуйте позже.")
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Ошибка при генерации файла: {e}", exc_info=True)
        try:
            await update.callback_query.message.reply_text("❌ Произошла ошибка при генерации файла. Попробуйте позже.")
        except Exception:
            pass
    finally:
        # Снимаем блокировку
        set_user_busy(user_data, False)

async def export_days_images(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Экспорт расписания по дням (отдельные картинки для каждого дня)"""
    if not update.callback_query:
        return

    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    logger.info(f"📤 [{user_id}] @{username} → Экспорт расписания: по дням (картинки)")

    mode, query_hash = parse_export_callback_data(data, CALLBACK_DATA_EXPORT_DAYS_IMAGES)
    logger.info(f"Экспорт по дням: mode = {mode}, query_hash = {query_hash}")

    if not mode or not query_hash:
        logger.error(f"Ошибка парсинга callback_data: mode={mode}, query_hash={query_hash}")
        await safe_answer_callback_query(update.callback_query, "Ошибка данных", show_alert=True)
        return

    user_data = context.user_data
    entity_name = user_data.get(f"export_{mode}_{query_hash}")
    logger.info(f"Экспорт по дням: entity_name = {entity_name}")

    if not entity_name:
        logger.error(f"Entity name не найден для ключа: export_{mode}_{query_hash}")
        await safe_answer_callback_query(update.callback_query, "Ошибка: данные не найдены", show_alert=True)
        return

    # Отвечаем на callback сразу
    await safe_answer_callback_query(update.callback_query, "Генерирую картинки по дням...")

    # Устанавливаем блокировку
    set_user_busy(user_data, True)

    # Отправляем сообщение о начале генерации
    progress_msg = None
    try:
        progress_msg = await update.callback_query.message.reply_text("🔄 Генерирую расписание по дням...\n\n📊 Прогресс: 0 из 6")
    except Exception:
        pass

    try:
        entity_type = API_TYPE_TEACHER if mode == "teacher" else API_TYPE_GROUP
        from .export import get_week_schedule_structured, generate_day_schedule_image
        from .schedule import get_schedule_structured

        # Используем ту же логику, что и в get_week_schedule_structured
        today = datetime.date.today()
        days_since_monday = today.weekday()
        if days_since_monday == 6:  # Воскресенье
            monday = today + datetime.timedelta(days=1)
        else:
            monday = today - datetime.timedelta(days=days_since_monday)

        week_schedule = await get_week_schedule_structured(entity_name, entity_type, start_date=today)
        logger.info(f"Получено расписание на неделю: {len(week_schedule)} дней (неделя с {monday.strftime('%d.%m.%Y')})")

        weekdays = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]
        entity_label = "преподавателя" if mode == "teacher" else "группы"

        # Сначала определяем, сколько дней с парами будет
        days_with_pairs_list = []
        for day_offset in range(6):
            current_date = monday + datetime.timedelta(days=day_offset)
            date_str = current_date.strftime("%Y-%m-%d")
            pairs = week_schedule.get(date_str, [])
            if pairs:
                days_with_pairs_list.append((day_offset, date_str, weekdays[day_offset]))

        total_days_with_pairs = len(days_with_pairs_list)
        if total_days_with_pairs == 0:
            if progress_msg:
                try:
                    await progress_msg.delete()
                except Exception:
                    pass
            try:
                await update.callback_query.message.reply_text("📅 На этой неделе нет занятий.")
            except Exception:
                pass
            return

        # Собираем все картинки и подписи
        media_group = []
        generated_count = 0

        for day_offset in range(6):  # Пн-Сб
            current_date = monday + datetime.timedelta(days=day_offset)
            date_str = current_date.strftime("%Y-%m-%d")
            weekday_name = weekdays[day_offset]

            pairs = week_schedule.get(date_str, [])
            logger.info(f"День {date_str}: {len(pairs)} пар")

            if not pairs:  # Пропускаем дни без пар
                continue

            # Обновляем прогресс только в начале и периодически (реже, чтобы было плавнее)
            if progress_msg:
                # Обновляем только при первой генерации и потом каждые 2 картинки
                should_update_progress = (generated_count == 0) or (generated_count > 0 and generated_count % 2 == 0)
                if should_update_progress:
                    try:
                        progress_text = (
                            f"🔄 Генерирую расписание по дням...\n\n"
                            f"📊 Прогресс: {generated_count} из {total_days_with_pairs}\n"
                            f"📅 Текущий день: {weekday_name}"
                        )
                        await progress_msg.edit_text(progress_text)
                        # Задержка для плавности отображения
                        await asyncio.sleep(1.0)
                    except Exception:
                        pass

            day_schedule, err = await get_schedule_structured(date_str, entity_name, entity_type)
            if err or not day_schedule:
                logger.warning(f"Не удалось получить расписание для {date_str}: {err}")
                continue

            img_bytes = await generate_day_schedule_image(day_schedule, entity_name, entity_type)
            if img_bytes:
                # Добавляем в медиагруппу (подпись только у первой картинки)
                if len(media_group) == 0:
                    caption = (
                        f"📅 Расписание на неделю для {entity_label}: {escape_html(entity_name)}\n"
                        f"📆 Неделя: {monday.strftime('%d.%m.%Y')} - {(monday + datetime.timedelta(days=5)).strftime('%d.%m.%Y')}"
                    )
                    media_group.append(InputMediaPhoto(media=img_bytes, caption=caption))
                else:
                    media_group.append(InputMediaPhoto(media=img_bytes))
                generated_count += 1

                # Небольшая задержка между генерацией картинок
                await asyncio.sleep(0.5)
            else:
                logger.warning(f"Не удалось сгенерировать картинку для {date_str}")

        # Удаляем сообщение о прогрессе перед отправкой
        if progress_msg:
            try:
                await progress_msg.delete()
            except Exception:
                pass

        # Отправляем все картинки одним MediaGroup
        if media_group:
            # Сохраняем состояние для возврата
            user_data["export_back_mode"] = mode
            user_data["export_back_query"] = entity_name
            user_data["export_back_date"] = (monday + datetime.timedelta(days=5)).strftime("%Y-%m-%d")
            if user_data.get(CTX_SCHEDULE_PAGES):
                user_data["export_back_pages"] = user_data[CTX_SCHEDULE_PAGES]
                user_data["export_back_page_index"] = user_data.get(CTX_CURRENT_PAGE_INDEX, 0)

            back_kbd = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад к расписанию", callback_data=CallbackData.BACK_TO_SCHEDULE.value)],
                        [InlineKeyboardButton("🏠 В начало", callback_data=CALLBACK_DATA_BACK_TO_START)]
                    ])

            # Отправляем MediaGroup
            try:
                sent_messages = await update.callback_query.message.reply_media_group(media=media_group)
                # Добавляем только одно финальное сообщение с информацией
                if sent_messages:
                    entity_label_text = "группы" if mode == "student" else "преподавателя"
                    await sent_messages[-1].reply_text(
                        f"📅 Расписание на неделю для {entity_label_text}: {escape_html(entity_name)}",
                        reply_markup=back_kbd
                    )
            except Exception as e:
                logger.error(f"Ошибка при отправке MediaGroup: {e}", exc_info=True)
                # Если MediaGroup не работает, отправляем по одной
                for i, media in enumerate(media_group):
                    try:
                        if i == len(media_group) - 1:
                            await update.callback_query.message.reply_photo(
                                photo=media.media,
                                caption=media.caption,
                                reply_markup=back_kbd
                            )
                        else:
                            await update.callback_query.message.reply_photo(
                                photo=media.media,
                                caption=media.caption
                            )
                        await asyncio.sleep(0.3)
                    except Exception as photo_error:
                        logger.error(f"Ошибка при отправке фото {i}: {photo_error}")

            # Удаляем сообщение о прогрессе
            if progress_msg:
                try:
                    await progress_msg.delete()
                except Exception:
                    pass
        else:
            # Удаляем сообщение о прогрессе и отправляем сообщение об отсутствии расписания
            if progress_msg:
                try:
                    await progress_msg.delete()
                except Exception:
                    pass
            try:
                await update.callback_query.message.reply_text("📅 На этой неделе нет занятий.")
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Ошибка при генерации картинок по дням: {e}", exc_info=True)
        if progress_msg:
            try:
                await progress_msg.delete()
            except Exception:
                pass
        try:
            await update.callback_query.message.reply_text("❌ Произошла ошибка при генерации картинок. Попробуйте позже.")
        except Exception:
            pass
    finally:
        # Снимаем блокировку
        set_user_busy(user_data, False)

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        logger.error("callback_router вызван без callback_query")
        return

    if not update.effective_user:
        logger.error("callback_router вызван без effective_user")
        return

    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    data = update.callback_query.data
    user_data = context.user_data

    # Проверяем, не админский ли это callback
    from .admin.handlers import admin_callback_router

    if data.startswith(CALLBACK_USER_REPLY_ADMIN_PREFIX):
        admin_id_str = data.replace(CALLBACK_USER_REPLY_ADMIN_PREFIX, "", 1)
        try:
            admin_id = int(admin_id_str)
        except ValueError:
            await safe_answer_callback_query(update.callback_query, "Администратор не найден", show_alert=True)
            return
        await start_user_reply_to_admin(update, context, admin_id)
        return
    if data.startswith(CALLBACK_USER_DISMISS_ADMIN_PREFIX):
        admin_id_str = data.replace(CALLBACK_USER_DISMISS_ADMIN_PREFIX, "", 1)
        try:
            admin_id = int(admin_id_str)
        except ValueError:
            await safe_answer_callback_query(update.callback_query, "Действие недоступно", show_alert=True)
            return
        await handle_user_dismiss_admin_message(update, context, admin_id)
        return
    if data.startswith("admin_"):
        await admin_callback_router(update, context)
        return

    # Проверяем статус бота (кроме админов)
    from .admin.utils import is_admin
    if not is_admin(user_id) and not is_bot_enabled():
        maintenance_msg = get_maintenance_message()
        await update.callback_query.answer(maintenance_msg, show_alert=True)
        return

    logger.info(f"🔘 [{user_id}] @{username} → Callback: '{data}'")

    # Проверяем блокировку
    if check_user_busy(user_data) and not data.startswith("cancel"):
        await safe_answer_callback_query(update.callback_query, "⏳ Пожалуйста, подождите...")
        return

    # Отвечаем на callback сразу
    await safe_answer_callback_query(update.callback_query)

    try:
        if data == CALLBACK_DATA_MODE_STUDENT or data == CALLBACK_DATA_MODE_TEACHER:
            mode = "student" if data == CALLBACK_DATA_MODE_STUDENT else "teacher"
            mode_text = "студента" if mode == "student" else "преподавателя"
            logger.info(f"🎯 [{user_id}] @{username} → Выбран режим: {mode_text}")
            user_data[CTX_MODE] = mode

            # Проверяем, новый ли это пользователь (первый запуск без установленной группы)
            default_query = user_data.get(CTX_DEFAULT_QUERY)
            is_new_user = default_query is None

            if is_new_user:
                # Для новых пользователей запрашиваем ввод группы/преподавателя
                prompt = "🎓 Введите название вашей группы:" if mode == "student" else "🧑‍🏫 Введите ФИО преподавателя:"
                user_data[CTX_AWAITING_DEFAULT_QUERY] = True
                kbd = InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data=CALLBACK_DATA_CANCEL_INPUT)]])
                await safe_edit_message_text(update.callback_query, prompt, reply_markup=kbd)
            else:
                # Для существующих пользователей показываем стандартный запрос
                prompt = "🎓 Введите название группы:" if mode == "student" else "🧑‍🏫 Введите ФИО преподавателя:"
                kbd = InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data=CALLBACK_DATA_CANCEL_INPUT)]])
                await safe_edit_message_text(update.callback_query, prompt, reply_markup=kbd)
        elif data.startswith("confirm_mode_"):
            # Подтверждение режима при умном холодном старте
            parts = data.replace("confirm_mode_", "").split("_", 1)
            if len(parts) == 2:
                mode = parts[0]
                pending_query = user_data.get(f"pending_query_{mode}")
                if pending_query:
                    user_data[CTX_MODE] = mode
                    user_data.pop(f"pending_query_{mode}", None)
                    await handle_schedule_search(update, context, pending_query)
                else:
                    await safe_edit_message_text(update.callback_query, "Ошибка: запрос не найден")
        elif data.startswith("quick_schedule_"):
            # Быстрый доступ к расписанию по умолчанию
            mode = data.replace("quick_schedule_", "")
            default_query = user_data.get(CTX_DEFAULT_QUERY)
            if default_query:
                user_data[CTX_MODE] = mode
                user_data[CTX_SELECTED_DATE] = datetime.date.today().strftime("%Y-%m-%d")
                await safe_edit_message_text(update.callback_query, "Загружаю ваше расписание...")
                await fetch_and_display_schedule(update, context, default_query)
            else:
                await safe_answer_callback_query(update.callback_query, "Расписание по умолчанию не установлено", show_alert=True)
        elif data == CALLBACK_DATA_BACK_TO_START:
            await start_command(update, context)
        elif data == CallbackData.HELP_COMMAND_INLINE.value or data == "help_command_inline":
            await help_command_handler(update, context)
        elif data == CALLBACK_DATA_SETTINGS_MENU:
            await settings_menu_callback(update, context)
        elif data.startswith("set_default_mode_"):
            mode = "student" if "student" in data else "teacher"
            mode_text = "группу" if mode == "student" else "преподавателя"
            logger.info(f"⚙️ [{user_id}] @{username} → Настройка {mode_text} по умолчанию")
            user_data[CTX_MODE], user_data[CTX_AWAITING_DEFAULT_QUERY] = mode, True
            prompt = "Теперь отправьте точное название группы:" if mode == "student" else "Теперь отправьте точное ФИО преподавателя:"
            kbd = InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data=CALLBACK_DATA_CANCEL_INPUT)]])
            await safe_edit_message_text(update.callback_query, prompt, reply_markup=kbd)
        elif data.startswith("choose_default_"):
            payload = data.replace("choose_default_", "", 1)
            if "_" not in payload:
                await settings_menu_callback(update, context)
            else:
                mode, idx_str = payload.rsplit("_", 1)
                try:
                    idx = int(idx_str)
                except ValueError:
                    idx = -1
                options = user_data.get(f"default_options_{mode}", [])
                if 0 <= idx < len(options):
                    chosen = options[idx]
                    user_data.pop(f"default_options_{mode}", None)
                    user_data.pop(CTX_AWAITING_DEFAULT_QUERY, None)

                    # Проверяем, новый ли это пользователь (первый запуск)
                    is_new_user = user_data.get(CTX_DEFAULT_QUERY) is None

                    await _apply_default_selection(update, context, chosen, mode, source="callback")

                    if is_new_user:
                        # Для новых пользователей показываем сообщение об успешной установке
                        mode_text = "группу" if mode == "student" else "преподавателя"
                        await safe_edit_message_text(
                            update.callback_query,
                            f"✅ Вы установили {mode_text}: <b>{escape_html(chosen)}</b>",
                            parse_mode=ParseMode.HTML
                        )
                        # Удаляем сообщение через 3 секунды и показываем главное меню
                        msg_to_delete = update.callback_query.message
                        asyncio.create_task(_delete_message_after_delay(context.bot, msg_to_delete.chat_id, msg_to_delete.message_id, 3.0))
                        # Показываем главное меню через 3.5 секунды (после удаления сообщения)
                        await asyncio.sleep(3.5)
                        await start_command(update, context)
                    else:
                        await safe_edit_message_text(
                            update.callback_query,
                            f"✅ Установлено по умолчанию: <b>{escape_html(chosen)}</b>",
                            parse_mode=ParseMode.HTML
                        )
                else:
                    await safe_edit_message_text(update.callback_query, "Не удалось определить выбранный вариант.")
            await settings_menu_callback(update, context)
        elif data == "reset_settings":
            # Подтверждение сброса
            prompt = (
                "Вы уверены, что хотите сбросить настройки?\n\n"
                "Будут удалены: выбранная группа/преподаватель и отключены уведомления."
            )
            kbd = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да, сбросить", callback_data="do_reset_settings")],
                [InlineKeyboardButton("⬅️ Отмена", callback_data=CALLBACK_DATA_SETTINGS_MENU)]
            ])
            await safe_edit_message_text(update.callback_query, prompt, reply_markup=kbd)
        elif data == "do_reset_settings":
            # Выполняем сброс
            # Останавливаем джоб, если активна
            chat_id = update.effective_chat.id if update.effective_chat else None
            if context.job_queue and chat_id:
                job_name = f"daily_schedule_{chat_id}"
                job = context.job_queue.get_jobs_by_name(job_name)
                if job:
                    for j in job:
                        try:
                            j.schedule_removal()
                        except Exception:
                            pass
            # Чистим user_data
            for key in [
                CTX_DEFAULT_QUERY,
                CTX_DEFAULT_MODE,
                CTX_LAST_QUERY,
                CTX_SCHEDULE_PAGES,
                CTX_CURRENT_PAGE_INDEX,
            ]:
                user_data.pop(key, None)
            user_data[CTX_DAILY_NOTIFICATIONS] = False
            user_data[CTX_NOTIFICATION_TIME] = "21:00"
            user_data.pop(CTX_SELECTED_DATE, None)
            # Сохраняем в БД: гарантированно очищаем значения в таблице
            first_name = update.effective_user.first_name if update.effective_user else None
            last_name = update.effective_user.last_name if update.effective_user else None
            try:
                # Полное удаление записи и создание чистой с дефолтами
                db.delete_user(user_id)
            except Exception:
                pass
            # Создаем запись со сброшенными настройками
            db.save_user(
                user_id=user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                default_query=None,
                default_mode=None,
                daily_notifications=False,
                notification_time="21:00"
            )
            db.log_activity(user_id, "reset_settings", "defaults_cleared")
            # Возвращаемся в настройки
            await safe_answer_callback_query(update.callback_query, "Настройки сброшены.")
            await settings_menu_callback(update, context)
        elif data == CALLBACK_DATA_TOGGLE_DAILY:
            await toggle_daily_notifications_callback(update, context)
        elif data == "set_notification_time":
            await show_notification_time_menu(update, context)
        elif data.startswith("set_time_"):
            await set_notification_time(update, context, data)
        elif data.startswith(f"{CALLBACK_DATA_DATE_TODAY}_from_notif") or data.startswith(f"{CALLBACK_DATA_DATE_TOMORROW}_from_notif"):
            await handle_date_from_notification(update, context, data)
        elif data.startswith(f"{CALLBACK_DATA_DATE_TODAY}_quick_") or data.startswith(f"{CALLBACK_DATA_DATE_TOMORROW}_quick_"):
            # Быстрый доступ из главного меню
            await handle_quick_date_callback(update, context, data)
        elif data.startswith(f"{CALLBACK_DATA_DATE_TODAY}_") or data.startswith(f"{CALLBACK_DATA_DATE_TOMORROW}_"):
            # Быстрый доступ из расписания
            await handle_quick_date_callback(update, context, data)
        elif data.startswith("refresh_from_notif_"):
            await handle_refresh_from_notification(update, context, data)
        elif data.startswith((CALLBACK_DATA_PREV_SCHEDULE_PREFIX, CALLBACK_DATA_NEXT_SCHEDULE_PREFIX, CALLBACK_DATA_REFRESH_SCHEDULE_PREFIX)):
            await schedule_navigation_callback(update, context)
        elif data == CALLBACK_DATA_CANCEL_INPUT:
            awaiting_manual = user_data.pop(CTX_AWAITING_MANUAL_DATE, None)
            awaiting_default = user_data.pop(CTX_AWAITING_DEFAULT_QUERY, None)
            user_data.pop(CTX_IS_BUSY, None)
            # Очищаем pending queries
            for key in list(user_data.keys()):
                if key.startswith("pending_query_") or key.startswith("default_options_"):
                    user_data.pop(key, None)
            try:
                await safe_edit_message_text(update.callback_query, "Действие отменено.")
            except BadRequest:
                pass
            if awaiting_default:
                await settings_menu_callback(update, context)
            elif awaiting_manual:
                await start_command(update, context)
            else:
                await start_command(update, context)
        elif data.startswith(CALLBACK_DATA_EXPORT_MENU):
            await show_export_menu(update, context, data)
        elif data.startswith(CALLBACK_DATA_EXPORT_WEEK_IMAGE):
            await export_week_schedule_image(update, context, data)
        elif data.startswith(CALLBACK_DATA_EXPORT_WEEK_FILE):
            await export_week_schedule_file(update, context, data)
        elif data.startswith(CALLBACK_DATA_EXPORT_DAYS_IMAGES):
            await export_days_images(update, context, data)
        elif data.startswith("view_changed_schedule_"):
            # Обработка просмотра измененного расписания
            parts = data.replace("view_changed_schedule_", "").split("_", 1)
            if len(parts) == 2:
                mode, date_str = parts[0], parts[1]
                logger.info(f"👁️ [{user_id}] @{username} → Просмотр измененного расписания на {date_str}")
                schedule_data = context.bot_data.get(f"changed_schedule_{user_id}_{date_str}")
                if schedule_data:
                    user_data[CTX_MODE] = mode
                    user_data[CTX_SELECTED_DATE] = date_str
                    user_data[CTX_LAST_QUERY] = schedule_data["query"]
                    user_data[CTX_SCHEDULE_PAGES] = schedule_data["pages"]
                    user_data[CTX_CURRENT_PAGE_INDEX] = 0
                    await send_schedule_with_pagination(update, context)
                else:
                    await safe_answer_callback_query(update.callback_query, "Расписание больше не доступно", show_alert=True)
        elif data == CallbackData.BACK_TO_SCHEDULE.value or data == "back_to_schedule_from_export":
            # Возврат к расписанию из экспорта или меню экспорта
            mode = user_data.get("export_back_mode")
            query = user_data.get("export_back_query")
            date_str = user_data.get("export_back_date", datetime.date.today().strftime("%Y-%m-%d"))
            saved_pages = user_data.get("export_back_pages")
            saved_page_index = user_data.get("export_back_page_index", 0)

            logger.info(f"⬅️ [{user_id}] @{username} → Возврат к расписанию из экспорта: {query} ({date_str})")

            if mode and query:
                user_data[CTX_MODE] = mode
                user_data[CTX_SELECTED_DATE] = date_str
                user_data[CTX_LAST_QUERY] = query

                # Если есть сохраненные страницы, используем их для быстрого возврата
                if saved_pages:
                    user_data[CTX_SCHEDULE_PAGES] = saved_pages
                    user_data[CTX_CURRENT_PAGE_INDEX] = saved_page_index
                    # Пытаемся показать сообщение о загрузке, но не критично если не получится
                    await safe_edit_message_text(update.callback_query, "Возвращаюсь к расписанию...")
                    await send_schedule_with_pagination(update, context)
                else:
                    # Загружаем расписание заново, если страницы не сохранены
                    await safe_edit_message_text(update.callback_query, "Загружаю расписание...")
                    await fetch_and_display_schedule(update, context, query)
            else:
                logger.warning(f"⚠️ [{user_id}] Не удалось восстановить состояние расписания из экспорта")
                await safe_answer_callback_query(update.callback_query, "Не удалось восстановить расписание", show_alert=True)
        else:
            logger.warning(f"⚠️ [{user_id}] Неизвестный callback: {data}")
            await safe_answer_callback_query(update.callback_query, "Неизвестная команда", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка в callback_router: {e}", exc_info=True)
        try:
            await safe_answer_callback_query(update.callback_query, "Произошла ошибка", show_alert=True)
        except Exception:
            pass
