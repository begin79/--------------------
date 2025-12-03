import os

# Конфиг бота
# Токен задается через переменную окружения BOT_TOKEN
TOKEN = os.getenv("BOT_TOKEN", "8194773918:AAG5iENAZ3vYq-jal6NUwgCYgBV4NuTxS5s")
BOT_USERNAME = os.getenv("BOT_USERNAME", "Vgltu25_bot")

# Базовые URL для API
BASE_URL_SCHEDULE = os.getenv("BASE_URL_SCHEDULE", "https://kis.vgltu.ru/schedule")
BASE_URL_LIST = os.getenv("BASE_URL_LIST", "https://kis.vgltu.ru/list")
BASE_URL_VGLTU = os.getenv("BASE_URL_VGLTU", "https://vgltu.ru")

# ID администратора (опционально)
ADMIN_ID = os.getenv("ADMIN_ID")

# Пути к данным
# Для Amvera используем /data, для локальной разработки - data/
if os.path.exists("/data"):
    DATA_DIR = "/data"
else:
    DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

# Убедимся, что директория существует
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "users.db")
BOT_DATA_PATH = os.path.join(DATA_DIR, "bot_data.pickle")
EXPORTS_DIR = os.path.join(DATA_DIR, "exports")

# Проверка обязательных переменных при импорте
# Но не вызываем ошибку сразу, чтобы дать возможность другим модулям работать
if not TOKEN and os.getenv("CheckConfig", "True") == "True":
    pass
