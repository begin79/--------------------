"""
Обработчики callback-запросов и inline-запросов
"""
import asyncio
import logging
import datetime
from telegram import Update, InlineQueryResultArticle, InputTextMessageContent, InputMediaPhoto, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .constants import (
    CALLBACK_DATA_MODE_STUDENT, CALLBACK_DATA_MODE_TEACHER,
    CALLBACK_DATA_SETTINGS_MENU, CALLBACK_DATA_BACK_TO_START,
    CALLBACK_DATA_TOGGLE_DAILY, CALLBACK_DATA_SET_NOTIFICATION_TIME,
    CALLBACK_DATA_FEEDBACK, CALLBACK_DATA_RESET_SETTINGS, CALLBACK_DATA_DO_RESET_SETTINGS,
    CALLBACK_DATA_EXPORT_MENU, CALLBACK_DATA_EXPORT_WEEK_TEXT, CALLBACK_DATA_EXPORT_WEEK_IMAGE,
    CALLBACK_DATA_EXPORT_WEEK_FILE, CALLBACK_DATA_EXPORT_DAY_IMAGE, CALLBACK_DATA_EXPORT_DAYS_IMAGES,
    CALLBACK_DATA_EXPORT_SEMESTER, CALLBACK_DATA_BACK_TO_SCHEDULE,
    CALLBACK_DATA_PREV_SCHEDULE_PREFIX, CALLBACK_DATA_NEXT_SCHEDULE_PREFIX,
    CALLBACK_DATA_REFRESH_SCHEDULE_PREFIX, CALLBACK_DATA_DATE_PREFIX,
    CALLBACK_DATA_NOTIFICATION_OPEN_PREFIX, CALLBACK_DATA_CANCEL_INPUT,
    CALLBACK_DATA_CONFIRM_MODE, CallbackData, CallbackPrefix,
    CTX_DEFAULT_QUERY, CTX_DEFAULT_MODE, CTX_SELECTED_DATE, CTX_LAST_QUERY,
    CTX_SCHEDULE_PAGES, CTX_CURRENT_PAGE_INDEX, CTX_MODE,
    CTX_NOTIFICATION_TIME, CTX_DAILY_NOTIFICATIONS, DEFAULT_NOTIFICATION_TIME,
    CTX_AWAITING_DEFAULT_QUERY, CTX_AWAITING_FEEDBACK, CTX_KEYBOARD_MESSAGE_ID,
    API_TYPE_GROUP, API_TYPE_TEACHER, MODE_STUDENT, MODE_TEACHER, ENTITY_GROUP, ENTITY_TEACHER,
    MAX_INLINE_RESULTS,
)
from .utils import escape_html
from .admin.handlers import admin_callback_router
from .admin.utils import is_admin
from .handlers.start import start_command
from .handlers.settings import settings_menu_callback
from .handlers.settings import handle_reset_confirm
from .handlers.notifications import toggle_daily_notifications_callback, set_notification_time, handle_notification_open_callback
from .handlers.schedule import schedule_navigation_callback
# Функции экспорта
from .export import generate_week_schedule_file, generate_schedule_image, get_week_schedule_structured, get_day_schedule_structured, generate_day_schedule_image
from .schedule import search_entities

logger = logging.getLogger(__name__)


async def _send_export_success_message(bot, chat_id: int, query: str, user_data: dict):
    """
    Отправляет сообщение с кнопками навигации после успешного экспорта.
    """
    text = "✅ Файл успешно сгенерирован. Вернуться к просмотру?"
    
    # Проверяем, есть ли сохраненное расписание для возврата
    has_schedule = bool(user_data.get(CTX_LAST_QUERY) and user_data.get(CTX_SCHEDULE_PAGES))
    
    keyboard_buttons = []
    if has_schedule:
        # Если есть сохраненное расписание, добавляем кнопку возврата к нему
        keyboard_buttons.append([
            InlineKeyboardButton("📅 К расписанию", callback_data=CALLBACK_DATA_BACK_TO_SCHEDULE)
        ])
    keyboard_buttons.append([
        InlineKeyboardButton("🏠 В меню", callback_data=CALLBACK_DATA_BACK_TO_START)
    ])
    
    keyboard = InlineKeyboardMarkup(keyboard_buttons)
    
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения о успешном экспорте: {e}", exc_info=True)


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Главный роутер для всех callback-запросов
    Направляет запросы в соответствующие обработчики
    """
    if not update.callback_query:
        return

    data = update.callback_query.data

    # Админские callback'и обрабатываются отдельно
    # Проверяем, является ли пользователь администратором
    user_is_admin = False
    if update.effective_user:
        from .admin.utils import is_admin as check_is_admin
        user_is_admin = check_is_admin(update.effective_user.id)
    
    if data.startswith("admin_") or (update.effective_user and user_is_admin and data in [
        "admin_menu", "admin_stats", "admin_bot_status", "admin_toggle_bot",
        "admin_set_maintenance_msg", "admin_users", "admin_cache", "admin_logs",
        "admin_broadcast", "admin_add_admin", "admin_remove_admin", "admin_list_admins",
        "admin_feedback", "admin_exit"
    ]):
        await admin_callback_router(update, context)
        return

    # Обработка основных callback'ов
    try:
        if data == CALLBACK_DATA_MODE_STUDENT:
            from .handlers.schedule import handle_mode_selection
            await handle_mode_selection(update, context, MODE_STUDENT)
        elif data == CALLBACK_DATA_MODE_TEACHER:
            from .handlers.schedule import handle_mode_selection
            await handle_mode_selection(update, context, "teacher")
        elif data == CALLBACK_DATA_BACK_TO_START:
            await start_command(update, context)
        elif data == CALLBACK_DATA_BACK_TO_SCHEDULE:
            # Возврат к расписанию из меню экспорта
            from .handlers.schedule import send_schedule_with_pagination
            await send_schedule_with_pagination(update, context)
        elif data == CALLBACK_DATA_SETTINGS_MENU:
            await settings_menu_callback(update, context)
        elif data == CALLBACK_DATA_TOGGLE_DAILY:
            await toggle_daily_notifications_callback(update, context)
        elif data == CALLBACK_DATA_SET_NOTIFICATION_TIME:
            from .handlers.notifications import show_notification_time_menu
            await show_notification_time_menu(update, context)
        elif data.startswith("set_time_"):
            await set_notification_time(update, context, data)
        elif data == CALLBACK_DATA_FEEDBACK:
            # Обработка отзывов
            await handle_feedback_callback(update, context)
        elif data == CallbackData.HELP_COMMAND_INLINE.value:
            # Обработка кнопки "Помощь"
            from .handlers.help import help_command_handler
            await help_command_handler(update, context)
        elif data == CALLBACK_DATA_RESET_SETTINGS:
            # Показываем подтверждение сброса настроек
            await handle_reset_confirm(update, context, data)
        elif data == CALLBACK_DATA_DO_RESET_SETTINGS:
            # Выполняем сброс настроек
            from .handlers.settings import handle_reset_execute
            await handle_reset_execute(update, context, data)
        elif data.startswith(CALLBACK_DATA_EXPORT_MENU + "_") or \
             data == CALLBACK_DATA_EXPORT_MENU or \
             data.startswith(CALLBACK_DATA_EXPORT_WEEK_IMAGE) or \
             data.startswith(CALLBACK_DATA_EXPORT_WEEK_FILE) or \
             data.startswith(CALLBACK_DATA_EXPORT_DAYS_IMAGES) or \
             data.startswith(CALLBACK_DATA_EXPORT_SEMESTER):
            # Обработка экспорта
            await handle_export_callback(update, context, data)
        elif data.startswith("user_reply_admin_") or data == "user_reply_broadcast":
            # Обработка ответа пользователя администратору
            from .admin.handlers import CALLBACK_USER_REPLY_ADMIN_PREFIX, CALLBACK_USER_REPLY_BROADCAST
            from .handlers.admin_dialogs import process_user_reply_to_admin_message
            from .admin.utils import get_root_admin_id
            from .handlers.utils import safe_answer_callback_query
            
            user_id = update.effective_user.id if update.effective_user else None
            if not user_id:
                await safe_answer_callback_query(update.callback_query, "❌ Ошибка: не удалось определить пользователя", show_alert=True)
                return
            
            # Определяем, кому отвечать
            if data == "user_reply_broadcast":
                # Ответ на массовую рассылку - отправляем корневому админу
                admin_id = get_root_admin_id()
                if not admin_id:
                    await safe_answer_callback_query(update.callback_query, "❌ Администратор недоступен", show_alert=True)
                    return
                
                # Устанавливаем состояние ожидания ответа
                reply_states = context.application.bot_data.setdefault("admin_reply_states", {})
                reply_states[user_id] = {"admin_id": admin_id, "from_broadcast": True}
                
                await safe_answer_callback_query(update.callback_query, "✉️ Теперь напишите ваш ответ")
                await update.callback_query.message.reply_text(
                    "✉️ <b>Ответ на сообщение от команды</b>\n\n"
                    "Напишите ваш ответ. Ваше сообщение будет отправлено администратору.\n\n"
                    "Для отмены отправьте: <code>отмена</code>",
                    parse_mode=ParseMode.HTML
                )
            else:
                # Ответ конкретному админу
                admin_id_str = data.replace(CALLBACK_USER_REPLY_ADMIN_PREFIX, "")
                try:
                    admin_id = int(admin_id_str)
                except (ValueError, TypeError):
                    await safe_answer_callback_query(update.callback_query, "❌ Ошибка: неверный ID администратора", show_alert=True)
                    return
                
                # Проверяем, что администратор существует
                from .admin.utils import is_admin
                if not is_admin(admin_id):
                    await safe_answer_callback_query(update.callback_query, "❌ Администратор не найден", show_alert=True)
                    return
                
                # Устанавливаем состояние ожидания ответа
                reply_states = context.application.bot_data.setdefault("admin_reply_states", {})
                reply_states[user_id] = {"admin_id": admin_id, "from_message": True}
                
                await safe_answer_callback_query(update.callback_query, "✉️ Теперь напишите ваш ответ")
                await update.callback_query.message.reply_text(
                    f"✉️ <b>Ответ администратору</b>\n\n"
                    f"Напишите ваш ответ. Ваше сообщение будет отправлено администратору.\n\n"
                    f"Для отмены отправьте: <code>отмена</code>",
                    parse_mode=ParseMode.HTML
                )
        elif data.startswith("user_dismiss_admin_"):
            # Обработка кнопки "Спасибо" / "Понятно"
            from .handlers.utils import safe_answer_callback_query
            
            # Отвечаем на callback
            await safe_answer_callback_query(update.callback_query, "✅ Хорошо!")
            
            # Открываем меню (/start) - используем глобальный импорт start_command
            try:
                await start_command(update, context)
            except Exception as e:
                logger.error(f"Ошибка при открытии меню после нажатия 'Спасибо': {e}", exc_info=True)
        elif data.startswith(CALLBACK_DATA_PREV_SCHEDULE_PREFIX) or \
             data.startswith(CALLBACK_DATA_NEXT_SCHEDULE_PREFIX) or \
             data.startswith(CALLBACK_DATA_REFRESH_SCHEDULE_PREFIX):
            await schedule_navigation_callback(update, context)
        elif data.startswith(CALLBACK_DATA_DATE_PREFIX):
            # Обработка выбора даты - будет реализовано позже
            from .handlers.utils import safe_answer_callback_query
            await safe_answer_callback_query(update.callback_query, "Выбор даты")
            await start_command(update, context)
        elif data.startswith(CALLBACK_DATA_NOTIFICATION_OPEN_PREFIX):
            await handle_notification_open_callback(update, context, data)
        elif data.startswith(CallbackPrefix.VIEW_CHANGED_SCHEDULE.value):
            # Обработка просмотра измененного расписания из уведомления
            from .handlers.utils import safe_answer_callback_query, safe_edit_message_text
            from .handlers.schedule import send_schedule_with_pagination
            
            if not update.callback_query:
                return
            
            await safe_answer_callback_query(update.callback_query, "Загружаю расписание...")
            
            # Извлекаем mode и date из callback_data: "view_changed_schedule_student_2026-01-14"
            prefix = CallbackPrefix.VIEW_CHANGED_SCHEDULE.value
            if not data.startswith(prefix):
                logger.error(f"Неверный формат callback для просмотра измененного расписания: {data}")
                await update.callback_query.answer("Ошибка: неверный формат команды", show_alert=True)
                return
            
            # Убираем префикс и разделяем по последнему подчеркиванию перед датой
            rest = data[len(prefix):]  # "student_2026-01-14"
            # Ищем последнее подчеркивание перед датой (дата всегда в формате YYYY-MM-DD)
            if "_" not in rest:
                logger.error(f"Неверный формат callback для просмотра измененного расписания: {data}")
                await update.callback_query.answer("Ошибка: неверный формат команды", show_alert=True)
                return
            
            # Разделяем по первому подчеркиванию (mode_date)
            parts = rest.split("_", 1)
            if len(parts) != 2:
                logger.error(f"Неверный формат callback для просмотра измененного расписания: {data}")
                await update.callback_query.answer("Ошибка: неверный формат команды", show_alert=True)
                return
            
            default_mode = parts[0]  # "student" или "teacher"
            date_str = parts[1]  # "2026-01-14"
            user_id = update.effective_user.id if update.effective_user else None
            
            if not user_id:
                await update.callback_query.answer("Ошибка: не удалось определить пользователя", show_alert=True)
                return
            
            # Получаем сохраненные данные расписания
            schedule_key = f"changed_schedule_{user_id}_{date_str}"
            schedule_data = context.bot_data.get(schedule_key)
            
            if not schedule_data:
                # Если данных нет в кеше, пытаемся получить из настроек пользователя
                user_data = context.user_data
                query = user_data.get(CTX_DEFAULT_QUERY)
                mode = user_data.get(CTX_DEFAULT_MODE) or default_mode
                
                if not query:
                    await update.callback_query.answer("❌ Группа/преподаватель не установлены", show_alert=True)
                    await start_command(update, context)
                    return
                
                # Загружаем расписание заново
                from .handlers.schedule import safe_get_schedule
                api_type = API_TYPE_GROUP if mode == MODE_STUDENT else API_TYPE_TEACHER
                pages, err = await safe_get_schedule(date_str, query, api_type, bot=context.bot)
                
                if err or not pages:
                    await update.callback_query.answer(f"❌ Не удалось загрузить расписание: {err or 'Не найдено'}", show_alert=True)
                    return
                
                schedule_data = {
                    "query": query,
                    "mode": mode,
                    "date": date_str,
                    "pages": pages
                }
            
            # Устанавливаем контекст для отображения расписания
            user_data = context.user_data
            user_data[CTX_LAST_QUERY] = schedule_data["query"]
            user_data[CTX_MODE] = schedule_data["mode"]
            user_data[CTX_SELECTED_DATE] = schedule_data["date"]
            user_data[CTX_SCHEDULE_PAGES] = schedule_data["pages"]
            user_data[CTX_CURRENT_PAGE_INDEX] = 0
            
            # Показываем расписание
            try:
                await send_schedule_with_pagination(update, context, msg_to_edit=update.callback_query.message)
            except Exception as e:
                logger.error(f"Ошибка при показе измененного расписания: {e}", exc_info=True)
                await update.callback_query.answer("❌ Ошибка при загрузке расписания", show_alert=True)
        elif data == CALLBACK_DATA_CANCEL_INPUT:
            from .handlers.utils import safe_answer_callback_query
            
            # Очищаем все состояния ожидания ввода через менеджер
            user_data = context.user_data
            manager = get_state_manager(user_data)
            manager.clear_state(UserState.AWAITING_DEFAULT_QUERY)
            manager.clear_state(UserState.AWAITING_FEEDBACK)
            
            await safe_answer_callback_query(update.callback_query, "Отменено")
            
            # Удаляем сообщение со стикером клавиатуры, если оно было отправлено
            keyboard_message_id = user_data.pop(CTX_KEYBOARD_MESSAGE_ID, None)
            if keyboard_message_id and update.callback_query.message:
                try:
                    await context.bot.delete_message(
                        chat_id=update.callback_query.message.chat_id,
                        message_id=keyboard_message_id
                    )
                except Exception as e:
                    logger.debug(f"Ошибка при удалении сообщения со стикером: {e}")
            
            # Удаляем Reply-клавиатуру, редактируя последнее сообщение бота
            try:
                if update.callback_query.message:
                    # Пытаемся отредактировать последнее сообщение, чтобы убрать клавиатуру
                    try:
                        await context.bot.edit_message_reply_markup(
                            chat_id=update.callback_query.message.chat_id,
                            message_id=update.callback_query.message.message_id,
                            reply_markup=None
                        )
                    except Exception:
                        # Если не получилось отредактировать, отправляем пустое сообщение для удаления клавиатуры
                        temp_msg = await update.callback_query.message.reply_text(" ", reply_markup=ReplyKeyboardRemove())
                        await asyncio.sleep(0.2)
                        try:
                            await context.bot.delete_message(
                                chat_id=update.callback_query.message.chat_id,
                                message_id=temp_msg.message_id
                            )
                        except Exception:
                            pass
            except Exception as e:
                logger.debug(f"Ошибка при удалении Reply-клавиатуры: {e}")
            
            await start_command(update, context)
        elif data.startswith(CALLBACK_DATA_CONFIRM_MODE):
            # Обработка подтверждения режима - будет реализовано позже
            from .handlers.utils import safe_answer_callback_query
            await safe_answer_callback_query(update.callback_query, "Режим подтвержден")
            await start_command(update, context)
        elif data.startswith("quick_schedule_"):
            # Быстрый показ расписания для установленной группы/преподавателя
            from .handlers.utils import safe_answer_callback_query, user_busy_context
            from .handlers.schedule import send_schedule_with_pagination, safe_get_schedule
            
            if not update.callback_query:
                return
            
            # Извлекаем mode из callback_data
            mode_str = data.replace("quick_schedule_", "")
            mode = MODE_STUDENT if mode_str == "student" else "teacher"
            
            user_data = context.user_data
            # При входе в просмотр расписания сбрасываем режим ожидания отзыва,
            # чтобы "призрак" отзыва не перехватывал ввод пользователя.
            manager = get_state_manager(user_data)
            if manager.has_state(UserState.AWAITING_FEEDBACK):
                manager.clear_state(UserState.AWAITING_FEEDBACK)
            query = user_data.get(CTX_DEFAULT_QUERY)
            default_mode = user_data.get(CTX_DEFAULT_MODE)
            
            # Используем mode из callback или из настроек
            if not default_mode or default_mode != mode:
                mode = default_mode or mode
            
            if not query:
                await safe_answer_callback_query(update.callback_query, "❌ Группа/преподаватель не установлены. Выберите в настройках.", show_alert=True)
                await start_command(update, context)
                return
            
            # Устанавливаем текущую дату
            today = datetime.date.today()
            date_str = today.strftime("%Y-%m-%d")
            
            user_data[CTX_SELECTED_DATE] = date_str
            user_data[CTX_MODE] = mode
            user_data[CTX_LAST_QUERY] = query
            
            # Показываем индикатор загрузки
            try:
                from .handlers.utils import safe_edit_message_text
                await safe_edit_message_text(update.callback_query, "⏳ Загружаю расписание...", reply_markup=None)
            except Exception as e:
                logger.debug(f"Ошибка при редактировании сообщения: {e}", exc_info=True)
            
            # Загружаем расписание
            api_type = API_TYPE_GROUP if mode == MODE_STUDENT else API_TYPE_TEACHER
            
            async with user_busy_context(user_data):
                pages, err = await safe_get_schedule(date_str, query, api_type, bot=context.bot)
                if err or not pages:
                    error_msg = f"❌ Не удалось получить расписание для '{query}': {err or 'Расписание не найдено'}"
                    try:
                        await update.callback_query.message.edit_text(error_msg, parse_mode=ParseMode.HTML)
                    except Exception as e:
                        logger.error(f"Ошибка при редактировании сообщения об ошибке: {e}")
                        try:
                            await update.callback_query.message.reply_text(error_msg, parse_mode=ParseMode.HTML)
                        except Exception as e2:
                            logger.error(f"Ошибка при отправке сообщения об ошибке: {e2}")
                    return
                
                user_data[CTX_SCHEDULE_PAGES] = pages
                user_data[CTX_CURRENT_PAGE_INDEX] = 0
                # Передаем сообщение для редактирования
                msg_to_edit = update.callback_query.message
                await send_schedule_with_pagination(update, context, msg_to_edit=msg_to_edit)
        elif data == "set_default_mode_student":
            # Установка группы по умолчанию
            from .handlers.schedule import handle_mode_selection
            await handle_mode_selection(update, context, MODE_STUDENT, for_default=True)
        elif data == "set_default_mode_teacher":
            # Установка преподавателя по умолчанию
            from .handlers.schedule import handle_mode_selection
            await handle_mode_selection(update, context, "teacher", for_default=True)
        elif data.startswith("set_default_from_schedule_"):
            # Установка по умолчанию из расписания
            from .handlers.utils import safe_answer_callback_query
            from .handlers.schedule import send_schedule_with_pagination
            from .utils import escape_html
            
            user_data = context.user_data
            
            # Извлекаем mode и query_hash из callback_data
            # Формат: set_default_from_schedule_{mode}_{query_hash}
            # query_hash всегда 12 символов (MD5 hex), mode - "student" или "teacher"
            prefix = "set_default_from_schedule_"
            if not data.startswith(prefix):
                logger.error(f"Неверный формат callback_data: {data}")
                await safe_answer_callback_query(update.callback_query, "❌ Ошибка: неверный формат команды", show_alert=True)
                return
            
            suffix = data[len(prefix):]
            # Разделяем на mode и query_hash используя split (без магических чисел)
            parts = suffix.split('_', 1)
            if len(parts) == 2:
                mode_str, query_hash = parts
                if mode_str == "student":
                    mode = "student"
                elif mode_str == "teacher":
                    mode = "teacher"
                else:
                    logger.error(f"Неверный формат callback_data (неизвестный mode): {data}")
                    await safe_answer_callback_query(update.callback_query, "❌ Ошибка: неверный формат команды", show_alert=True)
                    return
            else:
                logger.error(f"Неверный формат callback_data (не удалось разделить): {data}")
                await safe_answer_callback_query(update.callback_query, "❌ Ошибка: неверный формат команды", show_alert=True)
                return
            
            # Получаем query из user_data
            query_key = f"set_default_query_{query_hash}"
            mode_key = f"set_default_mode_{query_hash}"
            
            query = user_data.get(query_key)
            stored_mode = user_data.get(mode_key)
            
            if not query or stored_mode != mode:
                logger.error(f"Не найдены данные для установки по умолчанию: query_key={query_key}, mode_key={mode_key}")
                await safe_answer_callback_query(update.callback_query, "❌ Ошибка: данные не найдены", show_alert=True)
                return
            
            # Устанавливаем по умолчанию
            await safe_answer_callback_query(update.callback_query, "✅ Устанавливаю по умолчанию...")
            
            # Создаем временный update для _apply_default_selection
            # Но нам нужно обновить сообщение с расписанием, а не отправлять новое
            user_id = update.effective_user.id if update.effective_user else None
            username = update.effective_user.username if update.effective_user else None
            first_name = update.effective_user.first_name if update.effective_user else None
            last_name = update.effective_user.last_name if update.effective_user else None
            
            from .handlers.utils import save_user_data_to_db
            from .database import db
            
            # Сохраняем в user_data
            user_data[CTX_DEFAULT_QUERY] = query
            user_data[CTX_DEFAULT_MODE] = mode
            # ВАЖНО: Обновляем CTX_LAST_QUERY и CTX_MODE для send_schedule_with_pagination
            user_data[CTX_LAST_QUERY] = query
            user_data[CTX_MODE] = mode
            if not user_data.get(CTX_NOTIFICATION_TIME):
                user_data[CTX_NOTIFICATION_TIME] = DEFAULT_NOTIFICATION_TIME
            
            notifications_were_enabled = bool(user_data.get(CTX_DAILY_NOTIFICATIONS, False))
            user_data[CTX_DAILY_NOTIFICATIONS] = True
            
            # Сохраняем в БД
            save_user_data_to_db(
                user_id=user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                user_data=user_data,
            )
            if user_id:
                db.log_activity(user_id, "set_default_query", f"mode={mode}, query={query}")
                if not notifications_were_enabled:
                    db.log_activity(user_id, "auto_enable_notifications", f"mode={mode}")
            
            # Настраиваем уведомления
            chat_id = update.effective_chat.id if update.effective_chat else user_id
            from .handlers.notifications import schedule_daily_notifications
            schedule_daily_notifications(context, chat_id, user_data)
            
            # Обновляем список активных пользователей
            if user_id:
                if 'active_users' not in context.bot_data:
                    context.bot_data['active_users'] = set()
                if 'users_data_cache' not in context.bot_data:
                    context.bot_data['users_data_cache'] = {}
                
                context.bot_data['active_users'].add(user_id)
                context.bot_data['users_data_cache'][user_id] = {
                    CTX_DEFAULT_QUERY: query,
                    CTX_DEFAULT_MODE: mode,
                    CTX_DAILY_NOTIFICATIONS: True,
                    CTX_NOTIFICATION_TIME: user_data.get(CTX_NOTIFICATION_TIME, DEFAULT_NOTIFICATION_TIME)
                }
            
            # Обновляем сообщение с расписанием (кнопка "Установить по умолчанию" исчезнет)
            # Проверяем, что есть страницы расписания в user_data
            if not user_data.get(CTX_SCHEDULE_PAGES):
                logger.warning(f"Нет страниц расписания в user_data для обновления сообщения")
                # Если нет страниц, просто показываем сообщение об успехе
                time_str = user_data.get(CTX_NOTIFICATION_TIME, DEFAULT_NOTIFICATION_TIME)
                notif_text = (
                    f"🔔 Ежедневные уведомления уже были включены на {time_str}."
                    if notifications_were_enabled
                    else f"🔔 Ежедневные уведомления автоматически включены на {time_str}."
                )
                success_text = (
                    f"✅ Установлено по умолчанию: <b>{escape_html(query)}</b>\n"
                    f"{notif_text}"
                )
                try:
                    await update.callback_query.message.edit_text(success_text, parse_mode=ParseMode.HTML)
                except Exception as e2:
                    logger.error(f"Ошибка при обновлении сообщения об успехе: {e2}")
                    try:
                        await update.callback_query.message.reply_text(success_text, parse_mode=ParseMode.HTML)
                    except Exception as e3:
                        logger.error(f"Ошибка при отправке сообщения об успехе: {e3}")
                return
            
            try:
                await send_schedule_with_pagination(update, context, msg_to_edit=update.callback_query.message)
            except Exception as e:
                logger.error(f"Ошибка при обновлении расписания: {e}", exc_info=True)
                # Если не удалось обновить, показываем сообщение об успехе
                time_str = user_data.get(CTX_NOTIFICATION_TIME, DEFAULT_NOTIFICATION_TIME)
                notif_text = (
                    f"🔔 Ежедневные уведомления уже были включены на {time_str}."
                    if notifications_were_enabled
                    else f"🔔 Ежедневные уведомления автоматически включены на {time_str}."
                )
                success_text = (
                    f"✅ Установлено по умолчанию: <b>{escape_html(query)}</b>\n"
                    f"{notif_text}"
                )
                try:
                    await update.callback_query.message.reply_text(success_text, parse_mode=ParseMode.HTML)
                except Exception as e2:
                    logger.error(f"Ошибка при отправке сообщения об успехе: {e2}")
        else:
            # Проверяем, не является ли это устаревшим callback или callback от старой версии
            # Игнорируем некоторые известные паттерны, которые могут быть от старых версий
            known_old_patterns = [
                "teacher_photo_", "teacher_profile_",  # Старые callbacks для профилей преподавателей
            ]
            
            is_old_pattern = any(data.startswith(pattern) for pattern in known_old_patterns)
            
            if is_old_pattern:
                # Это устаревший callback, просто отвечаем без предупреждения
                logger.debug(f"Игнорирую устаревший callback: {data}")
                await update.callback_query.answer("Эта функция больше не поддерживается", show_alert=False)
            else:
                # Неизвестный callback - логируем как предупреждение для отладки
                logger.warning(f"Неизвестный callback: {data} (user_id: {update.effective_user.id if update.effective_user else 'unknown'})")
                try:
                    await update.callback_query.answer("Неизвестная команда", show_alert=False)
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"Ошибка при обработке callback {data}: {e}", exc_info=True)
        try:
            await update.callback_query.answer("Произошла ошибка", show_alert=True)
        except Exception:
            pass


async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик inline-запросов (поиск через @username бота)
    """
    if not update.inline_query:
        return

    query = update.inline_query.query.strip()
    user_id = update.inline_query.from_user.id

    logger.info(f"🔍 [{user_id}] Inline запрос: '{query}'")

    results = []

    if not query:
        # Если запрос пустой, показываем подсказку
        results.append(
            InlineQueryResultArticle(
                id="help",
                title="💡 Как использовать",
                description="Введите название группы (например: ИС1-231) или ФИО преподавателя",
                input_message_content=InputTextMessageContent(
                    "💡 Используйте inline-режим для быстрого поиска расписания!\n\n"
                    "Введите название группы или ФИО преподавателя после @Vgltu25_bot"
                )
            )
        )
    else:
        # Ищем группы и преподавателей и сразу готовим расписание на сегодня
        try:
            from .handlers.schedule import detect_query_type, safe_get_schedule
            import datetime as dt

            today = dt.date.today().strftime("%Y-%m-%d")

            async def _build_result(name: str, mode: str):
                """Формирует InlineQueryResultArticle с уже готовым расписанием на сегодня."""
                api_type = API_TYPE_GROUP if mode == MODE_STUDENT else API_TYPE_TEACHER
                pages, err = await safe_get_schedule(today, name, api_type, timeout=10.0, bot=context.bot)

                if err or not pages:
                    text = (
                        f"📅 <b>Расписание на сегодня для</b> {escape_html(name)}\n\n"
                        f"❌ Не удалось получить расписание: {escape_html(err or 'Расписание не найдено')}"
                    )
                else:
                    header = (
                        f"📅 <b>Расписание на сегодня</b>\n"
                        f"👤 <b>{escape_html(name)}</b>\n\n"
                    )
                    text = header + pages[0]

                return InlineQueryResultArticle(
                    id=f"{mode}_{name}",
                    title=name,
                    description=f"Расписание {'группы' if mode == MODE_STUDENT else 'преподавателя'} на сегодня",
                    input_message_content=InputTextMessageContent(
                        message_text=text,
                        parse_mode=ParseMode.HTML
                    )
                )

            # Определяем тип запроса
            query_type = detect_query_type(query)
            
            if query_type:
                mode, search_text = query_type
                api_type = API_TYPE_GROUP if mode == MODE_STUDENT else API_TYPE_TEACHER
                
                # Поиск сущностей (async функция!)
                found, _ = await search_entities(search_text, api_type)
                
                # Ограничиваем количество результатов
                if found:
                    found = found[:MAX_INLINE_RESULTS]
                else:
                    found = []
                
                for name in found:
                    results.append(await _build_result(name, mode))
            else:
                # Если тип не определен, ищем и в группах, и в преподавателях
                groups_res, _ = await search_entities(query, API_TYPE_GROUP)
                groups = groups_res[:5] if groups_res else []
                teachers_res, _ = await search_entities(query, API_TYPE_TEACHER)
                teachers = teachers_res[:5] if teachers_res else []
                
                for name in groups:
                    results.append(await _build_result(name, MODE_STUDENT))
                
                for name in teachers:
                    results.append(await _build_result(name, MODE_TEACHER))
        except Exception as e:
            logger.error(f"Ошибка при обработке inline-запроса: {e}", exc_info=True)

    # Отправляем результаты
    try:
        await update.inline_query.answer(results, cache_time=5)
    except Exception as e:
        logger.error(f"Ошибка при отправке inline-результатов: {e}", exc_info=True)


async def handle_feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик callback для кнопки "Оставить отзыв"
    Проверяет лимит 24 часа и устанавливает флаг ожидания отзыва
    """
    if not update.callback_query or not update.effective_user:
        return
    
    from .handlers.utils import safe_answer_callback_query, safe_edit_message_text
    from .database import db
    
    user_id = update.effective_user.id
    user_data = context.user_data
    manager = get_state_manager(user_data)
    
    # Проверяем, может ли пользователь оставить отзыв
    can_leave, seconds_left = db.can_leave_feedback(user_id)
    
    if not can_leave:
        # Показываем, сколько времени осталось ждать
        hours_left = seconds_left // 3600 if seconds_left else 0
        minutes_left = (seconds_left % 3600) // 60 if seconds_left else 0
        
        if hours_left > 0:
            time_msg = f"{hours_left} ч. {minutes_left} мин."
        else:
            time_msg = f"{minutes_left} мин."
        
        await safe_answer_callback_query(
            update.callback_query,
            f"⏱️ Вы уже оставляли отзыв недавно. Повторный отзыв можно оставить через {time_msg}.",
            show_alert=True
        )
        return
    
    # Устанавливаем состояние ожидания отзыва через менеджер
    # Менеджер автоматически очистит конфликтующие состояния
    manager.set_state(UserState.AWAITING_FEEDBACK)
    
    # Показываем сообщение с просьбой написать отзыв
    text = (
        "💬 <b>Оставить отзыв</b>\n\n"
        "Пожалуйста, напишите ваш отзыв о работе бота.\n"
        "Ваше мнение очень важно для нас!\n\n"
        "Для отмены отправьте: <code>отмена</code>"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_DATA_BACK_TO_START)]
    ])
    
    # Добавляем Reply-кнопку "Отмена" для удобства
    cancel_keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("❌ Отмена")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    
    await safe_answer_callback_query(update.callback_query, "Напишите ваш отзыв")
    await safe_edit_message_text(update.callback_query, text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    
    # Отправляем Reply-кнопку "Отмена" отдельным сообщением (без лишнего текста)
    try:
        await update.callback_query.message.reply_text(
            " ",
            reply_markup=cancel_keyboard
        )
    except Exception as e:
        logger.debug(f"Ошибка при отправке Reply-кнопки отмены: {e}", exc_info=True)


async def handle_export_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """
    Обработчик экспорта расписания (PDF и изображения)
    """
    if not update.callback_query or not update.effective_user:
        return
    
    from .handlers.utils import safe_answer_callback_query, user_busy_context, ExportProgress
    
    user_id = update.effective_user.id
    user_data = context.user_data
    
    # Извлекаем mode и query_hash из callback_data
    # Формат: export_week_file_{mode}_{query_hash} или export_week_image_{mode}_{query_hash}
    mode = None
    query = None
    
    # Проверяем префиксы экспорта
    if data.startswith(CallbackPrefix.EXPORT_WEEK_FILE.value):
        export_type = "pdf"
        suffix = data[len(CallbackPrefix.EXPORT_WEEK_FILE.value):]
    elif data.startswith(CallbackPrefix.EXPORT_WEEK_IMAGE.value):
        export_type = "image"
        suffix = data[len(CallbackPrefix.EXPORT_WEEK_IMAGE.value):]
    elif data.startswith(CallbackPrefix.EXPORT_DAYS_IMAGES.value):
        export_type = "days_images"
        suffix = data[len(CallbackPrefix.EXPORT_DAYS_IMAGES.value):]
    elif data.startswith(CallbackPrefix.EXPORT_SEMESTER.value):
        export_type = "excel"
        suffix = data[len(CallbackPrefix.EXPORT_SEMESTER.value):]
    elif data.startswith(CallbackPrefix.EXPORT_MENU.value):
        # Меню экспорта - показываем варианты
        await safe_answer_callback_query(update.callback_query, "Выберите формат экспорта")
        
        # Извлекаем mode и query_hash из callback_data
        # Формат: export_menu_{mode}_{query_hash}
        suffix = data[len(CallbackPrefix.EXPORT_MENU.value):]
        
        # Используем split вместо магических чисел
        parts = suffix.split('_', 1)
        if len(parts) == 2:
            mode_str, query_hash = parts
            if mode_str == "student":
                mode = MODE_STUDENT
            elif mode_str == "teacher":
                mode = MODE_TEACHER
            else:
                await safe_answer_callback_query(update.callback_query, "❌ Ошибка формата callback", show_alert=True)
                return
        else:
            await safe_answer_callback_query(update.callback_query, "❌ Ошибка формата callback", show_alert=True)
            return
        
        # Получаем query из user_data
        query_key = f"export_{mode}_{query_hash}"
        query = user_data.get(query_key)
        if not query:
            query = user_data.get(CTX_LAST_QUERY) or user_data.get(CTX_DEFAULT_QUERY)
        
        if not query:
            await safe_answer_callback_query(update.callback_query, "❌ Не найдены данные для экспорта", show_alert=True)
            return
        
        # Показываем меню выбора формата экспорта
        text = f"📤 <b>Экспорт расписания</b>\n\n"
        text += f"Группа/преподаватель: <code>{escape_html(query)}</code>\n\n"
        text += "Выберите формат экспорта:"
        
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📄 PDF неделя", callback_data=f"{CallbackPrefix.EXPORT_WEEK_FILE.value}{mode}_{query_hash}"),
                InlineKeyboardButton("🖼️ Изображение неделя", callback_data=f"{CallbackPrefix.EXPORT_WEEK_IMAGE.value}{mode}_{query_hash}")
            ],
            [
                InlineKeyboardButton("📊 Excel семестр", callback_data=f"{CallbackPrefix.EXPORT_SEMESTER.value}{mode}_{query_hash}"),
                InlineKeyboardButton("🖼️ Изображения по дням", callback_data=f"{CallbackPrefix.EXPORT_DAYS_IMAGES.value}{mode}_{query_hash}")
            ],
            [InlineKeyboardButton("⬅️ Назад к расписанию", callback_data=CALLBACK_DATA_BACK_TO_SCHEDULE)]
        ])
        
        from .handlers.utils import safe_edit_message_text
        await safe_edit_message_text(update.callback_query, text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        return
    else:
        await safe_answer_callback_query(update.callback_query, "❌ Неизвестный тип экспорта", show_alert=True)
        return
    
    # Извлекаем mode и query_hash из suffix (используем split вместо магических чисел)
    parts = suffix.split('_', 1)
    if len(parts) == 2:
        mode_str, query_hash = parts
        if mode_str == "student":
            mode = MODE_STUDENT
        elif mode_str == "teacher":
            mode = MODE_TEACHER
        else:
            mode = None
    else:
        mode = None
        query_hash = None
    
    if not mode or not query_hash:
        # Пытаемся получить из user_data (для обратной совместимости)
        query = user_data.get(CTX_LAST_QUERY) or user_data.get(CTX_DEFAULT_QUERY)
        mode = user_data.get(CTX_MODE) or user_data.get(CTX_DEFAULT_MODE)
        if not query or not mode:
            await safe_answer_callback_query(update.callback_query, "❌ Не найдены данные для экспорта", show_alert=True)
            return
    
    # Получаем query из user_data, если не получили выше
    if not query:
        query_key = f"export_{mode}_{query_hash}"
        query = user_data.get(query_key)
        if not query:
            # Пробуем получить из других источников
            query = user_data.get(CTX_LAST_QUERY) or user_data.get(CTX_DEFAULT_QUERY)
    
    if not query or not mode:
        await safe_answer_callback_query(update.callback_query, "❌ Не найдены данные для экспорта", show_alert=True)
        return
    
    # Определяем тип API
    api_type = API_TYPE_GROUP if mode == MODE_STUDENT else API_TYPE_TEACHER
    
    await safe_answer_callback_query(update.callback_query, "⏳ Генерирую экспорт...")
    
    # Используем user_busy_context для блокировки
    async with user_busy_context(user_data):
        try:
            # Показываем прогресс
            progress = ExportProgress(update.callback_query.message)
            await progress.start("📥 Загружаю расписание...")
            
            chat_id = update.effective_chat.id if update.effective_chat else user_id
            
            if export_type == "excel":
                # Экспорт в Excel (семестр)
                await progress.update(20, "📊 Загружаю расписание за семестр...")
                from excel_export.export_semester import fetch_semester_schedule, build_excel_workbook, resolve_semester_bounds
                import datetime as dt
                
                # Определяем текущий семестр
                today = dt.date.today()
                if today.month >= 9:
                    semester = "autumn"
                    year = today.year
                elif today.month >= 1 and today.month <= 4:
                    semester = "spring"
                    year = today.year
                else:
                    semester = "spring"
                    year = today.year
                
                # Получаем границы семестра
                start_date, end_date, semester_label = resolve_semester_bounds(semester, year, None, None)
                
                # Загружаем расписание за семестр (передаем bot для мониторинга)
                # ВАЖНО: fetch_semester_schedule использует свой семафор (8), но это нормально для долгой операции
                semester_data = await fetch_semester_schedule(query, api_type, start_date, end_date, bot=context.bot)
                
                if not semester_data:
                    await progress.finish("❌ Расписание за семестр не найдено", delete_after=3.0)
                    return
                
                await progress.update(60, "📊 Формирую Excel файл...")
                wb, _, _, _, _, _ = build_excel_workbook(
                    query, mode, semester_label, semester_data
                )
                
                await progress.update(80, "💾 Сохраняю файл...")
                from io import BytesIO
                excel_bytes = BytesIO()
                wb.save(excel_bytes)
                excel_bytes.seek(0)
                
                filename = f"schedule_{query}_{semester}_{year}.xlsx"
                caption = f"📊 Расписание за семестр для {query}"
                
                await progress.update(90, "📤 Отправляю файл...")
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=excel_bytes,
                    filename=filename,
                    caption=caption
                )
                
                # Отправляем сообщение с кнопками навигации после экспорта
                await _send_export_success_message(context.bot, chat_id, query, user_data)
                
            elif export_type == "days_images":
                # Экспорт по дням (изображения для каждого дня) - отправляем все вместе
                await progress.update(20, "📊 Загружаю расписание на неделю...")
                week_schedule = await get_week_schedule_structured(query, api_type)
                
                if not week_schedule:
                    await progress.finish("❌ Расписание не найдено", delete_after=3.0)
                    return
                
                await progress.update(40, "🖼️ Генерирую изображения...")
                media_group = []
                total_days = len(week_schedule)
                images_generated = 0
                
                # Генерируем все изображения
                for date_str, pairs in sorted(week_schedule.items()):
                    date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                    day_schedule = await get_day_schedule_structured(query, api_type, date_obj)
                    
                    if day_schedule:
                        image_bytes = await generate_day_schedule_image(day_schedule, query, api_type)
                        if image_bytes:
                            weekday_name = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"][date_obj.weekday()]
                            filename = f"schedule_{query}_{date_str}.png"
                            caption = f"🖼️ {weekday_name}, {date_obj.strftime('%d.%m.%Y')}"
                            
                            image_bytes.name = filename
                            media_group.append(InputMediaPhoto(media=image_bytes, caption=caption))
                            images_generated += 1
                    
                    await progress.update(40 + int(30 * images_generated / max(total_days, 1)), f"🖼️ Сгенерировано {images_generated} изображений...")
                
                if images_generated == 0:
                    await progress.finish("❌ Не удалось сгенерировать изображения", delete_after=3.0)
                    return
                
                # Отправляем все изображения вместе (media_group до 10 файлов за раз)
                await progress.update(80, "📤 Отправляю изображения...")
                
                # Telegram позволяет отправлять до 10 медиафайлов в одной группе
                chunk_size = 10
                for i in range(0, len(media_group), chunk_size):
                    chunk = media_group[i:i + chunk_size]
                    try:
                        await context.bot.send_media_group(
                            chat_id=chat_id,
                            media=chunk
                        )
                    except Exception as e:
                        logger.error(f"Ошибка при отправке группы изображений (chunk {i//chunk_size + 1}): {e}", exc_info=True)
                        # Пытаемся отправить изображения по одному, если группа не удалась
                        for img in chunk:
                            try:
                                await context.bot.send_photo(
                                    chat_id=chat_id,
                                    photo=img.media,
                                    caption=img.caption
                                )
                            except Exception as e2:
                                logger.error(f"Ошибка при отправке отдельного изображения: {e2}", exc_info=True)
                
                # Отправляем сообщение с кнопками навигации после экспорта
                await _send_export_success_message(context.bot, chat_id, query, user_data)
                    
            else:
                # PDF или изображение недели
                await progress.update(30, "📊 Обрабатываю данные...")
                week_schedule = await get_week_schedule_structured(query, api_type)
                
                if not week_schedule:
                    await progress.finish("❌ Расписание не найдено", delete_after=3.0)
                    return
                
                # Генерируем файл
                await progress.update(60, f"🎨 Генерирую {export_type.upper()}...")
                
                if export_type == "pdf":
                    file_bytes = await generate_week_schedule_file(week_schedule, query, api_type)
                    filename = f"schedule_{query}_{datetime.date.today().strftime('%Y%m%d')}.pdf"
                    caption = f"📄 Расписание для {query}"
                else:  # image
                    file_bytes = await generate_schedule_image(week_schedule, query, api_type)
                    filename = f"schedule_{query}_{datetime.date.today().strftime('%Y%m%d')}.png"
                    caption = f"🖼️ Расписание для {query}"
                
                if not file_bytes:
                    await progress.finish("❌ Ошибка при генерации файла", delete_after=3.0)
                    return
                
                # Отправляем файл
                await progress.update(90, "📤 Отправляю файл...")
                
                if export_type == "pdf":
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=file_bytes,
                        filename=filename,
                        caption=caption
                    )
                else:  # image
                    file_bytes.name = filename
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=file_bytes,
                        caption=caption
                    )
                
                # Отправляем сообщение с кнопками навигации после экспорта
                await _send_export_success_message(context.bot, chat_id, query, user_data)
            
            await progress.finish("✅ Экспорт готов!", delete_after=2.0)
            
        except Exception as e:
            logger.error(f"Ошибка при экспорте: {e}", exc_info=True)
            await safe_answer_callback_query(
                update.callback_query,
                "❌ Ошибка при экспорте. Попробуйте позже.",
                show_alert=True
            )

