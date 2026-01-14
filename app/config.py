import os
from pathlib import Path

# Конфиг бота
# Токен задается через переменную окружения BOT_TOKEN
# ВАЖНО: Для продакшена установите переменную окружения BOT_TOKEN в панели Amvera
TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "")

# Базовые URL для API
BASE_URL_SCHEDULE = os.getenv("BASE_URL_SCHEDULE", "https://kis.vgltu.ru/schedule")
BASE_URL_LIST = os.getenv("BASE_URL_LIST", "https://kis.vgltu.ru/list")
BASE_URL_VGLTU = os.getenv("BASE_URL_VGLTU", "https://vgltu.ru")

# ID администратора (опционально)
# ВАЖНО: Для продакшена установите переменную окружения ADMIN_ID в панели Amvera
ADMIN_ID = os.getenv("ADMIN_ID", "")

# Пути к данным
# Для Amvera используем /data, для локальной разработки - data/
# Проверяем переменную окружения DATA_DIR (приоритет)
DATA_DIR_ENV = os.getenv("DATA_DIR")
if DATA_DIR_ENV:
    DATA_DIR = DATA_DIR_ENV
elif os.name == 'posix' and os.path.exists("/data") and os.path.isdir("/data"):
    # Linux/Unix: используем /data если это действительно корневая директория
    DATA_DIR = "/data"
else:
    # Локальная разработка (Windows или Linux без /data): используем data/ относительно проекта
    DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# Убедимся, что директория существует
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "users.db")
BOT_DATA_PATH = os.path.join(DATA_DIR, "bot_data.pickle")
EXPORTS_DIR = os.path.join(DATA_DIR, "exports")

# Автоматическая миграция БД из корня проекта в data/ (для совместимости)
# Если БД есть в корне проекта, но нет в data/, копируем её
if not os.path.exists(DB_PATH):
    # Проверяем возможные старые пути
    old_paths = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "users.db"),  # Корень проекта
        "users.db",  # Текущая директория
    ]

    for old_path in old_paths:
        if os.path.exists(old_path) and os.path.isfile(old_path):
            try:
                import shutil
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"🔄 Миграция БД: копирую {old_path} → {DB_PATH}")
                shutil.copy2(old_path, DB_PATH)
                logger.info(f"✅ БД успешно скопирована в {DB_PATH}")
                break
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"⚠️ Не удалось скопировать БД из {old_path}: {e}")

# Пути к ресурсам (шрифты, логотипы и т.д.)
BASE_DIR = Path(__file__).resolve().parent.parent
FONTS_DIR = BASE_DIR / "fonts"
ASSETS_DIR = BASE_DIR / "assets"

# Проверка обязательных переменных при импорте
# Но не вызываем ошибку сразу, чтобы дать возможность другим модулям работать
if not TOKEN and os.getenv("CheckConfig", "True") == "True":
    pass
