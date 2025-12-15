"""
Модули обработчиков бота
"""
from .start import start_command
from .help import help_command_handler
from .settings import settings_menu_callback

# Временно импортируем из старого handlers.py до завершения рефакторинга
try:
    from ..handlers import handle_text_message, callback_router
except ImportError:
    # Если handlers.py уже удален, импортируем из новых модулей
    from .text import handle_text_message
    from .callbacks import callback_router

__all__ = [
    'start_command',
    'help_command_handler',
    'settings_menu_callback',
    'handle_text_message',
    'callback_router',
]

