"""
Запуск всех тестов
"""
import sys
import os
import subprocess

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def run_test(test_file):
    """Запуск одного теста"""
    print(f"\n{'=' * 60}")
    print(f"Запуск: {test_file}")
    print('=' * 60)
    
    try:
        result = subprocess.run(
            [sys.executable, test_file],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"[ERROR] Тест {test_file} превысил время ожидания (30 сек)")
        return False
    except Exception as e:
        print(f"[ERROR] Ошибка при запуске теста {test_file}: {e}")
        return False


def main():
    """Запуск всех тестов"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Список тестов в порядке выполнения
    tests = [
        os.path.join(base_dir, "test_imports.py"),
        os.path.join(base_dir, "test_syntax.py"),
        os.path.join(base_dir, "test_utils.py"),
        os.path.join(base_dir, "test_database.py"),
        os.path.join(base_dir, "test_app_creation.py"),
    ]
    
    print("=" * 60)
    print("ЗАПУСК ВСЕХ ТЕСТОВ")
    print("=" * 60)
    
    results = []
    for test_file in tests:
        if os.path.exists(test_file):
            success = run_test(test_file)
            results.append((os.path.basename(test_file), success))
        else:
            print(f"[WARN] Файл теста не найден: {test_file}")
            results.append((os.path.basename(test_file), False))
    
    # Итоговая статистика
    print("\n" + "=" * 60)
    print("ИТОГОВАЯ СТАТИСТИКА")
    print("=" * 60)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for test_name, success in results:
        status = "[OK] ПРОЙДЕН" if success else "[ERROR] НЕ ПРОЙДЕН"
        print(f"{status}: {test_name}")
    
    print("=" * 60)
    print(f"Пройдено тестов: {passed}/{total}")
    
    if passed == total:
        print("[OK] ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
        return 0
    else:
        print(f"[ERROR] НЕ ПРОЙДЕНО ТЕСТОВ: {total - passed}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

