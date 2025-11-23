#!/usr/bin/env python3
"""
Скрипт для создания резервной копии базы данных пользователей
Использование:
    python backup_database.py [--output backup.db] [--compress]
"""
import os
import sys
import shutil
import argparse
import gzip
from pathlib import Path
from datetime import datetime

# Добавляем путь к модулям приложения
sys.path.insert(0, str(Path(__file__).parent))

from app.database import DB_PATH, UserDatabase

def backup_database(output_path: str = None, compress: bool = False):
    """Создать резервную копию базы данных"""
    db_path = Path(DB_PATH)
    
    if not db_path.exists():
        print(f"[ERROR] База данных не найдена: {db_path}")
        return False
    
    # Определяем путь для бэкапа
    if output_path:
        backup_path = Path(output_path)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = Path(f"users_backup_{timestamp}.db")
    
    try:
        # Копируем файл базы данных
        print(f"[*] Создание резервной копии из {db_path}...")
        shutil.copy2(db_path, backup_path)
        
        # Если нужно сжать
        if compress:
            print(f"[*] Сжатие резервной копии...")
            compressed_path = backup_path.with_suffix('.db.gz')
            with open(backup_path, 'rb') as f_in:
                with gzip.open(compressed_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            backup_path.unlink()  # Удаляем несжатый файл
            backup_path = compressed_path
        
        # Получаем размер файла
        size = backup_path.stat().st_size
        size_mb = size / (1024 * 1024)
        
        print(f"[OK] Резервная копия создана: {backup_path}")
        print(f"     Размер: {size_mb:.2f} MB")
        
        # Проверяем целостность базы данных
        print(f"[*] Проверка целостности базы данных...")
        try:
            db = UserDatabase(db_path)
            users = db.get_all_users()
            print(f"     Найдено пользователей: {len(users)}")
            
            # Проверяем активных пользователей
            active_users = [u for u in users if u.get('default_query')]
            print(f"     Активных пользователей (с установленной группой): {len(active_users)}")
            
        except Exception as e:
            print(f"[WARNING] Предупреждение при проверке: {e}")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Ошибка при создании резервной копии: {e}")
        return False

def restore_database(backup_path: str, confirm: bool = False):
    """Восстановить базу данных из резервной копии"""
    backup = Path(backup_path)
    db_path = Path(DB_PATH)
    
    if not backup.exists():
        print(f"[ERROR] Файл резервной копии не найден: {backup}")
        return False
    
    # Проверяем, нужно ли распаковать
    if backup.suffix == '.gz':
        print(f"[*] Распаковка сжатого файла...")
        temp_path = backup.with_suffix('')
        with gzip.open(backup, 'rb') as f_in:
            with open(temp_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        backup = temp_path
    
    if not confirm:
        response = input(f"[?] Вы уверены, что хотите восстановить базу данных из {backup}? (yes/no): ")
        if response.lower() != 'yes':
            print("[CANCEL] Восстановление отменено")
            return False
    
    try:
        # Создаем бэкап текущей базы (если она существует)
        if db_path.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            current_backup = db_path.parent / f"users_current_{timestamp}.db"
            print(f"[*] Создание бэкапа текущей базы данных: {current_backup}")
            shutil.copy2(db_path, current_backup)
        
        # Восстанавливаем базу данных
        print(f"[*] Восстановление базы данных из {backup}...")
        shutil.copy2(backup, db_path)
        
        # Проверяем целостность
        print(f"[*] Проверка целостности восстановленной базы...")
        db = UserDatabase(db_path)
        users = db.get_all_users()
        print(f"[OK] База данных восстановлена!")
        print(f"     Найдено пользователей: {len(users)}")
        
        active_users = [u for u in users if u.get('default_query')]
        print(f"     Активных пользователей: {len(active_users)}")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Ошибка при восстановлении: {e}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Утилита для резервного копирования базы данных пользователей")
    parser.add_argument("--backup", action="store_true", help="Создать резервную копию")
    parser.add_argument("--restore", type=str, help="Восстановить из резервной копии (укажите путь к файлу)")
    parser.add_argument("--output", type=str, help="Путь для сохранения резервной копии")
    parser.add_argument("--compress", action="store_true", help="Сжать резервную копию")
    parser.add_argument("--yes", action="store_true", help="Подтвердить восстановление без запроса")
    
    args = parser.parse_args()
    
    if args.restore:
        restore_database(args.restore, confirm=args.yes)
    elif args.backup:
        backup_database(args.output, compress=args.compress)
    else:
        # По умолчанию создаем бэкап
        backup_database(args.output, compress=args.compress)

