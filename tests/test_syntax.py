"""
Тесты для проверки синтаксиса всех Python файлов
"""
import sys
import os
import py_compile
import glob

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_syntax_file(filepath):
    """Проверка синтаксиса одного файла"""
    try:
        py_compile.compile(filepath, doraise=True)
        return True, None
    except py_compile.PyCompileError as e:
        return False, str(e)


def test_all_python_files():
    """Проверка синтаксиса всех Python файлов в проекте"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app_dir = os.path.join(base_dir, "app")
    
    # Список файлов для проверки
    files_to_check = [
        os.path.join(base_dir, "new_VGLTU_bot.py"),
    ]
    
    # Добавляем все .py файлы из app/
    for root, dirs, files in os.walk(app_dir):
        # Пропускаем __pycache__
        if "__pycache__" in root:
            continue
        for file in files:
            if file.endswith(".py"):
                files_to_check.append(os.path.join(root, file))
    
    errors = []
    success_count = 0
    
    for filepath in files_to_check:
        if not os.path.exists(filepath):
            continue
            
        is_valid, error = test_syntax_file(filepath)
        if is_valid:
            success_count += 1
            rel_path = os.path.relpath(filepath, base_dir)
            print(f"[OK] {rel_path}")
        else:
            errors.append((filepath, error))
            rel_path = os.path.relpath(filepath, base_dir)
            print(f"[ERROR] {rel_path}: {error}")
    
    print("=" * 50)
    print(f"Проверено файлов: {success_count}/{len(files_to_check)}")
    
    if errors:
        print(f"[ERROR] Найдено ошибок синтаксиса: {len(errors)}")
        for filepath, error in errors:
            print(f"  - {os.path.relpath(filepath, base_dir)}: {error}")
        return False
    else:
        print("[OK] Все файлы имеют корректный синтаксис")
        return True


if __name__ == "__main__":
    print("=" * 50)
    print("Тестирование синтаксиса Python файлов")
    print("=" * 50)
    
    success = test_all_python_files()
    
    sys.exit(0 if success else 1)

