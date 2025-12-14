"""
Тест UX/UI дизайна бота
Проверяет понятность сообщений, навигацию и удобство использования
"""
import asyncio
import sys
import os
from typing import Dict, List

sys.path.insert(0, os.path.abspath('.'))

from app.handlers import (
    start_command, settings_menu_callback, help_command_handler,
    handle_schedule_search, send_schedule_with_pagination
)
from app.constants import MODE_STUDENT, MODE_TEACHER
from unittest.mock import AsyncMock, MagicMock, patch

class MockUpdate:
    def __init__(self, user_id: int, text: str = None, callback_data: str = None):
        self.effective_user = MagicMock()
        self.effective_user.id = user_id
        self.effective_user.username = f"user_{user_id}"
        self.effective_user.first_name = f"User{user_id}"
        self.effective_user.last_name = None
        
        self.effective_chat = MagicMock()
        self.effective_chat.id = user_id
        
        if text:
            self.message = MagicMock()
            self.message.text = text
            self.message.reply_text = AsyncMock()
            self.message.reply_chat_action = AsyncMock()
            self.callback_query = None
        elif callback_data:
            self.callback_query = MagicMock()
            self.callback_query.data = callback_data
            self.callback_query.message = MagicMock()
            self.callback_query.message.edit_text = AsyncMock()
            self.callback_query.message.reply_text = AsyncMock()
            self.callback_query.answer = AsyncMock()
            self.message = None
        else:
            self.message = None
            self.callback_query = None

class MockContext:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}
        self.job_queue = None

def analyze_message_clarity(text: str) -> Dict:
    """Анализирует понятность сообщения"""
    issues = []
    suggestions = []
    
    # Проверка длины
    if len(text) > 500:
        issues.append("Сообщение слишком длинное (>500 символов)")
        suggestions.append("Разбить на несколько сообщений или сократить текст")
    
    # Проверка структуры
    if text.count('\n') < 2:
        issues.append("Мало структуры (мало переносов строк)")
        suggestions.append("Добавить больше структуры с переносами строк")
    
    # Проверка эмодзи
    emoji_count = sum(1 for c in text if ord(c) > 127 and c not in 'абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ')
    if emoji_count == 0:
        issues.append("Нет эмодзи для визуального разделения")
        suggestions.append("Добавить эмодзи для улучшения восприятия")
    
    # Проверка HTML форматирования
    if '<b>' not in text and '<code>' not in text:
        issues.append("Нет форматирования текста")
        suggestions.append("Использовать HTML теги для выделения важной информации")
    
    return {
        "issues": issues,
        "suggestions": suggestions,
        "length": len(text),
        "lines": text.count('\n'),
        "has_emoji": emoji_count > 0,
        "has_formatting": '<b>' in text or '<code>' in text
    }

def analyze_navigation(buttons: List) -> Dict:
    """Анализирует навигацию"""
    issues = []
    suggestions = []
    
    # Проверка наличия кнопки "Назад"
    has_back = any("назад" in str(btn).lower() or "⬅️" in str(btn) for btn in buttons)
    if not has_back and len(buttons) > 1:
        issues.append("Нет кнопки 'Назад' для возврата")
        suggestions.append("Добавить кнопку 'Назад' или 'В начало'")
    
    # Проверка количества кнопок
    if len(buttons) > 6:
        issues.append("Слишком много кнопок (>6)")
        suggestions.append("Разбить на несколько строк или группировать")
    
    return {
        "issues": issues,
        "suggestions": suggestions,
        "button_count": len(buttons),
        "has_back": has_back
    }

async def test_start_command_design():
    """Тест дизайна команды /start"""
    print("\n" + "="*60)
    print("ТЕСТ ДИЗАЙНА: Команда /start")
    print("="*60)
    
    update = MockUpdate(12345)
    context = MockContext()
    
    with patch('app.handlers.is_bot_enabled', return_value=True), \
         patch('app.handlers.get_maintenance_message', return_value=""), \
         patch('app.handlers.db.get_user', return_value=None), \
         patch('app.handlers.save_user_data_to_db'), \
         patch('app.handlers.db.log_activity'):
        
        try:
            await start_command(update, context)
            
            # Проверяем, что сообщение было отправлено
            if update.message and update.message.reply_text.called:
                call_args = update.message.reply_text.call_args
                if call_args:
                    text = call_args[0][0] if call_args[0] else ""
                    analysis = analyze_message_clarity(text)
                    
                    print(f"\n📝 Анализ сообщения:")
                    print(f"   Длина: {analysis['length']} символов")
                    print(f"   Строк: {analysis['lines']}")
                    print(f"   Эмодзи: {'✅' if analysis['has_emoji'] else '❌'}")
                    print(f"   Форматирование: {'✅' if analysis['has_formatting'] else '❌'}")
                    
                    if analysis['issues']:
                        print(f"\n⚠️ Проблемы:")
                        for issue in analysis['issues']:
                            print(f"   • {issue}")
                    
                    if analysis['suggestions']:
                        print(f"\n💡 Предложения:")
                        for suggestion in analysis['suggestions']:
                            print(f"   • {suggestion}")
        except Exception as e:
            print(f"❌ Ошибка: {e}")

async def test_settings_menu_design():
    """Тест дизайна меню настроек"""
    print("\n" + "="*60)
    print("ТЕСТ ДИЗАЙНА: Меню настроек")
    print("="*60)
    
    update = MockUpdate(12345, callback_data="settings_menu")
    context = MockContext()
    context.user_data = {
        'default_query': 'ИС1-231',
        'default_mode': MODE_STUDENT,
        'daily_notifications': False,
        'notification_time': '21:00'
    }
    
    with patch('app.handlers.load_user_data_from_db'), \
         patch('app.handlers.safe_edit_message_text', new_callable=AsyncMock) as mock_edit:
        
        mock_edit.return_value = True
        
        try:
            await settings_menu_callback(update, context)
            
            if mock_edit.called:
                call_args = mock_edit.call_args
                if call_args:
                    text = call_args[1].get('text', '') if call_args[1] else (call_args[0][1] if len(call_args[0]) > 1 else "")
                    analysis = analyze_message_clarity(text)
                    
                    print(f"\n📝 Анализ сообщения:")
                    print(f"   Длина: {analysis['length']} символов")
                    print(f"   Строк: {analysis['lines']}")
                    print(f"   Эмодзи: {'✅' if analysis['has_emoji'] else '❌'}")
                    print(f"   Форматирование: {'✅' if analysis['has_formatting'] else '❌'}")
                    
                    if analysis['issues']:
                        print(f"\n⚠️ Проблемы:")
                        for issue in analysis['issues']:
                            print(f"   • {issue}")
                    
                    if analysis['suggestions']:
                        print(f"\n💡 Предложения:")
                        for suggestion in analysis['suggestions']:
                            print(f"   • {suggestion}")
        except Exception as e:
            print(f"❌ Ошибка: {e}")

def analyze_ux_improvements():
    """Анализ UX и предложения по улучшению"""
    print("\n" + "="*60)
    print("АНАЛИЗ UX/UI И ПРЕДЛОЖЕНИЯ ПО УЛУЧШЕНИЮ")
    print("="*60)
    
    improvements = [
        {
            "category": "Навигация",
            "issues": [
                "Дублирование информации в заголовке расписания",
                "Нет breadcrumbs в некоторых местах",
                "Кнопка 'Назад' не всегда понятна куда ведет"
            ],
            "suggestions": [
                "Убрать дублирование в заголовке (строки 1301-1302)",
                "Добавить breadcrumbs везде: 'Главное меню > Настройки > ...'",
                "Использовать более конкретные названия: 'Назад к расписанию', 'В главное меню'"
            ]
        },
        {
            "category": "Сообщения",
            "issues": [
                "Сообщения об ошибках недостаточно информативны",
                "Нет подсказок для новых пользователей",
                "Сообщения могут быть более структурированными"
            ],
            "suggestions": [
                "Добавить примеры в сообщения об ошибках",
                "Добавить подсказки при первом использовании функций",
                "Использовать списки и структурированный формат"
            ]
        },
        {
            "category": "Кнопки",
            "issues": [
                "Некоторые кнопки слишком длинные",
                "Нет группировки связанных действий",
                "Кнопки могут быть более понятными"
            ],
            "suggestions": [
                "Сократить длинные тексты кнопок",
                "Группировать связанные действия (например, все экспорты вместе)",
                "Использовать более понятные иконки и тексты"
            ]
        },
        {
            "category": "Обратная связь",
            "issues": [
                "Нет индикации загрузки в некоторых местах",
                "Toast-уведомления не всегда видны",
                "Нет подтверждения важных действий"
            ],
            "suggestions": [
                "Добавить индикацию загрузки везде, где есть ожидание",
                "Использовать show_alert=True для важных уведомлений",
                "Добавить подтверждение для сброса настроек"
            ]
        },
        {
            "category": "Информационная архитектура",
            "issues": [
                "Много информации в одном сообщении",
                "Нет прогрессивного раскрытия информации",
                "Сложно найти нужную функцию"
            ],
            "suggestions": [
                "Разбить длинные сообщения на несколько",
                "Использовать вкладки или секции для группировки",
                "Добавить поиск или быстрый доступ к часто используемым функциям"
            ]
        }
    ]
    
    for improvement in improvements:
        print(f"\n📋 {improvement['category']}:")
        print(f"   ⚠️ Проблемы:")
        for issue in improvement['issues']:
            print(f"      • {issue}")
        print(f"   💡 Предложения:")
        for suggestion in improvement['suggestions']:
            print(f"      • {suggestion}")

async def main():
    """Главная функция тестирования"""
    print("\n" + "="*60)
    print("ТЕСТИРОВАНИЕ UX/UI ДИЗАЙНА БОТА")
    print("="*60)
    
    # Тесты дизайна
    await test_start_command_design()
    await test_settings_menu_design()
    
    # Анализ и предложения
    analyze_ux_improvements()
    
    print("\n" + "="*60)
    print("ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(main())

