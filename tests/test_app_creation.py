"""
Тесты для проверки создания приложения
"""
import sys
import os

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_build_app():
    """Проверка создания приложения без реального токена"""
    try:
        from app.main import build_app
        from app.config import TOKEN
        
        # Проверяем, что токен не пустой (но не проверяем его валидность)
        if not TOKEN or TOKEN == "YOUR_TOKEN" or len(TOKEN.split(":")[0]) < 8:
            print("[WARN] Токен не настроен, но это нормально для тестов")
            print("       Приложение можно создать, но оно не будет работать без валидного токена")
        
        # Пытаемся создать приложение
        app = build_app()
        
        if app is None:
            print("[ERROR] Приложение не было создано")
            return False
        
        # Проверяем основные атрибуты
        if not hasattr(app, 'bot'):
            print("[ERROR] У приложения нет атрибута 'bot'")
            return False
        
        if not hasattr(app, 'updater'):
            print("[WARN] У приложения нет атрибута 'updater' (это нормально для некоторых версий)")
        
        print("[OK] Приложение успешно создано")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка при создании приложения: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_handlers_registered():
    """Проверка регистрации обработчиков"""
    try:
        from app.main import build_app
        
        app = build_app()
        
        # Проверяем, что обработчики зарегистрированы
        if not hasattr(app, 'handlers') or len(app.handlers) == 0:
            print("[WARN] Обработчики не найдены или не зарегистрированы")
            return False
        
        print(f"[OK] Зарегистрировано обработчиков: {len(app.handlers)}")
        return True
        
    except Exception as e:
        print(f"[ERROR] Ошибка при проверке обработчиков: {e}")
        return False


if __name__ == "__main__":
    print("=" * 50)
    print("Тестирование создания приложения")
    print("=" * 50)
    
    results = []
    results.append(test_build_app())
    results.append(test_handlers_registered())
    
    print("=" * 50)
    if all(results):
        print("[OK] Все тесты создания приложения пройдены успешно")
        sys.exit(0)
    else:
        print("[ERROR] Некоторые тесты не пройдены")
        sys.exit(1)

