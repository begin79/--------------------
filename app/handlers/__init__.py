"""
Модули обработчиков бота
"""
from .start import start_command
from .help import help_command_handler
from .settings import settings_menu_callback
from .text import handle_text_message
from .callbacks import callback_router, inline_query_handler

__all__ = [
    'start_command',
    'help_command_handler',
    'settings_menu_callback',
    'handle_text_message',
    'callback_router',
    'inline_query_handler',
]

