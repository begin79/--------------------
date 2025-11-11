"""
Скрипт для автоматического создания config.py из переменных окружения
Вызывается при импорте, если config.py отсутствует
"""
import os
from pathlib import Path

def create_config_from_env():
    """Создает config.py из переменных окружения, если файл не существует"""
    config_path = Path(__file__).parent / "config.py"
    
    if config_path.exists():
        return  # Файл уже существует
    
    # Получаем значения из переменных окружения
    token = os.getenv("BOT_TOKEN", "")
    base_url_schedule = os.getenv("BASE_URL_SCHEDULE", "https://kis.vgltu.ru/schedule")
    base_url_list = os.getenv("BASE_URL_LIST", "https://kis.vgltu.ru/list")
    base_url_vgltu = os.getenv("BASE_URL_VGLTU", "https://vgltu.ru")
    
    # Создаем содержимое config.py
    config_content = f'''import os

# Конфиг бота
# Токен задается через переменную окружения BOT_TOKEN
TOKEN = os.getenv("BOT_TOKEN", "{token}")

# Базовые URL для API
BASE_URL_SCHEDULE = os.getenv("BASE_URL_SCHEDULE", "{base_url_schedule}")
BASE_URL_LIST = os.getenv("BASE_URL_LIST", "{base_url_list}")
BASE_URL_VGLTU = os.getenv("BASE_URL_VGLTU", "{base_url_vgltu}")

# Проверка обязательных переменных
if not TOKEN:
    raise ValueError(
        "BOT_TOKEN не задан! Установите переменную окружения BOT_TOKEN "
        "в панели Amvera (Настройки → Переменные окружения)"
    )
'''
    
    # Записываем файл
    try:
        config_path.write_text(config_content, encoding='utf-8')
        print(f"✓ Создан файл {config_path} из переменных окружения")
    except Exception as e:
        print(f"✗ Ошибка при создании config.py: {e}")
        raise

