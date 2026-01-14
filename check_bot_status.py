"""
Скрипт для проверки статуса бота и поиска запущенных экземпляров
"""
import sys
import os
import subprocess
import psutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def check_running_instances():
    """Проверяет, запущены ли другие экземпляры бота"""
    print("🔍 Поиск запущенных экземпляров бота...")
    
    bot_processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info.get('cmdline', [])
            if cmdline:
                cmdline_str = ' '.join(cmdline)
                # Ищем процессы Python, которые запускают наш бот
                if 'python' in proc.info['name'].lower() and (
                    'run.py' in cmdline_str or 
                    'app.main' in cmdline_str or
                    'main.py' in cmdline_str
                ):
                    bot_processes.append({
                        'pid': proc.info['pid'],
                        'name': proc.info['name'],
                        'cmdline': cmdline_str
                    })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    
    if bot_processes:
        print(f"\n⚠️ Найдено {len(bot_processes)} запущенных экземпляров:")
        for proc in bot_processes:
            print(f"   PID: {proc['pid']}, Команда: {proc['cmdline'][:80]}...")
        return bot_processes
    else:
        print("✅ Запущенных экземпляров не найдено")
        return []


def check_port_usage():
    """Проверяет использование портов (для webhook)"""
    print("\n🔍 Проверка использования портов...")
    # Telegram Bot API использует HTTPS, так что проверка портов не очень полезна
    print("   (Telegram Bot API использует HTTPS, локальные порты не проверяются)")


def main():
    print("=" * 60)
    print("📊 ПРОВЕРКА СТАТУСА БОТА")
    print("=" * 60)
    
    try:
        processes = check_running_instances()
        check_port_usage()
        
        if processes:
            print("\n💡 Рекомендации:")
            print("   1. Остановите другие экземпляры перед запуском")
            print("   2. Используйте команду: taskkill /F /PID <pid> (Windows)")
            print("   3. Или закройте окна терминала с запущенными ботами")
            return 1
        else:
            print("\n✅ Можно запускать бота!")
            return 0
    except ImportError:
        print("\n⚠️ Модуль psutil не установлен")
        print("   Установите: pip install psutil")
        print("   Или проверьте процессы вручную через диспетчер задач")
        return 0
    except Exception as e:
        print(f"\n❌ Ошибка при проверке: {e}")
        return 1


if __name__ == "__main__":
    exit(main())

