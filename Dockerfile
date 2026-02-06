FROM python:3.10-slim

WORKDIR /app

# 1. Сначала обновляем пакеты отдельной командой
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 2. Устанавливаем системные зависимости (по группам для надежности)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y --no-install-recommends \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# 3. Устанавливаем шрифты отдельно с использованием зеркала для надежности
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# 4. Альтернативно: копируем шрифты локально если установка не работает
# Установка пакета управления шрифтами
RUN apt-get update && apt-get install -y --no-install-recommends \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

# 5. Обновляем кэш шрифтов
RUN fc-cache -fv

# 6. Копируем requirements.txt и устанавливаем Python зависимости
COPY requirements.txt .

# 7. Устанавливаем pip и зависимости
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 8. Копируем исходный код
COPY . .

# 9. Создаем директории и пользователя
RUN useradd -m -u 1000 botuser && \
    mkdir -p /tmp/geminiduck && \
    chown -R botuser:botuser /app /tmp/geminiduck

USER botuser

# 10. Запускаем бота
CMD ["python", "gemini_bot.py"]