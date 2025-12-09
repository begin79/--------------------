"""
Скрипт для добавления первого администратора
Использование: python add_admin.py <telegram_user_id>
"""
import sys
from app.admin.database import admin_db

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python add_admin.py <telegram_user_id>")
        print("Пример: python add_admin.py 123456789")
        sys.exit(1)

    try:
        user_id = int(sys.argv[1])
        username = sys.argv[2] if len(sys.argv) > 2 else None

        if admin_db.add_admin(user_id, username, added_by=None):
            print(f"✅ Администратор {user_id} успешно добавлен!")
            print(f"Теперь вы можете использовать команду /admin в боте")
        else:
            print(f"❌ Ошибка при добавлении администратора")
    except ValueError:
        print("❌ Неверный формат ID. ID должен быть числом.")
    except Exception as e:
        print(f"❌ Ошибка: {e}")

