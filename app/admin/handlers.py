"""
Обработчики команд админ-панели
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .database import admin_db
from .utils import is_admin, is_bot_enabled, set_bot_status, get_maintenance_message, set_maintenance_message
from ..database import db
from ..utils import escape_html
from datetime import datetime

logger = logging.getLogger(__name__)

# Callback data для админ-панели
CALLBACK_ADMIN_MENU = "admin_menu"
CALLBACK_ADMIN_STATS = "admin_stats"
CALLBACK_ADMIN_BOT_STATUS = "admin_bot_status"
CALLBACK_ADMIN_TOGGLE_BOT = "admin_toggle_bot"
CALLBACK_ADMIN_SET_MAINTENANCE_MSG = "admin_set_maintenance_msg"
CALLBACK_ADMIN_USERS = "admin_users"
CALLBACK_ADMIN_CACHE = "admin_cache"
CALLBACK_ADMIN_LOGS = "admin_logs"
CALLBACK_ADMIN_BROADCAST = "admin_broadcast"
CALLBACK_ADMIN_ADD_ADMIN = "admin_add_admin"
CALLBACK_ADMIN_REMOVE_ADMIN = "admin_remove_admin"
CALLBACK_ADMIN_LIST_ADMINS = "admin_list_admins"
CALLBACK_ADMIN_CONFIRM_TOGGLE = "admin_confirm_toggle"
CALLBACK_ADMIN_CANCEL_TOGGLE = "admin_cancel_toggle"

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
        [InlineKeyboardButton("📋 Список пользователей", callback_data="admin_users_list")],
        [InlineKeyboardButton("🔍 Найти пользователя", callback_data="admin_users_search")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_ADMIN_MENU)]
    ])

    await update.callback_query.edit_message_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
    await update.callback_query.answer()

async def admin_users_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список пользователей"""
    if not update.effective_user or not is_admin(update.effective_user.id):
        return

    try:
        all_users = db.get_all_users()
        total = len(all_users)

        if total == 0:
            text = "👥 <b>Список пользователей</b>\n\nПользователей пока нет."
        else:
            # Показываем первые 20 пользователей
            users_to_show = all_users[:20]
            text = f"👥 <b>Список пользователей</b>\n\nВсего: {total}\n\n"

            for i, user in enumerate(users_to_show, 1):
                username = user.get('username', 'без username')
                user_id = user.get('user_id', 'N/A')
                last_active = user.get('last_active', 'никогда')
                try:
                    if last_active and last_active != 'никогда':
                        # Пытаемся отформатировать дату
                        if 'T' in str(last_active):
                            from datetime import datetime
                            date_obj = datetime.fromisoformat(str(last_active).replace('Z', '+00:00'))
                            last_active = date_obj.strftime('%d.%m.%Y %H:%M')
                except:
                    pass

                text += f"{i}. @{escape_html(username)} (ID: {user_id})\n   Активен: {last_active}\n\n"

            if total > 20:
                text += f"\n... и еще {total - 20} пользователей"

        kbd = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Обновить", callback_data="admin_users_list")],
            [InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_ADMIN_USERS)]
        ])

        await update.callback_query.edit_message_text(text, reply_markup=kbd, parse_mode=ParseMode.HTML)
        await update.callback_query.answer()
    except Exception as e:
        logger.error(f"Ошибка при получении списка пользователей: {e}", exc_info=True)
        await update.callback_query.answer("❌ Ошибка при получении списка", show_alert=True)

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

    if not admins:
        text = "👨‍💼 <b>Администраторы</b>\n\nСписок пуст."
    else:
        text = f"👨‍💼 <b>Администраторы</b> ({len(admins)}):\n\n"
        for i, admin in enumerate(admins, 1):
            username = admin.get('username', 'без username')
            added_at = admin.get('added_at', 'неизвестно')
            try:
                if 'T' in added_at:
                    date_obj = datetime.fromisoformat(added_at.replace('Z', '+00:00'))
                    added_at = date_obj.strftime('%d.%m.%Y')
            except:
                pass
            text += f"{i}. @{escape_html(username)} (ID: {admin['user_id']})\n   Добавлен: {added_at}\n\n"

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
    total = len(all_users)

    await update.message.reply_text(f"📤 Начинаю рассылку для {total} пользователей...")

    success = 0
    failed = 0

    for user in all_users:
        try:
            user_id = user['user_id']
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
            logger.debug(f"Не удалось отправить сообщение пользователю {user_id}: {e}")

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
    elif data.startswith(CALLBACK_ADMIN_CONFIRM_TOGGLE):
        await admin_confirm_toggle_callback(update, context, data)
    else:
        await update.callback_query.answer("Неизвестная команда")

