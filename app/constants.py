from enum import Enum
from typing import Optional

# Типы сущностей
class EntityType(str, Enum):
    GROUP = "Group"
    TEACHER = "Teacher"

# Для обратной совместимости
API_TYPE_GROUP = EntityType.GROUP.value
API_TYPE_TEACHER = EntityType.TEACHER.value

# Режимы работы бота
class BotMode(str, Enum):
    STUDENT = "student"
    TEACHER = "teacher"

# Эмодзи для нумерации пар
PAIR_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"]

# Эмодзи для типов пар
PAIR_TYPE_EMOJIS = {
    "лекция": "📚",
    "практика": "✏️",
    "лабораторная": "🔬",
    "семинар": "💬",
    "зачет": "📝",
    "экзамен": "📋",
    "консультация": "💡",
    "default": "📖"  # По умолчанию для предмета
}

# Регулярные выражения
GROUP_NAME_PATTERN = r"\b[А-Я0-9]+-\d{1,3}(?:-[А-Я]+)?\b"
SUBGROUP_PATTERN = r"([а-яА-Я])(\d)"

# Callback data - используем Enum для безопасности
class CallbackData(str, Enum):
    MODE_STUDENT = "mode_student"
    MODE_TEACHER = "mode_teacher"
    BACK_TO_START = "back_to_start"
    SETTINGS_MENU = "settings_menu"
    SET_DEFAULT = "set_default_query"
    TOGGLE_DAILY = "toggle_daily_notifications"
    CANCEL_INPUT = "cancel_input"
    EXPORT_WEEK_TEXT = "export_week_text"
    EXPORT_WEEK_IMAGE = "export_week_image"
    EXPORT_WEEK_FILE = "export_week_file"
    EXPORT_MENU = "export_menu"
    EXPORT_DAY_IMAGE = "export_day_image_"
    EXPORT_DAYS_IMAGES = "export_days_images"
    EXPORT_SEMESTER = "export_semester"
    TEACHER_PHOTO = "teacher_photo_"
    TEACHER_PROFILE = "teacher_profile_"
    HELP_COMMAND_INLINE = "help_command_inline"
    BACK_TO_SCHEDULE = "back_to_schedule_from_export"
    FEEDBACK = "feedback"
    SET_DEFAULT_FROM_SCHEDULE = "set_default_from_schedule"
    RESET_SETTINGS = "reset_settings"
    DO_RESET_SETTINGS = "do_reset_settings"
    SET_NOTIFICATION_TIME = "set_notification_time"
    CONFIRM_MODE = "confirm_mode_"

# Префиксы для callback data
class CallbackPrefix(str, Enum):
    REFRESH = "refresh_"
    PREV = "prev_"
    NEXT = "next_"
    DATE = "pick_date_"
    SET_TIME = "set_time_"
    SET_DEFAULT_MODE = "set_default_mode_"
    EXPORT_MENU = "export_menu_"
    EXPORT_WEEK_IMAGE = "export_week_image_"
    EXPORT_WEEK_FILE = "export_week_file_"
    EXPORT_DAYS_IMAGES = "export_days_images_"
    EXPORT_SEMESTER = "export_semester_"
    VIEW_CHANGED_SCHEDULE = "view_changed_schedule_"
    NOTIFICATION_OPEN = "notification_open_schedule_"

# Для обратной совместимости
CALLBACK_DATA_MODE_STUDENT = CallbackData.MODE_STUDENT.value
CALLBACK_DATA_MODE_TEACHER = CallbackData.MODE_TEACHER.value
CALLBACK_DATA_BACK_TO_START = CallbackData.BACK_TO_START.value
CALLBACK_DATA_SETTINGS_MENU = CallbackData.SETTINGS_MENU.value
CALLBACK_DATA_SET_DEFAULT = CallbackData.SET_DEFAULT.value
CALLBACK_DATA_TOGGLE_DAILY = CallbackData.TOGGLE_DAILY.value
CALLBACK_DATA_CANCEL_INPUT = CallbackData.CANCEL_INPUT.value
CALLBACK_DATA_EXPORT_WEEK_TEXT = CallbackData.EXPORT_WEEK_TEXT.value
CALLBACK_DATA_EXPORT_WEEK_IMAGE = CallbackData.EXPORT_WEEK_IMAGE.value
CALLBACK_DATA_EXPORT_WEEK_FILE = CallbackData.EXPORT_WEEK_FILE.value
CALLBACK_DATA_EXPORT_MENU = CallbackData.EXPORT_MENU.value
CALLBACK_DATA_EXPORT_DAY_IMAGE = CallbackData.EXPORT_DAY_IMAGE.value
CALLBACK_DATA_EXPORT_DAYS_IMAGES = CallbackData.EXPORT_DAYS_IMAGES.value
CALLBACK_DATA_EXPORT_SEMESTER = CallbackData.EXPORT_SEMESTER.value
CALLBACK_DATA_BACK_TO_SCHEDULE = CallbackData.BACK_TO_SCHEDULE.value
# CALLBACK_DATA_TEACHER_PHOTO = CallbackData.TEACHER_PHOTO.value  # Не используется
# CALLBACK_DATA_TEACHER_PROFILE = CallbackData.TEACHER_PROFILE.value  # Не используется
CALLBACK_DATA_FEEDBACK = CallbackData.FEEDBACK.value
CALLBACK_DATA_RESET_SETTINGS = CallbackData.RESET_SETTINGS.value
CALLBACK_DATA_DO_RESET_SETTINGS = CallbackData.DO_RESET_SETTINGS.value
CALLBACK_DATA_SET_NOTIFICATION_TIME = CallbackData.SET_NOTIFICATION_TIME.value
CALLBACK_DATA_CONFIRM_MODE = CallbackData.CONFIRM_MODE.value

CALLBACK_DATA_REFRESH_SCHEDULE_PREFIX = CallbackPrefix.REFRESH.value
CALLBACK_DATA_PREV_SCHEDULE_PREFIX = CallbackPrefix.PREV.value
CALLBACK_DATA_NEXT_SCHEDULE_PREFIX = CallbackPrefix.NEXT.value
CALLBACK_DATA_DATE_PREFIX = CallbackPrefix.DATE.value
CALLBACK_DATA_DATE_TODAY = f"{CallbackPrefix.DATE.value}today"
CALLBACK_DATA_DATE_TOMORROW = f"{CallbackPrefix.DATE.value}tomorrow"
CALLBACK_DATA_DATE_MANUAL = f"{CallbackPrefix.DATE.value}manual"
CALLBACK_DATA_NOTIFICATION_OPEN_PREFIX = CallbackPrefix.NOTIFICATION_OPEN.value

# Ключи контекста пользователя
class UserContextKey(str, Enum):
    MODE = "ctx_mode"
    SELECTED_DATE = "ctx_selected_date"
    AWAITING_MANUAL_DATE = "ctx_awaiting_manual_date"
    LAST_QUERY = "ctx_last_query"
    SCHEDULE_PAGES = "ctx_schedule_pages"
    CURRENT_PAGE_INDEX = "ctx_current_page_index"
    AWAITING_DEFAULT_QUERY = "ctx_awaiting_default_query"
    AWAITING_FEEDBACK = "ctx_awaiting_feedback"
    DEFAULT_QUERY = "ctx_default_query"
    DEFAULT_MODE = "ctx_default_mode"
    DAILY_NOTIFICATIONS = "ctx_daily_notifications"
    NOTIFICATION_TIME = "ctx_notification_time"
    IS_BUSY = "ctx_is_busy"  # Для блокировки одновременных запросов
    REPLY_KEYBOARD_PINNED = "ctx_reply_keyboard_pinned"
    FOUND_ENTITIES = "ctx_found_entities"  # Список найденных вариантов для выбора
    KEYBOARD_MESSAGE_ID = "ctx_keyboard_message_id"  # ID сообщения со стикером клавиатуры

# Для обратной совместимости
CTX_MODE = UserContextKey.MODE.value
CTX_SELECTED_DATE = UserContextKey.SELECTED_DATE.value
CTX_AWAITING_MANUAL_DATE = UserContextKey.AWAITING_MANUAL_DATE.value
CTX_LAST_QUERY = UserContextKey.LAST_QUERY.value
CTX_SCHEDULE_PAGES = UserContextKey.SCHEDULE_PAGES.value
CTX_CURRENT_PAGE_INDEX = UserContextKey.CURRENT_PAGE_INDEX.value
CTX_AWAITING_DEFAULT_QUERY = UserContextKey.AWAITING_DEFAULT_QUERY.value
CTX_AWAITING_FEEDBACK = UserContextKey.AWAITING_FEEDBACK.value
CTX_DEFAULT_QUERY = UserContextKey.DEFAULT_QUERY.value
CTX_DEFAULT_MODE = UserContextKey.DEFAULT_MODE.value
CTX_DAILY_NOTIFICATIONS = UserContextKey.DAILY_NOTIFICATIONS.value
CTX_NOTIFICATION_TIME = UserContextKey.NOTIFICATION_TIME.value
CTX_IS_BUSY = UserContextKey.IS_BUSY.value
CTX_REPLY_KEYBOARD_PINNED = UserContextKey.REPLY_KEYBOARD_PINNED.value
CTX_FOUND_ENTITIES = UserContextKey.FOUND_ENTITIES.value
CTX_KEYBOARD_MESSAGE_ID = UserContextKey.KEYBOARD_MESSAGE_ID.value

# Магические строки - режимы работы
MODE_STUDENT = BotMode.STUDENT.value  # "student"
MODE_TEACHER = BotMode.TEACHER.value  # "teacher"

# Магические строки - текстовые описания
ENTITY_GROUP = "группу"
ENTITY_GROUPS = "группы"
ENTITY_GROUP_GENITIVE = "группы"
ENTITY_TEACHER = "преподавателя"
ENTITY_TEACHER_GENITIVE = "преподавателя"
ENTITY_STUDENT = "студента"

# Магические строки - значения по умолчанию
DEFAULT_NOTIFICATION_TIME = "21:00"

# Магические строки - префиксы для задач
JOB_PREFIX_DAILY_SCHEDULE = "daily_schedule_"

# Лимиты для поиска и отображения
MAX_SEARCH_RESULTS_DISPLAY = 20  # Максимальное количество результатов поиска для отображения
MAX_INLINE_RESULTS = 10  # Максимальное количество результатов в inline-режиме


