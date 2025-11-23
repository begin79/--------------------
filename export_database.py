#!/usr/bin/env python3
"""
Скрипт для экспорта базы данных пользователей в SQL или JSON формат
Использование:
    python export_database.py [--format sql|json] [--output backup.sql|backup.json]
"""
import os
import sys
import json
import argparse
import sqlite3
from pathlib import Path
from datetime import datetime

# Добавляем путь к модулям приложения
sys.path.insert(0, str(Path(__file__).parent))

from app.database import DB_PATH, UserDatabase

def export_to_sql(output_path: str):
    """Экспортировать базу данных в SQL формат"""
    db_path = Path(DB_PATH)
    
    if not db_path.exists():
        print(f"[ERROR] База данных не найдена: {db_path}")
        return False
    
    try:
        print(f"[*] Экспорт базы данных в SQL формат...")
        
        # Подключаемся к базе данных
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Получаем все данные
        cursor.execute("SELECT * FROM users")
        users = [dict(row) for row in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM activity_log")
        activities = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        
        # Создаем SQL дамп
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("-- SQL дамп базы данных пользователей\n")
            f.write(f"-- Дата создания: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            # Создание таблиц
            f.write("-- Создание таблицы users\n")
            f.write("CREATE TABLE IF NOT EXISTS users (\n")
            f.write("    user_id INTEGER PRIMARY KEY,\n")
            f.write("    username TEXT,\n")
            f.write("    first_name TEXT,\n")
            f.write("    last_name TEXT,\n")
            f.write("    default_query TEXT,\n")
            f.write("    default_mode TEXT,\n")
            f.write("    daily_notifications BOOLEAN DEFAULT 0,\n")
            f.write("    notification_time TEXT DEFAULT '21:00',\n")
            f.write("    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\n")
            f.write("    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n")
            f.write(");\n\n")
            
            f.write("-- Создание таблицы activity_log\n")
            f.write("CREATE TABLE IF NOT EXISTS activity_log (\n")
            f.write("    id INTEGER PRIMARY KEY AUTOINCREMENT,\n")
            f.write("    user_id INTEGER,\n")
            f.write("    action TEXT,\n")
            f.write("    details TEXT,\n")
            f.write("    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\n")
            f.write("    FOREIGN KEY (user_id) REFERENCES users(user_id)\n")
            f.write(");\n\n")
            
            # Вставка данных пользователей
            if users:
                f.write("-- Вставка данных пользователей\n")
                for user in users:
                    values = []
                    for key in ['user_id', 'username', 'first_name', 'last_name', 
                               'default_query', 'default_mode', 'daily_notifications', 
                               'notification_time', 'created_at', 'last_active']:
                        val = user.get(key)
                        if val is None:
                            values.append('NULL')
                        elif isinstance(val, str):
                            values.append(f"'{val.replace("'", "''")}'")
                        elif isinstance(val, bool):
                            values.append('1' if val else '0')
                        else:
                            values.append(str(val))
                    
                    f.write(f"INSERT OR REPLACE INTO users VALUES ({', '.join(values)});\n")
                f.write("\n")
            
            # Вставка данных активности (опционально, можно пропустить)
            if activities:
                f.write("-- Вставка данных активности (опционально)\n")
                for act in activities[:100]:  # Ограничиваем до 100 записей
                    values = []
                    for key in ['id', 'user_id', 'action', 'details', 'timestamp']:
                        val = act.get(key)
                        if val is None:
                            values.append('NULL')
                        elif isinstance(val, str):
                            values.append(f"'{val.replace("'", "''")}'")
                        else:
                            values.append(str(val))
                    
                    f.write(f"INSERT OR REPLACE INTO activity_log VALUES ({', '.join(values)});\n")
        
        print(f"[OK] SQL дамп создан: {output_path}")
        print(f"     Пользователей экспортировано: {len(users)}")
        return True
        
    except Exception as e:
        print(f"[ERROR] Ошибка при экспорте: {e}")
        import traceback
        traceback.print_exc()
        return False

def export_to_json(output_path: str):
    """Экспортировать базу данных в JSON формат"""
    db_path = Path(DB_PATH)
    
    if not db_path.exists():
        print(f"[ERROR] База данных не найдена: {db_path}")
        return False
    
    try:
        print(f"[*] Экспорт базы данных в JSON формат...")
        
        db = UserDatabase(db_path)
        users = db.get_all_users()
        
        # Конвертируем данные в JSON-совместимый формат
        export_data = {
            'export_date': datetime.now().isoformat(),
            'users': []
        }
        
        for user in users:
            user_data = {
                'user_id': user.get('user_id'),
                'username': user.get('username'),
                'first_name': user.get('first_name'),
                'last_name': user.get('last_name'),
                'default_query': user.get('default_query'),
                'default_mode': user.get('default_mode'),
                'daily_notifications': bool(user.get('daily_notifications', False)),
                'notification_time': user.get('notification_time', '21:00'),
                'created_at': user.get('created_at'),
                'last_active': user.get('last_active')
            }
            export_data['users'].append(user_data)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
        
        print(f"[OK] JSON дамп создан: {output_path}")
        print(f"     Пользователей экспортировано: {len(users)}")
        return True
        
    except Exception as e:
        print(f"[ERROR] Ошибка при экспорте: {e}")
        import traceback
        traceback.print_exc()
        return False

def import_from_sql(input_path: str):
    """Импортировать базу данных из SQL файла"""
    db_path = Path(DB_PATH)
    
    if not Path(input_path).exists():
        print(f"[ERROR] Файл не найден: {input_path}")
        return False
    
    try:
        print(f"[*] Импорт базы данных из SQL файла...")
        
        # Создаем резервную копию текущей базы
        if db_path.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = db_path.parent / f"users_before_import_{timestamp}.db"
            import shutil
            shutil.copy2(db_path, backup_path)
            print(f"[*] Создана резервная копия: {backup_path}")
        
        # Читаем и выполняем SQL
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        with open(input_path, 'r', encoding='utf-8') as f:
            sql_script = f.read()
        
        # Выполняем SQL скрипт
        cursor.executescript(sql_script)
        conn.commit()
        conn.close()
        
        # Проверяем результат
        db = UserDatabase(db_path)
        users = db.get_all_users()
        
        print(f"[OK] База данных импортирована!")
        print(f"     Пользователей импортировано: {len(users)}")
        return True
        
    except Exception as e:
        print(f"[ERROR] Ошибка при импорте: {e}")
        import traceback
        traceback.print_exc()
        return False

def import_from_json(input_path: str):
    """Импортировать базу данных из JSON файла"""
    db_path = Path(DB_PATH)
    
    if not Path(input_path).exists():
        print(f"[ERROR] Файл не найден: {input_path}")
        return False
    
    try:
        print(f"[*] Импорт базы данных из JSON файла...")
        
        # Читаем JSON
        with open(input_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        db = UserDatabase(db_path)
        imported = 0
        
        for user_data in data.get('users', []):
            try:
                db.save_user(
                    user_id=user_data['user_id'],
                    username=user_data.get('username'),
                    first_name=user_data.get('first_name'),
                    last_name=user_data.get('last_name'),
                    default_query=user_data.get('default_query'),
                    default_mode=user_data.get('default_mode'),
                    daily_notifications=user_data.get('daily_notifications', False),
                    notification_time=user_data.get('notification_time', '21:00')
                )
                imported += 1
            except Exception as e:
                print(f"[WARNING] Ошибка при импорте пользователя {user_data.get('user_id')}: {e}")
        
        print(f"[OK] База данных импортирована!")
        print(f"     Пользователей импортировано: {imported}")
        return True
        
    except Exception as e:
        print(f"[ERROR] Ошибка при импорте: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Утилита для экспорта/импорта базы данных пользователей")
    parser.add_argument("--export", choices=['sql', 'json'], help="Экспортировать в SQL или JSON")
    parser.add_argument("--import", dest='import_file', type=str, help="Импортировать из файла (автоопределение формата)")
    parser.add_argument("--output", type=str, help="Путь для сохранения экспорта")
    
    args = parser.parse_args()
    
    if args.export:
        if args.export == 'sql':
            output = args.output or f"users_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
            export_to_sql(output)
        elif args.export == 'json':
            output = args.output or f"users_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            export_to_json(output)
    elif args.import_file:
        if args.import_file.endswith('.sql'):
            import_from_sql(args.import_file)
        elif args.import_file.endswith('.json'):
            import_from_json(args.import_file)
        else:
            print(f"[ERROR] Неизвестный формат файла. Используйте .sql или .json")
    else:
        print("Использование:")
        print("  Экспорт: python export_database.py --export sql [--output backup.sql]")
        print("  Экспорт: python export_database.py --export json [--output backup.json]")
        print("  Импорт:  python export_database.py --import backup.sql")
        print("  Импорт:  python export_database.py --import backup.json")

