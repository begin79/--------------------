"""
Обработчики callback queries и роутер
"""
import datetime
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from ..constants import (
    CTX_MODE, CTX_SELECTED_DATE, CTX_AWAITING_MANUAL_DATE, CTX_LAST_QUERY,
    CTX_SCHEDULE_PAGES, CTX_CURRENT_PAGE_INDEX, CTX_AWAITING_DEFAULT_QUERY,
    CTX_DEFAULT_QUERY, CTX_DEFAULT_MODE, CTX_DAILY_NOTIFICATIONS, CTX_NOTIFICATION_TIME,
    CTX_IS_BUSY,
    CALLBACK_DATA_MODE_STUDENT, CALLBACK_DATA_MODE_TEACHER, CALLBACK_DATA_BACK_TO_START,
    CALLBACK_DATA_SETTINGS_MENU, CALLBACK_DATA_CANCEL_INPUT, CALLBACK_DATA_CONFIRM_MODE,
    CALLBACK_DATA_DATE_TODAY, CALLBACK_DATA_DATE_TOMORROW,
    CALLBACK_DATA_EXPORT_MENU, CALLBACK_DATA_EXPORT_WEEK_IMAGE, CALLBACK_DATA_EXPORT_WEEK_FILE,
    CALLBACK_DATA_EXPORT_DAYS_IMAGES, CALLBACK_DATA_EXPORT_SEMESTER,
    CALLBACK_DATA_RESET_SETTINGS, CALLBACK_DATA_DO_RESET_SETTINGS,
    CALLBACK_DATA_SET_NOTIFICATION_TIME, CALLBACK_DATA_TOGGLE_DAILY,
    CALLBACK_DATA_FEEDBACK, CALLBACK_DATA_NOTIFICATION_OPEN_PREFIX,
    CALLBACK_DATA_PREV_SCHEDULE_PREFIX, CALLBACK_DATA_NEXT_SCHEDULE_PREFIX,
    CALLBACK_DATA_REFRESH_SCHEDULE_PREFIX,
    MODE_STUDENT, MODE_TEACHER, ENTITY_GROUP, ENTITY_TEACHER, ENTITY_STUDENT,
    DEFAULT_NOTIFICATION_TIME, JOB_PREFIX_DAILY_SCHEDULE, CallbackData,
)
from ..admin.handlers import (
    CALLBACK_USER_REPLY_ADMIN_PREFIX,
    CALLBACK_USER_DISMISS_ADMIN_PREFIX,
)
from ..admin.utils import is_bot_enabled, get_maintenance_message, is_admin
from ..state_manager import (
    validate_callback_data, safe_get_user_data, is_user_busy, set_user_busy,
    clear_user_busy_state, clear_temporary_states
)
from ..database import db
from .start import start_command
from .help import help_command_handler
from .settings import settings_menu_callback, handle_reset_confirm, handle_reset_execute
from .feedback import feedback_callback
from .notifications import (
    toggle_daily_notifications_callback, show_notification_time_menu,
    set_notification_time, handle_notification_open_callback
)
from .schedule import (
    handle_schedule_search, send_schedule_with_pagination, schedule_navigation_callback,
    fetch_and_display_schedule, detect_query_type
)
from .export import (
    show_export_menu, export_week_schedule_image, export_week_schedule_file,
    export_days_images, export_semester_excel
)
from .admin_dialogs import start_user_reply_to_admin, handle_user_dismiss_admin_message
from .text import handle_quick_date_callback, _apply_default_selection
from .utils import safe_answer_callback_query, safe_edit_message_text, user_busy_context

logger = logging.getLogger(__name__)


async def handle_confirm_mode(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Подтверждение режима при умном холодном старте"""
    user_data = context.user_data
    parts = data.replace(CALLBACK_DATA_CONFIRM_MODE, "").split("_", 1)
    if len(parts) == 2:
        mode = parts[0]
        pending_query = user_data.get(f"pending_query_{mode}")
        if pending_query:
            user_data[CTX_MODE] = mode
            user_data.pop(f"pending_query_{mode}", None)
            # Просто показываем расписание, не устанавливаем default_query
            await handle_schedule_search(update, context, pending_query)
        else:
            error_kbd = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 Попробовать снова", callback_data=CALLBACK_DATA_BACK_TO_START)],
                [InlineKeyboardButton("🏠 В начало", callback_data=CALLBACK_DATA_BACK_TO_START)]
            ])
            await safe_edit_message_text(update.callback_query, "Ошибка: запрос не найден. Попробуйте ввести запрос снова.", reply_markup=error_kbd)


async def handle_quick_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Быстрый доступ к расписанию по умолчанию"""
    user_data = context.user_data
    mode = data.replace("quick_schedule_", "")
    default_query = user_data.get(CTX_DEFAULT_QUERY)
    if default_query:
        user_data[CTX_MODE] = mode
        user_data[CTX_SELECTED_DATE] = datetime.date.today().strftime("%Y-%m-%d")
        await safe_edit_message_text(update.callback_query, "Загружаю ваше расписание...")
        await fetch_and_display_schedule(update, context, default_query)
    else:
        await safe_answer_callback_query(update.callback_query, "Расписание по умолчанию не установлено", show_alert=True)


async def handle_set_default_mode(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Настройка режима по умолчанию"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    user_data = context.user_data
    mode = MODE_STUDENT if "student" in data else MODE_TEACHER
    mode_text = ENTITY_GROUP if mode == MODE_STUDENT else ENTITY_TEACHER
    logger.info(f"⚙️ [{user_id}] @{username} → Настройка {mode_text} по умолчанию")
    user_data[CTX_MODE], user_data[CTX_AWAITING_DEFAULT_QUERY] = mode, True
    prompt = "Теперь отправьте точное название группы:" if mode == MODE_STUDENT else "Теперь отправьте точное ФИО преподавателя:"
    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data=CALLBACK_DATA_CANCEL_INPUT)],
        [InlineKeyboardButton("🏠 В начало", callback_data=CALLBACK_DATA_BACK_TO_START)]
    ])
    await safe_edit_message_text(update.callback_query, prompt, reply_markup=kbd)


async def handle_set_default_from_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Установка расписания по умолчанию прямо из расписания"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    user_data = context.user_data

    # Парсим данные: "set_default_from_schedule_{mode}_{query_hash}"
    parts = data.replace("set_default_from_schedule_", "").split("_", 1)
    if len(parts) != 2:
        await safe_answer_callback_query(update.callback_query, "Ошибка данных", show_alert=True)
        return

    mode = parts[0]
    query_hash = parts[1]
    query = user_data.get(f"set_default_query_{query_hash}")

    if not query:
        await safe_answer_callback_query(update.callback_query, "Ошибка: данные не найдены", show_alert=True)
        return

    mode_text = ENTITY_GROUP if mode == MODE_STUDENT else ENTITY_TEACHER
    logger.info(f"⭐ [{user_id}] @{username} → Устанавливает {mode_text} по умолчанию из расписания: '{query}'")

    # Применяем установку по умолчанию
    await _apply_default_selection(update, context, query, mode, source="schedule")

    # Показываем уведомление
    await safe_answer_callback_query(
        update.callback_query,
        f"✅ {mode_text.capitalize()} '{query}' установлена по умолчанию!",
        show_alert=False
    )

    # Обновляем расписание, чтобы скрыть кнопку "Установить по умолчанию"
    # Восстанавливаем состояние для обновления
    user_data[CTX_MODE] = mode
    user_data[CTX_LAST_QUERY] = query
    if user_data.get(CTX_SCHEDULE_PAGES):
        await send_schedule_with_pagination(update, context)
    else:
        # Если страниц нет, загружаем заново
        await fetch_and_display_schedule(update, context, query)


async def handle_cancel_input(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Обработка отмены ввода"""
    user_data = context.user_data
    awaiting_manual = user_data.pop(CTX_AWAITING_MANUAL_DATE, None)
    awaiting_default = user_data.pop(CTX_AWAITING_DEFAULT_QUERY, None)
    user_data.pop(CTX_IS_BUSY, None)
    # Очищаем pending queries
    for key in list(user_data.keys()):
        if key.startswith("pending_query_"):
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


async def handle_view_changed_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Обработка просмотра измененного расписания"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    parts = data.replace("view_changed_schedule_", "").split("_", 1)
    if len(parts) == 2:
        mode, date_str = parts[0], parts[1]
        logger.info(f"👁️ [{user_id}] @{username} → Просмотр измененного расписания на {date_str}")
        user_data = context.user_data
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


async def handle_mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Обработка выбора режима (студент/преподаватель)"""
    user_data = context.user_data
    mode = MODE_STUDENT if data == CALLBACK_DATA_MODE_STUDENT else MODE_TEACHER
    mode_text = ENTITY_STUDENT if mode == MODE_STUDENT else ENTITY_TEACHER
    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    logger.info(f"🎯 [{user_id}] @{username} → Выбран режим: {mode_text}")
    user_data[CTX_MODE] = mode

    # ВАЖНО: Явно сбрасываем CTX_AWAITING_DEFAULT_QUERY, если он был установлен ранее
    # Это делается только в handle_set_default_mode (когда пользователь нажимает "Установить/изменить" в настройках)
    # Здесь пользователь просто хочет посмотреть расписание, а не устанавливать группу по умолчанию
    user_data.pop(CTX_AWAITING_DEFAULT_QUERY, None)

    entity_text = "группу" if mode == MODE_STUDENT else "преподавателя"
    prompt = (
        f"✅ Режим установлен: {mode_text}\n\n"
        f"Теперь вы можете искать расписание для любой {entity_text}.\n"
        f"Просто введите название {entity_text}.\n\n"
        f"💡 Чтобы установить {entity_text} по умолчанию для уведомлений, "
        f"используйте кнопку «⚙️ Настройки» в главном меню."
    )
    kbd = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ В главное меню", callback_data=CALLBACK_DATA_BACK_TO_START)]])
    await safe_edit_message_text(update.callback_query, prompt, reply_markup=kbd)


async def handle_back_to_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Возврат к расписанию из экспорта"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"
    user_data = context.user_data
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


async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Инлайн-поиск групп/преподавателей и вставка расписания на сегодня.
    Форматы запроса:
    - "г <текст>" или без префикса — поиск групп
    - "п <текст>" — поиск преподавателей
    """
    from telegram import InlineQueryResultArticle, InputTextMessageContent
    from ..schedule import search_entities
    from ..utils import escape_html
    from .schedule import safe_get_schedule

    user_id = update.inline_query.from_user.id

    # Проверяем статус бота (кроме админов)
    if not is_admin(user_id) and not is_bot_enabled():
        await update.inline_query.answer([], cache_time=1, is_personal=True)
        return

    username = update.inline_query.from_user.username or "без username"
    query_text = (update.inline_query.query or "").strip()

    if not query_text:
        await update.inline_query.answer([], cache_time=5, is_personal=True)
        return

    logger.debug(f"🔍 [{user_id}] @{username} → Inline поиск: '{query_text[:50]}{'...' if len(query_text) > 50 else ''}'")

    # Умное определение типа сущности
    entity_type = None
    search_text = query_text
    found = None
    err = None

    # Сначала пробуем определить автоматически через detect_query_type
    query_type_result = detect_query_type(query_text)
    if query_type_result:
        from ..constants import API_TYPE_GROUP, API_TYPE_TEACHER, MODE_STUDENT
        entity_type = API_TYPE_GROUP if query_type_result[0] == MODE_STUDENT else API_TYPE_TEACHER
        search_text = query_type_result[1]
        found, err = await search_entities(search_text, entity_type)
        # Если не нашли с определенным типом, пробуем противоположный
        if not found or err:
            entity_type = API_TYPE_TEACHER if entity_type == API_TYPE_GROUP else API_TYPE_GROUP
            found, err = await search_entities(search_text, entity_type)
    else:
        # Если не удалось определить автоматически, пробуем оба варианта
        # Сначала группы (более частый случай)
        from ..constants import API_TYPE_GROUP, API_TYPE_TEACHER
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

    logger.debug(f"✅ [{user_id}] Inline поиск: найдено {len(found)} результатов (тип: {entity_type})")
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


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Оптимизированный роутер для callback queries с улучшенной обработкой ошибок
    """
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

    logger.debug(f"🔍 callback_router: получен callback '{data}' от пользователя {user_id}")

    # Валидация callback data
    if not validate_callback_data(data):
        logger.warning(f"⚠️ [{user_id}] Некорректные данные callback: {data[:50]}")
        await safe_answer_callback_query(update.callback_query, "Ошибка: некорректные данные", show_alert=True)
        return

    # Проверяем, не админский ли это callback (ранняя проверка для оптимизации)
    from ..admin.handlers import admin_callback_router

    # Обработка админских callback'ов
    if data.startswith("admin_"):
        try:
            await admin_callback_router(update, context)
        except Exception as e:
            logger.error(f"Ошибка в admin_callback_router: {e}", exc_info=True)
            await safe_answer_callback_query(update.callback_query, "Ошибка обработки команды", show_alert=True)
            clear_temporary_states(user_data)
        return

    # Обработка ответов пользователя администратору
    if data.startswith(CALLBACK_USER_REPLY_ADMIN_PREFIX):
        admin_id_str = data.replace(CALLBACK_USER_REPLY_ADMIN_PREFIX, "", 1)
        try:
            admin_id = int(admin_id_str)
            await start_user_reply_to_admin(update, context, admin_id)
        except (ValueError, TypeError):
            await safe_answer_callback_query(update.callback_query, "Администратор не найден", show_alert=True)
        except Exception as e:
            logger.error(f"Ошибка при обработке ответа администратору: {e}", exc_info=True)
            await safe_answer_callback_query(update.callback_query, "Ошибка обработки", show_alert=True)
        return

    if data.startswith(CALLBACK_USER_DISMISS_ADMIN_PREFIX):
        admin_id_str = data.replace(CALLBACK_USER_DISMISS_ADMIN_PREFIX, "", 1)
        try:
            admin_id = int(admin_id_str)
            await handle_user_dismiss_admin_message(update, context, admin_id)
        except (ValueError, TypeError):
            await safe_answer_callback_query(update.callback_query, "Действие недоступно", show_alert=True)
        except Exception as e:
            logger.error(f"Ошибка при закрытии уведомления: {e}", exc_info=True)
            await safe_answer_callback_query(update.callback_query, "Ошибка обработки", show_alert=True)
        return

    # Проверяем статус бота (кроме админов) - кешируем результат
    is_admin_user = is_admin(user_id)
    if not is_admin_user and not is_bot_enabled():
        maintenance_msg = get_maintenance_message()
        await safe_answer_callback_query(update.callback_query, maintenance_msg, show_alert=True)
        return

    logger.debug(f"🔘 [{user_id}] @{username} → Callback: '{data}'")

    # Проверяем блокировку (оптимизировано)
    if safe_get_user_data(user_data, CTX_IS_BUSY, False) and not data.startswith("cancel"):
        await safe_answer_callback_query(update.callback_query, "⏳ Пожалуйста, подождите...")
        return

    # Отвечаем на callback сразу (оптимизация UX), кроме случаев,
    # где обработчик сам отправляет текстовый ответ (feedback, toggle_daily_notifications).
    if data not in {CALLBACK_DATA_FEEDBACK, CALLBACK_DATA_TOGGLE_DAILY}:
        await safe_answer_callback_query(update.callback_query)

    # Словарь для точных совпадений (Direct Match)
    # Прямая ссылка на функцию, без lambda, так как сигнатуры совпадают
    HANDLERS = {
        CALLBACK_DATA_MODE_STUDENT: handle_mode_selection,
        CALLBACK_DATA_MODE_TEACHER: handle_mode_selection,
        CALLBACK_DATA_BACK_TO_START: lambda u, c, d: start_command(u, c),  # start_command принимает 2 аргумента
        CallbackData.HELP_COMMAND_INLINE.value: lambda u, c, d: help_command_handler(u, c),  # принимает 2
        "help_command_inline": lambda u, c, d: help_command_handler(u, c),
        CALLBACK_DATA_SETTINGS_MENU: lambda u, c, d: settings_menu_callback(u, c),  # принимает 2
        CALLBACK_DATA_RESET_SETTINGS: handle_reset_confirm,
        CALLBACK_DATA_DO_RESET_SETTINGS: handle_reset_execute,
        CALLBACK_DATA_TOGGLE_DAILY: lambda u, c, d: toggle_daily_notifications_callback(u, c),  # принимает 2
        CALLBACK_DATA_SET_NOTIFICATION_TIME: lambda u, c, d: show_notification_time_menu(u, c),  # принимает 2
        CALLBACK_DATA_CANCEL_INPUT: handle_cancel_input,
        CALLBACK_DATA_FEEDBACK: feedback_callback,
        CallbackData.BACK_TO_SCHEDULE.value: handle_back_to_schedule,
        "back_to_schedule_from_export": handle_back_to_schedule,
    }

    # Обработка точных совпадений
    if data in HANDLERS:
        handler = HANDLERS[data]
        try:
            # Используем context manager для длительных операций
            if data not in [CALLBACK_DATA_CANCEL_INPUT, CALLBACK_DATA_BACK_TO_START]:
                with user_busy_context(user_data):
                    try:
                        await handler(update, context, data)
                    except TypeError:
                        # Если функция принимает только 2 аргумента
                        await handler(update, context)
            else:
                # Для быстрых операций не используем блокировку
                try:
                    await handler(update, context, data)
                except TypeError:
                    # Если функция принимает только 2 аргумента
                    await handler(update, context)
        except Exception as e:
            user_id = update.effective_user.id if update.effective_user else "unknown"
            logger.error(f"❌ Ошибка в обработчике callback '{data}' для пользователя {user_id}: {e}", exc_info=True)
            try:
                await safe_answer_callback_query(
                    update.callback_query,
                    "Произошла ошибка при обработке команды",
                    show_alert=True
                )
            except Exception as answer_error:
                logger.error(f"Ошибка при ответе на callback query: {answer_error}")
            clear_temporary_states(user_data)
            # Убеждаемся, что блокировка снята
            clear_user_busy_state(user_data)
        return

    # Список префиксов для динамических данных (порядок важен, если префиксы пересекаются)
    PREFIXES = [
        (CALLBACK_DATA_EXPORT_MENU, show_export_menu),
        (CALLBACK_DATA_EXPORT_WEEK_IMAGE, export_week_schedule_image),
        (CALLBACK_DATA_EXPORT_WEEK_FILE, export_week_schedule_file),
        (CALLBACK_DATA_EXPORT_DAYS_IMAGES + "_", export_days_images),
        (CALLBACK_DATA_EXPORT_SEMESTER + "_", export_semester_excel),
        ("set_default_mode_", handle_set_default_mode),
        ("set_default_from_schedule_", handle_set_default_from_schedule),
        ("quick_schedule_", handle_quick_schedule),
        (CALLBACK_DATA_CONFIRM_MODE, handle_confirm_mode),
        (CALLBACK_DATA_NOTIFICATION_OPEN_PREFIX, handle_notification_open_callback),
        (f"{CALLBACK_DATA_DATE_TODAY}_quick_", handle_quick_date_callback),
        (f"{CALLBACK_DATA_DATE_TOMORROW}_quick_", handle_quick_date_callback),
        (f"{CALLBACK_DATA_DATE_TODAY}_", handle_quick_date_callback),
        (f"{CALLBACK_DATA_DATE_TOMORROW}_", handle_quick_date_callback),
        ("set_time_", set_notification_time),
        ("view_changed_schedule_", handle_view_changed_schedule),
        (CALLBACK_DATA_PREV_SCHEDULE_PREFIX, lambda u, c, d: schedule_navigation_callback(u, c)),
        (CALLBACK_DATA_NEXT_SCHEDULE_PREFIX, lambda u, c, d: schedule_navigation_callback(u, c)),
        (CALLBACK_DATA_REFRESH_SCHEDULE_PREFIX, lambda u, c, d: schedule_navigation_callback(u, c)),
    ]

    # Обработка префиксов
    for prefix, handler in PREFIXES:
        if data.startswith(prefix):
            logger.debug(f"🔍 Найден префикс '{prefix}' для callback '{data[:50]}...', вызываю handler: {handler.__name__}")
            try:
                # Функции экспорта сами управляют блокировкой через user_busy_context
                # Не используем внешний user_busy_context для них
                handlers_with_own_busy_context = [
                    export_days_images, export_week_schedule_image,
                    export_week_schedule_file, export_semester_excel
                ]

                if handler in handlers_with_own_busy_context:
                    # Эти функции сами управляют блокировкой
                    try:
                        await handler(update, context, data)
                    except TypeError:
                        # Если функция принимает только 2 аргумента
                        await handler(update, context)
                else:
                    # Используем context manager для автоматического управления блокировкой
                    with user_busy_context(user_data):
                        try:
                            await handler(update, context, data)
                        except TypeError:
                            # Если функция принимает только 2 аргумента
                            await handler(update, context)
            except Exception as e:
                user_id = update.effective_user.id if update.effective_user else "unknown"
                logger.error(f"❌ Ошибка в обработчике префикса '{prefix}' (callback: '{data[:50]}...') для пользователя {user_id}: {e}", exc_info=True)
                try:
                    await safe_answer_callback_query(
                        update.callback_query,
                        "Произошла ошибка при обработке команды",
                        show_alert=True
                    )
                except Exception as answer_error:
                    logger.error(f"Ошибка при ответе на callback query: {answer_error}")
                clear_temporary_states(user_data)
                # Убеждаемся, что блокировка снята
                clear_user_busy_state(user_data)
            return

    # Неизвестный callback
    logger.warning(f"⚠️ [{user_id}] Неизвестный callback: {data}")
    await safe_answer_callback_query(update.callback_query, "Неизвестная команда", show_alert=True)

