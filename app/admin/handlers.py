"""
Обработчики команд админ-панели
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.error import Forbidden, BadRequest
from telegram.ext import ContextTypes

from .database import admin_db
from .utils import (
    is_admin,
    is_bot_enabled,
    set_bot_status,
    get_maintenance_message,
    set_maintenance_message,
    get_root_admin_id,
    is_root_admin,
)
from ..database import db
from ..utils import escape_html

logger = logging.getLogger(__name__)

# Callback data для админ-панели
CALLBACK_ADMIN_MENU = "admin_menu"
CALLBACK_ADMIN_STATS = "admin_stats"
CALLBACK_ADMIN_BOT_STATUS = "admin_bot_status"
CALLBACK_ADMIN_TOGGLE_BOT = "admin_toggle_bot"
CALLBACK_ADMIN_SET_MAINTENANCE_MSG = "admin_set_maintenance_msg"
CALLBACK_ADMIN_USERS = "admin_users"
CALLBACK_ADMIN_USERS_LIST = "admin_users_list"
CALLBACK_ADMIN_USERS_PAGE_PREFIX = "admin_users_page_"
CALLBACK_ADMIN_USER_DETAILS_PREFIX = "admin_user_details_"
CALLBACK_ADMIN_MESSAGE_USER_PREFIX = "admin_message_user_"
CALLBACK_ADMIN_MESSAGE_CANCEL = "admin_message_cancel"
CALLBACK_USER_REPLY_ADMIN_PREFIX = "user_reply_admin_"
CALLBACK_USER_DISMISS_ADMIN_PREFIX = "user_dismiss_admin_"
CALLBACK_ADMIN_CACHE = "admin_cache"
CALLBACK_ADMIN_LOGS = "admin_logs"
CALLBACK_ADMIN_BROADCAST = "admin_broadcast"
CALLBACK_ADMIN_ADD_ADMIN = "admin_add_admin"
CALLBACK_ADMIN_REMOVE_ADMIN = "admin_remove_admin"
CALLBACK_ADMIN_LIST_ADMINS = "admin_list_admins"
CALLBACK_ADMIN_CONFIRM_TOGGLE = "admin_confirm_toggle"
CALLBACK_ADMIN_CANCEL_TOGGLE = "admin_cancel_toggle"

USERS_PAGE_SIZE = 5  # Уменьшено для удобства навигации

def format_timestamp(value: Optional[str]) -> str:
    """Приводит ISO-дату к читаемому виду"""
    if not value:
        return "неизвестно"
    try:
        ts = value
        if isinstance(value, datetime):
            dt = value
        else:
            if isinstance(value, str):
                ts = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(str(ts))
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(value)

def display_username(raw_username: Optional[str]) -> str:
    """Форматирует username для отображения"""
    if not raw_username:
        return "без username"
    return raw_username

def require_admin(func):
    """Декоратор для проверки прав администратора"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not update.effective_user:
            return

        user_id = update.effective_user.id
        if not is_admin(user_id):
            await update.message.reply_text("❌ У вас нет прав администратора.")
            return

        return await func(update, context, *args, **kwargs)
    return wrapper

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /admin - вход в админ-панель"""
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id

    if not is_admin(user_id):
        # Для не-админов показываем дружелюбное сообщение вместо ошибки
        await update.message.reply_text(
            "❌ У вас нет прав администратора.\n\n"
            "Эта команда доступна только администраторам бота."
        )
        return

    await admin_menu_callback(update, context)

async def admin_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главное меню админ-панели"""
    if not update.effective_user:
        return

    user_id = update.effective_user.id
    username = update.effective_user.username or "без username"

    if not is_admin(user_id):
        await update.message.reply_text("❌ У вас нет прав администратора.")
        return

    # Получаем статус бота
    bot_status = admin_db.get_bot_status()
    status_emoji = "🟢" if bot_status.get('is_enabled', True) else "🔴"
    status_text = "Включен" if bot_status.get('is_enabled', True) else "Выключен"

    # Получаем статистику
    stats = admin_db.get_statistics()

    text = (
        f"🔧 <b>Админ-панель</b>\n\n"
        f"👤 Администратор: @{escape_html(username)}\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"🟢 Активных за 24ч: {stats['active_users_24h']}\n"
        f"📝 Всего запросов: {stats['total_requests']}\n\n"
        f"🤖 <b>Статус бота:</b> {status_emoji} {status_text}\n\n"
        f"Выберите действие:"
    )

    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статистика", callback_data=CALLBACK_ADMIN_STATS)],
        [InlineKeyboardButton(f"{status_emoji} Управление ботом", callback_data=CALLBACK_ADMIN_BOT_STATUS)],
        [InlineKeyboardButton("👥 Управление пользователями", callback_data=CALLBACK_ADMIN_USERS)],
        [InlineKeyboardButton("💬 Массовая рассылка", callback_data=CALLBACK_ADMIN_BROADCAST)],
        [InlineKeyboardButton("🗑️ Очистить кеш", callback_data=CALLBACK_ADMIN_CACHE)],
        [InlineKeyboardButton("👨‍💼 Управление админами", callback_data=CALLBACK_ADMIN_LIST_ADMINS)],
    ])

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
        await update.callback_query.answer()
    else:
        await update.message.reply_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)

async def admin_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детальная статистика"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    # Обновляем статистику
    admin_db.update_statistics_cache()
    stats = admin_db.get_statistics()

    # Получаем дополнительную статистику
    try:
        from ..database import db
        all_users = db.get_all_users()

        # Пользователи с уведомлениями
        users_with_notifications = sum(1 for u in all_users if u.get('daily_notifications'))

        # Самые активные пользователи
        from datetime import datetime, timedelta
        active_users = [u for u in all_users if u.get('last_active')]
        active_users.sort(key=lambda x: x.get('last_active', ''), reverse=True)
        top_active = active_users[:5]

        # Популярные группы/преподаватели (из activity_log)
        # Это можно расширить позже

    except Exception as e:
        logger.error(f"Ошибка получения дополнительной статистики: {e}")
        users_with_notifications = 0
        top_active = []

    text = (
        f"📊 <b>Детальная статистика</b>\n\n"
        f"👥 <b>Пользователи:</b>\n"
        f"   • Всего: {stats['total_users']}\n"
        f"   • Активных за 24ч: {stats['active_users_24h']}\n"
        f"   • С уведомлениями: {users_with_notifications}\n\n"
        f"📝 <b>Активность:</b>\n"
        f"   • Всего запросов: {stats['total_requests']}\n\n"
    )

    if top_active:
        text += f"🏆 <b>Топ-5 активных пользователей:</b>\n"
        for i, user in enumerate(top_active, 1):
            username = user.get('username', 'без username')
            text += f"   {i}. @{escape_html(username)}\n"
        text += "\n"

    text += f"🕐 Обновлено: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"

    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Обновить", callback_data=CALLBACK_ADMIN_STATS)],
        [InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_ADMIN_MENU)]
    ])

    await update.callback_query.edit_message_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
    await update.callback_query.answer()

async def admin_bot_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление статусом бота"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    bot_status = admin_db.get_bot_status()
    is_enabled = bot_status.get('is_enabled', True)
    maintenance_msg = bot_status.get('maintenance_message', 'Бот временно недоступен. Ведутся технические работы.')

    status_emoji = "🟢" if is_enabled else "🔴"
    status_text = "Включен" if is_enabled else "Выключен"
    toggle_text = "Выключить бота" if is_enabled else "Включить бота"
    toggle_emoji = "🔴" if is_enabled else "🟢"

    text = (
        f"🤖 <b>Управление статусом бота</b>\n\n"
        f"Текущий статус: {status_emoji} <b>{status_text}</b>\n\n"
        f"📝 <b>Сообщение при выключении:</b>\n"
        f"<i>{escape_html(maintenance_msg)}</i>\n\n"
        f"Выберите действие:"
    )

    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{toggle_emoji} {toggle_text}", callback_data=CALLBACK_ADMIN_TOGGLE_BOT)],
        [InlineKeyboardButton("✏️ Изменить сообщение", callback_data=CALLBACK_ADMIN_SET_MAINTENANCE_MSG)],
        [InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_ADMIN_MENU)]
    ])

    await update.callback_query.edit_message_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
    await update.callback_query.answer()

async def admin_toggle_bot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключение статуса бота"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    bot_status = admin_db.get_bot_status()
    is_enabled = bot_status.get('is_enabled', True)
    new_status = not is_enabled

    # Подтверждение
    text = (
        f"⚠️ <b>Подтверждение</b>\n\n"
        f"Вы уверены, что хотите <b>{'выключить' if new_status == False else 'включить'}</b> бота?\n\n"
    )

    if new_status == False:
        maintenance_msg = bot_status.get('maintenance_message', 'Бот временно недоступен. Ведутся технические работы.')
        text += f"Пользователи будут видеть сообщение:\n<i>{escape_html(maintenance_msg)}</i>"

    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да, подтверждаю", callback_data=f"{CALLBACK_ADMIN_CONFIRM_TOGGLE}_{int(new_status)}")],
        [InlineKeyboardButton("❌ Отмена", callback_data=CALLBACK_ADMIN_BOT_STATUS)]
    ])

    await update.callback_query.edit_message_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
    await update.callback_query.answer()

async def admin_confirm_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
    """Подтверждение переключения статуса бота"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    try:
        new_status = bool(int(data.split('_')[-1]))
        user_id = update.effective_user.id

        if set_bot_status(new_status, updated_by=user_id):
            status_text = "включен" if new_status else "выключен"
            status_emoji = "🟢" if new_status else "🔴"

            text = (
                f"{status_emoji} <b>Бот успешно {status_text}!</b>\n\n"
            )

            if not new_status:
                maintenance_msg = get_maintenance_message()
                text += f"Пользователи будут видеть сообщение:\n<i>{escape_html(maintenance_msg)}</i>"

            kbd = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_ADMIN_BOT_STATUS)]
            ])

            await update.callback_query.edit_message_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
            await update.callback_query.answer(f"Бот {status_text}!")

            logger.info(f"Админ {user_id} {'выключил' if not new_status else 'включил'} бота")
        else:
            await update.callback_query.answer("❌ Ошибка при изменении статуса", show_alert=True)
    except Exception as e:
        logger.error(f"Ошибка при переключении статуса бота: {e}", exc_info=True)
        await update.callback_query.answer("❌ Произошла ошибка", show_alert=True)

async def admin_set_maintenance_msg_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установка сообщения о техническом обслуживании"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    context.user_data['awaiting_maintenance_msg'] = True

    current_msg = get_maintenance_message()

    text = (
        f"✏️ <b>Изменение сообщения о техническом обслуживании</b>\n\n"
        f"Текущее сообщение:\n<i>{escape_html(current_msg)}</i>\n\n"
        f"Отправьте новое сообщение:"
    )

    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data=CALLBACK_ADMIN_BOT_STATUS)]
    ])

    await update.callback_query.edit_message_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
    await update.callback_query.answer()

async def handle_maintenance_message_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода сообщения о техническом обслуживании"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    if not context.user_data.get('awaiting_maintenance_msg'):
        return

    user_id = update.effective_user.id
    new_message = update.message.text

    if set_maintenance_message(new_message, updated_by=user_id):
        context.user_data.pop('awaiting_maintenance_msg', None)

        text = (
            f"✅ <b>Сообщение обновлено!</b>\n\n"
            f"Новое сообщение:\n<i>{escape_html(new_message)}</i>"
        )

        kbd = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_ADMIN_BOT_STATUS)]
        ])

        await update.message.reply_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
        logger.info(f"Админ {user_id} изменил сообщение о техническом обслуживании")
    else:
        await update.message.reply_text("❌ Ошибка при обновлении сообщения")

async def admin_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление пользователями"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    stats = admin_db.get_statistics()

    text = (
        f"👥 <b>Управление пользователями</b>\n\n"
        f"📊 Статистика:\n"
        f"   • Всего пользователей: {stats['total_users']}\n"
        f"   • Активных за 24ч: {stats['active_users_24h']}\n\n"
        f"Выберите действие:"
    )

    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Список пользователей", callback_data=CALLBACK_ADMIN_USERS_LIST)],
        [InlineKeyboardButton("🔍 Найти пользователя", callback_data="admin_users_search")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_ADMIN_MENU)]
    ])

    await update.callback_query.edit_message_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
    await update.callback_query.answer()

async def admin_users_list_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    page: int = 0,
):
    """Список пользователей с пагинацией"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    try:
        all_users = db.get_all_users()
        root_id = get_root_admin_id()
        visible_users = [
            user for user in all_users if user.get("user_id") != root_id
        ]
        total = len(visible_users)

        if total == 0:
            text = "👥 <b>Список пользователей</b>\n\nПользователей пока нет."
            kbd = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_ADMIN_USERS)]
            ])
            await update.callback_query.edit_message_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
            await update.callback_query.answer()
            return

        total_pages = (total + USERS_PAGE_SIZE - 1) // USERS_PAGE_SIZE
        page = max(0, min(page, total_pages - 1))
        context.user_data["admin_users_page"] = page

        start = page * USERS_PAGE_SIZE
        end = start + USERS_PAGE_SIZE
        users_page = visible_users[start:end]

        text_lines = [
            "👥 <b>Список пользователей</b>",
            "",
            f"Всего: {total} | Страница: {page + 1}/{total_pages}",
            "",
        ]

        # Компактный формат отображения
        for index, user in enumerate(users_page, start=start + 1):
            username = display_username(user.get("username"))
            user_id = user.get("user_id", "N/A")
            last_active = format_timestamp(user.get("last_active"))
            default_query = user.get("default_query")

            username_display = (
                f"@{escape_html(username)}" if username != "без username" else "без username"
            )

            # Компактная строка: номер, имя, ID, группа (если есть), активность
            if default_query:
                default_mode = user.get("default_mode") or ""
                mode_emoji = "🎓" if default_mode == "student" else "🧑‍🏫" if default_mode == "teacher" else ""
                line = f"{index}. {username_display} (ID: {user_id}) {mode_emoji} {escape_html(default_query[:20])}{'...' if len(default_query) > 20 else ''} | {last_active}"
            else:
                line = f"{index}. {username_display} (ID: {user_id}) | {last_active}"

            text_lines.append(line)

        if root_id:
            text_lines.append("")
            text_lines.append("ℹ️ Главный администратор скрыт из списка.")

        text = "\n".join(text_lines)

        # Компактные кнопки: две кнопки в одной строке
        kbd_rows = []
        for user in users_page:
            user_id = user.get("user_id")
            if user_id is None:
                continue
            username = display_username(user.get("username"))

            # Компактная метка для кнопки
            if username != "без username":
                label = f"👤 {username[:15]}{'...' if len(username) > 15 else ''}"
            else:
                label = f"👤 ID: {user_id}"

            # Две кнопки в одной строке: детали и написать
            kbd_rows.append([
                InlineKeyboardButton(
                    label,
                    callback_data=f"{CALLBACK_ADMIN_USER_DETAILS_PREFIX}{user_id}",
                ),
                InlineKeyboardButton(
                    "✉️",
                    callback_data=f"{CALLBACK_ADMIN_MESSAGE_USER_PREFIX}{user_id}",
                )
            ])

        nav_row = []
        if page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    "⬅️ Назад",
                    callback_data=f"{CALLBACK_ADMIN_USERS_PAGE_PREFIX}{page - 1}",
                )
            )
        nav_row.append(
            InlineKeyboardButton(
                "🔄 Обновить",
                callback_data=f"{CALLBACK_ADMIN_USERS_PAGE_PREFIX}{page}",
            )
        )
        if page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    "➡️ Далее",
                    callback_data=f"{CALLBACK_ADMIN_USERS_PAGE_PREFIX}{page + 1}",
                )
            )
        if nav_row:
            kbd_rows.append(nav_row)

        kbd_rows.append(
            [InlineKeyboardButton("⬅️ Меню", callback_data=CALLBACK_ADMIN_USERS)]
        )

        kbd = InlineKeyboardMarkup(kbd_rows)

        await update.callback_query.edit_message_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
        await update.callback_query.answer()
    except Exception as e:
        logger.error(f"Ошибка при получении списка пользователей: {e}", exc_info=True)
        await update.callback_query.answer("❌ Ошибка при получении списка", show_alert=True)

async def admin_user_details_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
):
    """Детальная информация о пользователе"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    if is_root_admin(user_id) and not is_root_admin(update.effective_user.id):
        await update.callback_query.answer("Недоступно для просмотра.", show_alert=True)
        return

    user = db.get_user(user_id)
    if not user:
        await update.callback_query.answer("Пользователь не найден.", show_alert=True)
        return

    username = display_username(user.get("username"))
    default_query = user.get("default_query") or "не установлено"
    default_mode = user.get("default_mode") or "не выбран"
    mode_text = "Студент" if default_mode == "student" else ("Преподаватель" if default_mode == "teacher" else default_mode)
    notifications_enabled = bool(user.get("daily_notifications"))
    notification_time = user.get("notification_time") or "21:00"
    last_active = format_timestamp(user.get("last_active"))
    created_at = format_timestamp(user.get("created_at"))

    history = db.get_user_activity(user_id, limit=5)

    username_display = (
        f"@{escape_html(username)}" if username != "без username" else "без username"
    )
    text_lines = [
        "👤 <b>Профиль пользователя</b>",
        "",
        f"ID: <code>{user_id}</code>",
        f"Username: {username_display}",
        f"Создан: {created_at}",
        f"Последняя активность: {last_active}",
        "",
        f"📌 По умолчанию: <b>{escape_html(default_query)}</b>",
        f"Режим: {escape_html(mode_text)}",
        "",
        f"🔔 Уведомления: {'включены' if notifications_enabled else 'выключены'}",
        f"Время уведомлений: {notification_time}",
        "",
    ]

    if username == "без username":
        text_lines.append("ℹ️ Пользователь скрывает свой username в Telegram.")
        text_lines.append("")

    if history:
        text_lines.append("📝 <b>Последние действия:</b>")
        for entry in history:
            timestamp = format_timestamp(entry.get("timestamp"))
            action = entry.get("action") or "действие"
            action_label = escape_html(action.replace("_", " ").capitalize())
            details = entry.get("details")
            if details:
                details = details.strip()
                if len(details) > 80:
                    details = details[:77] + "…"
                details = escape_html(details)
                text_lines.append(f"   • {timestamp}: {action_label}\n     <i>{details}</i>")
            else:
                text_lines.append(f"   • {timestamp}: {action_label}")
    else:
        text_lines.append("📝 История действий отсутствует.")

    text = "\n".join(text_lines)

    back_page = context.user_data.get("admin_users_page", 0)
    kbd_rows = [
        [InlineKeyboardButton("🔄 Обновить", callback_data=f"{CALLBACK_ADMIN_USER_DETAILS_PREFIX}{user_id}")],
        [InlineKeyboardButton("✉️ Написать сообщение", callback_data=f"{CALLBACK_ADMIN_MESSAGE_USER_PREFIX}{user_id}")],
        [InlineKeyboardButton("⬅️ К списку", callback_data=f"{CALLBACK_ADMIN_USERS_PAGE_PREFIX}{back_page}")],
    ]
    if username != "без username":
        kbd_rows.append(
            [InlineKeyboardButton("✉️ Открыть чат", url=f"https://t.me/{username}")]
        )
    kbd_rows.append(
        [InlineKeyboardButton("⬅️ Меню", callback_data=CALLBACK_ADMIN_USERS)]
    )

    kbd = InlineKeyboardMarkup(kbd_rows)

    await update.callback_query.edit_message_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
    await update.callback_query.answer()


def _get_dialog_storage(context: ContextTypes.DEFAULT_TYPE) -> Dict[int, Dict[str, Any]]:
    """Получить словарь активных диалогов админ↔пользователь"""
    return context.application.bot_data.setdefault("admin_dialogs", {})


async def admin_message_user_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
):
    """Запрос на отправку сообщения конкретному пользователю"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    context.user_data["awaiting_direct_message"] = True
    context.user_data["direct_message_target"] = user_id

    username = update.effective_user.username or "без username"
    prompt = (
        f"✉️ <b>Отправка сообщения пользователю</b>\n\n"
        f"Введите текст, который хотите отправить пользователю <code>{user_id}</code>.\n"
        f"После отправки пользователь увидит, что сообщение от администратора и сможет ответить.\n\n"
        f"💡 Администратор: @{escape_html(username)}"
    )

    back_buttons = [
        [InlineKeyboardButton("❌ Отмена", callback_data=CALLBACK_ADMIN_MESSAGE_CANCEL)],
        [InlineKeyboardButton("⬅️ К профилю", callback_data=f"{CALLBACK_ADMIN_USER_DETAILS_PREFIX}{user_id}")]
    ]
    kbd = InlineKeyboardMarkup(back_buttons)

    if update.callback_query:
        await update.callback_query.edit_message_text(prompt, reply_markup=kbd, parse_mode=ParseMode.HTML)
        await update.callback_query.answer()
    else:
        await update.message.reply_text(prompt, reply_markup=kbd, parse_mode=ParseMode.HTML)


async def admin_cancel_direct_message_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена режима отправки прямого сообщения"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    context.user_data.pop("awaiting_direct_message", None)
    context.user_data.pop("direct_message_target", None)

    text = "❌ Отправка сообщения отменена."

    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_ADMIN_USERS)]
    ])

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kbd)
        await update.callback_query.answer()
    else:
        await update.message.reply_text(text, reply_markup=kbd)


async def handle_direct_message_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода текста для конкретного пользователя"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    if not context.user_data.get("awaiting_direct_message"):
        return

    target_id = context.user_data.get("direct_message_target")
    if not target_id:
        await update.message.reply_text("Не удалось определить получателя. Попробуйте заново из списка пользователей.")
        context.user_data.pop("awaiting_direct_message", None)
        return

    message_text = update.message.text.strip()
    if not message_text:
        await update.message.reply_text("Отправьте текстовое сообщение для пользователя.")
        return

    admin = update.effective_user
    admin_id = admin.id
    admin_username = admin.username or "без username"
    admin_name = admin.full_name or admin.first_name or "Администратор"

    dialogs = _get_dialog_storage(context)
    dialogs[target_id] = {
        "admin_id": admin_id,
        "admin_username": admin_username,
        "last_sent_at": datetime.utcnow().isoformat()
    }

    user_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✉️ Ответить", callback_data=f"{CALLBACK_USER_REPLY_ADMIN_PREFIX}{admin_id}"),
            InlineKeyboardButton("✅ Спасибо", callback_data=f"{CALLBACK_USER_DISMISS_ADMIN_PREFIX}{admin_id}")
        ]
    ])

    user_message = (
        "📬 <b>Сообщение от администратора</b>\n\n"
        f"<b>{escape_html(admin_name)}</b> (@{escape_html(admin_username)}) написал:\n"
        f"{escape_html(message_text)}\n\n"
        "Вы можете ответить администратору или закрыть это уведомление."
    )

    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=user_message,
            parse_mode=ParseMode.HTML,
            reply_markup=user_keyboard
        )
        db.log_activity(target_id, "admin_message_received", f"from={admin_id}")
    except Forbidden:
        await update.message.reply_text(
            "⚠️ Пользователь заблокировал бота или недоступен. Сообщение не доставлено."
        )
        logger.warning(f"Админ {admin_id} не смог отправить сообщение пользователю {target_id}: Forbidden")
        dialogs.pop(target_id, None)
        return
    except BadRequest as e:
        await update.message.reply_text(
            f"❌ Не удалось отправить сообщение: {e}"
        )
        logger.error(f"Ошибка телеграма при отправке сообщения пользователю {target_id}: {e}")
        dialogs.pop(target_id, None)
        return
    except Exception as e:
        await update.message.reply_text("❌ Не удалось отправить сообщение пользователю.")
        logger.error(f"Ошибка при отправке сообщения пользователю {target_id}: {e}", exc_info=True)
        dialogs.pop(target_id, None)
        return

    context.user_data.pop("awaiting_direct_message", None)
    context.user_data.pop("direct_message_target", None)

    confirm_text = (
        f"✅ Сообщение отправлено пользователю <code>{target_id}</code>.\n"
        f"Текст:\n<pre>{escape_html(message_text)}</pre>"
    )
    confirm_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✉️ Написать ещё", callback_data=f"{CALLBACK_ADMIN_MESSAGE_USER_PREFIX}{target_id}")],
        [InlineKeyboardButton("⬅️ К профилю", callback_data=f"{CALLBACK_ADMIN_USER_DETAILS_PREFIX}{target_id}")],
        [InlineKeyboardButton("⬅️ Меню", callback_data=CALLBACK_ADMIN_USERS)]
    ])

    await update.message.reply_text(
        confirm_text,
        parse_mode=ParseMode.HTML,
        reply_markup=confirm_keyboard
    )
    logger.info(f"Админ {admin_id} отправил сообщение пользователю {target_id}")

async def admin_users_search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск пользователя"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    context.user_data['awaiting_user_search'] = True

    text = (
        f"🔍 <b>Поиск пользователя</b>\n\n"
        f"Отправьте:\n"
        f"   • Telegram ID пользователя (число)\n"
        f"   • Или username (без @)\n\n"
        f"Примеры:\n"
        f"   • 1003795435\n"
        f"   • hacker020106"
    )

    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data=CALLBACK_ADMIN_USERS)]
    ])

    await update.callback_query.edit_message_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
    await update.callback_query.answer()

async def handle_user_search_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода поиска пользователя"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    if not context.user_data.get('awaiting_user_search'):
        return

    search_query = update.message.text.strip()
    context.user_data.pop('awaiting_user_search', None)

    try:
        all_users = db.get_all_users()
        found_users = []

        # Пытаемся найти по ID
        try:
            search_id = int(search_query)
            for user in all_users:
                if user.get('user_id') == search_id:
                    found_users.append(user)
                    break
        except ValueError:
            # Ищем по username
            search_lower = search_query.lower().lstrip('@')
            for user in all_users:
                username = user.get('username', '').lower()
                if search_lower in username:
                    found_users.append(user)

        if not found_users:
            text = (
                f"❌ <b>Пользователь не найден</b>\n\n"
                f"Поиск: <code>{escape_html(search_query)}</code>\n\n"
                f"Попробуйте другой запрос."
            )
        else:
            user = found_users[0]
            user_id = user.get('user_id', 'N/A')
            username = user.get('username', 'без username')
            first_name = user.get('first_name', 'не указано')
            last_name = user.get('last_name', '')
            default_query = user.get('default_query', 'не установлено')
            default_mode = user.get('default_mode', 'не установлен')
            daily_notifications = 'включены' if user.get('daily_notifications') else 'выключены'
            notification_time = user.get('notification_time', 'не установлено')
            last_active = user.get('last_active', 'никогда')

            try:
                if last_active and last_active != 'никогда':
                    if 'T' in str(last_active):
                        from datetime import datetime
                        date_obj = datetime.fromisoformat(str(last_active).replace('Z', '+00:00'))
                        last_active = date_obj.strftime('%d.%m.%Y %H:%M')
            except:
                pass

            text = (
                f"👤 <b>Информация о пользователе</b>\n\n"
                f"🆔 ID: <code>{user_id}</code>\n"
                f"👤 Username: @{escape_html(username)}\n"
                f"📛 Имя: {escape_html(first_name)}"
            )

            if last_name:
                text += f" {escape_html(last_name)}"
            text += "\n\n"

            text += (
                f"📌 <b>Настройки:</b>\n"
                f"   • Расписание по умолчанию: {escape_html(default_query)} ({default_mode})\n"
                f"   • Уведомления: {daily_notifications}\n"
                f"   • Время уведомлений: {notification_time}\n\n"
                f"🕐 Последняя активность: {last_active}"
            )

        kbd = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Новый поиск", callback_data="admin_users_search")],
            [InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_ADMIN_USERS)]
        ])

        await update.message.reply_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Ошибка при поиске пользователя: {e}", exc_info=True)
        await update.message.reply_text("❌ Произошла ошибка при поиске пользователя.")

async def admin_cache_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Очистка кеша"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    try:
        # Очищаем кеши расписания
        from ..schedule import schedule_cache, list_cache
        schedule_cache.clear()
        list_cache.clear()

        # Очищаем кеш фотографий преподавателей
        try:
            from ..teacher_photo import teacher_photo_cache, teacher_profile_cache
            teacher_photo_cache.clear()
            teacher_profile_cache.clear()
        except:
            pass

        text = (
            f"✅ <b>Кеш очищен!</b>\n\n"
            f"Очищены:\n"
            f"   • Кеш расписания\n"
            f"   • Кеш списков\n"
            f"   • Кеш фотографий преподавателей"
        )

        logger.info(f"Админ {update.effective_user.id} очистил кеш")
    except Exception as e:
        logger.error(f"Ошибка при очистке кеша: {e}", exc_info=True)
        text = "❌ Ошибка при очистке кеша"

    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_ADMIN_MENU)]
    ])

    await update.callback_query.edit_message_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
    await update.callback_query.answer()

async def admin_list_admins_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список администраторов"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    admins = admin_db.get_all_admins()
    root_id = get_root_admin_id()
    visible_admins = [admin for admin in admins if admin.get("user_id") != root_id]

    if not visible_admins:
        text = (
            "👨‍💼 <b>Администраторы</b>\n\n"
            "Сейчас нет дополнительных администраторов."
        )
    else:
        text = f"👨‍💼 <b>Администраторы</b> ({len(visible_admins)}):\n\n"
        for i, admin in enumerate(visible_admins, 1):
            username = display_username(admin.get("username"))
            added_at = admin.get('added_at', 'неизвестно')
            try:
                if isinstance(added_at, str) and 'T' in added_at:
                    date_obj = datetime.fromisoformat(added_at.replace('Z', '+00:00'))
                    added_at = date_obj.strftime('%d.%m.%Y')
            except Exception:
                pass
            username_display = (
                f"@{escape_html(username)}" if username != "без username" else "без username"
            )
            text += (
                f"{i}. {username_display} (ID: {admin['user_id']})\n"
                f"   Добавлен: {added_at}\n\n"
            )

    if root_id:
        text += "ℹ️ Главный администратор скрыт из списка и не может быть удалён.\n"

    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить админа", callback_data=CALLBACK_ADMIN_ADD_ADMIN)],
        [InlineKeyboardButton("➖ Удалить админа", callback_data=CALLBACK_ADMIN_REMOVE_ADMIN)],
        [InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_ADMIN_MENU)]
    ])

    await update.callback_query.edit_message_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
    await update.callback_query.answer()

async def admin_add_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление администратора"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    context.user_data['awaiting_admin_id'] = True

    text = (
        f"➕ <b>Добавление администратора</b>\n\n"
        f"Отправьте Telegram ID пользователя, которого хотите сделать администратором.\n\n"
        f"💡 Как узнать ID:\n"
        f"   • Используйте бота @userinfobot\n"
        f"   • Или попросите пользователя написать /start в этом боте"
    )

    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data=CALLBACK_ADMIN_LIST_ADMINS)]
    ])

    await update.callback_query.edit_message_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
    await update.callback_query.answer()

async def handle_admin_id_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода ID администратора"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    if not context.user_data.get('awaiting_admin_id'):
        return

    try:
        new_admin_id = int(update.message.text.strip())
        added_by = update.effective_user.id

        # Получаем информацию о пользователе из основной БД
        from ..database import db
        user_info = db.get_user(new_admin_id)
        username = user_info.get('username') if user_info else None

        if admin_db.add_admin(new_admin_id, username, added_by):
            context.user_data.pop('awaiting_admin_id', None)

            text = (
                f"✅ <b>Администратор добавлен!</b>\n\n"
                f"ID: {new_admin_id}\n"
                f"Username: @{escape_html(username or 'неизвестно')}"
            )

            logger.info(f"Админ {added_by} добавил администратора {new_admin_id}")
        else:
            text = "❌ Ошибка при добавлении администратора"
    except ValueError:
        text = "❌ Неверный формат ID. Отправьте числовой ID."
    except Exception as e:
        logger.error(f"Ошибка при добавлении администратора: {e}", exc_info=True)
        text = "❌ Произошла ошибка"

    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_ADMIN_LIST_ADMINS)]
    ])

    await update.message.reply_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)

async def admin_remove_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление администратора"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    context.user_data['awaiting_remove_admin_id'] = True

    text = (
        f"➖ <b>Удаление администратора</b>\n\n"
        f"Отправьте Telegram ID администратора, которого хотите удалить."
    )

    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data=CALLBACK_ADMIN_LIST_ADMINS)]
    ])

    await update.callback_query.edit_message_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
    await update.callback_query.answer()

async def handle_remove_admin_id_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода ID для удаления администратора"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    if not context.user_data.get('awaiting_remove_admin_id'):
        return

    try:
        admin_id = int(update.message.text.strip())

        # Нельзя удалить самого себя
        if admin_id == update.effective_user.id:
            text = "❌ Вы не можете удалить самого себя."
        elif is_root_admin(admin_id):
            text = "❌ Нельзя удалить главного администратора."
        elif admin_db.remove_admin(admin_id):
            context.user_data.pop('awaiting_remove_admin_id', None)
            text = f"✅ Администратор {admin_id} удален."
            logger.info(f"Админ {update.effective_user.id} удалил администратора {admin_id}")
        else:
            text = "❌ Ошибка при удалении администратора или администратор не найден."
    except ValueError:
        text = "❌ Неверный формат ID."
    except Exception as e:
        logger.error(f"Ошибка при удалении администратора: {e}", exc_info=True)
        text = "❌ Произошла ошибка"

    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_ADMIN_LIST_ADMINS)]
    ])

    await update.message.reply_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)

async def admin_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Массовая рассылка"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    text = (
        f"💬 <b>Массовая рассылка</b>\n\n"
        f"Отправьте сообщение, которое будет разослано всем пользователям.\n\n"
        f"⚠️ <b>Внимание:</b> Рассылка может занять время при большом количестве пользователей."
    )

    context.user_data['awaiting_broadcast'] = True

    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data=CALLBACK_ADMIN_MENU)]
    ])

    await update.callback_query.edit_message_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
    await update.callback_query.answer()

async def handle_broadcast_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода сообщения для рассылки"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    if not context.user_data.get('awaiting_broadcast'):
        return

    message_text = update.message.text
    context.user_data.pop('awaiting_broadcast', None)

    # Получаем всех пользователей
    all_users = db.get_all_users()
    target_ids = db.get_all_known_user_ids(include_activity_log=True)
    total = len(target_ids)

    if total == 0:
        await update.message.reply_text("ℹ️ Пока нет пользователей для рассылки.")
        return

    stored_user_ids = {user.get('user_id') for user in all_users if user.get('user_id')}
    additional_from_log = len(set(target_ids) - stored_user_ids)

    info_suffix = ""
    if additional_from_log > 0:
        info_suffix = f"\nℹ️ Дополнительно найдено в журнале активности: {additional_from_log}"

    await update.message.reply_text(f"📤 Начинаю рассылку для {total} пользователей...{info_suffix}")

    success = 0
    failed = 0

    for raw_user_id in target_ids:
        if raw_user_id is None:
            continue
        try:
            user_id = int(raw_user_id)
            await context.bot.send_message(
                chat_id=user_id,
                text=message_text,
                parse_mode=ParseMode.HTML
            )
            success += 1
            # Небольшая задержка, чтобы не превысить лимиты API
            await asyncio.sleep(0.05)
        except Exception as e:
            failed += 1
            logger.debug(f"Не удалось отправить сообщение пользователю {raw_user_id}: {e}")

    text = (
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📊 Результаты:\n"
        f"   • Успешно: {success}\n"
        f"   • Ошибок: {failed}\n"
        f"   • Всего: {total}"
    )

    kbd = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_ADMIN_MENU)]
    ])

    await update.message.reply_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
    logger.info(f"Админ {update.effective_user.id} выполнил рассылку: {success}/{total} успешно")

async def admin_callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Роутер для callback'ов админ-панели"""
    if not update.callback_query:
        return

    # Проверяем права администратора
    if not update.effective_user or not is_admin(update.effective_user.id):
        await update.callback_query.answer("❌ У вас нет прав администратора", show_alert=True)
        return

    data = update.callback_query.data

    if data == CALLBACK_ADMIN_MENU:
        await admin_menu_callback(update, context)
    elif data == CALLBACK_ADMIN_STATS:
        await admin_stats_callback(update, context)
    elif data == CALLBACK_ADMIN_BOT_STATUS:
        await admin_bot_status_callback(update, context)
    elif data == CALLBACK_ADMIN_TOGGLE_BOT:
        await admin_toggle_bot_callback(update, context)
    elif data == CALLBACK_ADMIN_SET_MAINTENANCE_MSG:
        await admin_set_maintenance_msg_callback(update, context)
    elif data == CALLBACK_ADMIN_USERS:
        await admin_users_callback(update, context)
    elif data == "admin_users_list":
        await admin_users_list_callback(update, context)
    elif data == "admin_users_search":
        await admin_users_search_callback(update, context)
    elif data == CALLBACK_ADMIN_CACHE:
        await admin_cache_callback(update, context)
    elif data == CALLBACK_ADMIN_LIST_ADMINS:
        await admin_list_admins_callback(update, context)
    elif data == CALLBACK_ADMIN_ADD_ADMIN:
        await admin_add_admin_callback(update, context)
    elif data == CALLBACK_ADMIN_REMOVE_ADMIN:
        await admin_remove_admin_callback(update, context)
    elif data == CALLBACK_ADMIN_BROADCAST:
        await admin_broadcast_callback(update, context)
    elif data.startswith(CALLBACK_ADMIN_USERS_PAGE_PREFIX):
        try:
            page = int(data.replace(CALLBACK_ADMIN_USERS_PAGE_PREFIX, "", 1))
        except ValueError:
            page = 0
        await admin_users_list_callback(update, context, page=page)
    elif data.startswith(CALLBACK_ADMIN_USER_DETAILS_PREFIX):
        try:
            user_id = int(data.replace(CALLBACK_ADMIN_USER_DETAILS_PREFIX, "", 1))
        except ValueError:
            await update.callback_query.answer("Пользователь не найден", show_alert=True)
            return
        await admin_user_details_callback(update, context, user_id)
    elif data.startswith(CALLBACK_ADMIN_MESSAGE_USER_PREFIX):
        try:
            user_id = int(data.replace(CALLBACK_ADMIN_MESSAGE_USER_PREFIX, "", 1))
        except ValueError:
            await update.callback_query.answer("Пользователь не найден", show_alert=True)
            return
        await admin_message_user_callback(update, context, user_id)
    elif data == CALLBACK_ADMIN_MESSAGE_CANCEL:
        await admin_cancel_direct_message_callback(update, context)
    elif data.startswith(CALLBACK_ADMIN_CONFIRM_TOGGLE):
        await admin_confirm_toggle_callback(update, context, data)
    else:
        await update.callback_query.answer("Неизвестная команда")

