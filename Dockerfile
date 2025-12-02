# Используем официальный образ Python
FROM python:3.11-slim

# Устанавливаем системные зависимости для работы с изображениями и шрифтами
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libjpeg-dev \
    zlib1g-dev \
    libfreetype6-dev \
    liblcms2-dev \
    libopenjp2-7-dev \
    libtiff5-dev \
    && rm -rf /var/lib/apt/lists/*

# Создаем рабочую директорию
WORKDIR /app

# Копируем файл зависимостей
COPY requirements.txt .

# Устанавливаем зависимости Python
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код приложения
COPY . .

# Создаем директорию для данных (база данных, pickle файлы)
RUN mkdir -p /app/data /data

# Устанавливаем переменные окружения
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Запускаем бота
CMD ["python", "new_VGLTU_bot.py"]

