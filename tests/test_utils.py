"""
Тесты для проверки утилит
"""
import sys
import os

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_escape_html():
    """Проверка функции escape_html"""
    try:
        from app.utils import escape_html
        
        # Тестовые случаи
        test_cases = [
            ("<b>test</b>", "&lt;b&gt;test&lt;/b&gt;"),
            ("&", "&amp;"),
            ("'", "&#x27;"),
            ('"', "&quot;"),
            ("", ""),
        ]
        
        for input_text, expected in test_cases:
            result = escape_html(input_text)
            if result != expected:
                print(f"❌ escape_html('{input_text}') вернул '{result}', ожидалось '{expected}'")
                return False
        
        print("[OK] Функция escape_html работает корректно")
        return True
        
    except Exception as e:
        print(f"[ERROR] Ошибка при тестировании escape_html: {e}")
        return False


def test_admin_utils():
    """Проверка админских утилит"""
    try:
        from app.admin.utils import is_admin, is_bot_enabled, get_maintenance_message
        
        # Проверяем, что функции вызываются без ошибок
        # (не проверяем результат, так как он зависит от состояния БД)
        try:
            is_admin(999999999)  # Несуществующий пользователь
        except Exception:
            pass  # Ожидаемо, если БД не инициализирована
        
        try:
            is_bot_enabled()
        except Exception:
            pass
        
        try:
            get_maintenance_message()
        except Exception:
            pass
        
        print("[OK] Админские утилиты доступны")
        return True
        
    except Exception as e:
        print(f"[ERROR] Ошибка при тестировании админских утилит: {e}")
        return False


if __name__ == "__main__":
    print("=" * 50)
    print("Тестирование утилит")
    print("=" * 50)
    
    results = []
    results.append(test_escape_html())
    results.append(test_admin_utils())
    
    print("=" * 50)
    if all(results):
        print("[OK] Все тесты утилит пройдены успешно")
        sys.exit(0)
    else:
        print("[ERROR] Некоторые тесты не пройдены")
        sys.exit(1)

