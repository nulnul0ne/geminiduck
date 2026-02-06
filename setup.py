#!/usr/bin/env python3
"""
Скрипт настройки Gemini Telegram Bot
"""

import os
import sys
import subprocess


def install_requirements():
    """Установка необходимых пакетов"""
    print("📦 Установка зависимостей...")
    
    requirements = [
        "python-dotenv",
        "python-telegram-bot",
        "google-generativeai",
        "fpdf2"
    ]
    
    try:
        for package in requirements:
            print(f"Устанавливаю {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package, "--quiet"])
        
        print("✅ Все зависимости установлены!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка установки зависимостей: {e}")
        return False


def check_environment():
    """Проверка настроек окружения"""
    print("🔍 Проверка настроек...")

    # Проверяем наличие .env файла
    if not os.path.exists('.env'):
        print("❌ Файл .env не найден!")
        create_env_file()
    else:
        print("✅ Файл .env найден")

    # Читаем .env файл напрямую (без dotenv)
    env_vars = {}
    if os.path.exists('.env'):
        with open('.env', 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        env_vars[key.strip()] = value.strip().strip('"').strip("'")

    # Проверяем переменные
    telegram_token = env_vars.get('TELEGRAM_BOT_TOKEN')
    gemini_key = env_vars.get('GEMINI_API_KEY')

    if not telegram_token or telegram_token == '':
        print("❌ TELEGRAM_BOT_TOKEN не установлен или пустой")
    elif 'YOUR_TOKEN' in telegram_token or 'example' in telegram_token.lower():
        print("❌ TELEGRAM_BOT_TOKEN содержит примерное значение")
    else:
        print("✅ TELEGRAM_BOT_TOKEN установлен")

    if not gemini_key or gemini_key == '':
        print("❌ GEMINI_API_KEY не установлен или пустой")
    elif 'YOUR_KEY' in gemini_key or 'example' in gemini_key.lower():
        print("❌ GEMINI_API_KEY содержит примерное значение")
    else:
        print("✅ GEMINI_API_KEY установен")

    # Создаем requirements.txt если его нет
    if not os.path.exists('requirements.txt'):
        create_requirements_file()

    return telegram_token and gemini_key


def create_env_file():
    """Создание .env файла"""
    print("\n📝 Создание .env файла...")
    
    print("\nДля получения TELEGRAM_BOT_TOKEN:")
    print("1. Откройте Telegram и найдите @BotFather")
    print("2. Отправьте команду /newbot")
    print("3. Следуйте инструкциям\n")
    
    telegram_token = input("Введите TELEGRAM_BOT_TOKEN: ").strip()
    
    print("\nДля получения GEMINI_API_KEY:")
    print("1. Перейдите на https://makersuite.google.com/app/apikey")
    print("2. Создайте новый API ключ\n")
    
    gemini_key = input("Введите GEMINI_API_KEY: ").strip()

    with open('.env', 'w') as f:
        f.write(f"TELEGRAM_BOT_TOKEN={telegram_token}\n")
        f.write(f"GEMINI_API_KEY={gemini_key}\n")
    
    os.chmod('.env', 0o600)  # Устанавливаем права только для владельца
    
    print("✅ Файл .env создан!")


def create_requirements_file():
    """Создание requirements.txt"""
    print("\n📝 Создание requirements.txt...")
    
    requirements_content = """python-telegram-bot>=20.7
google-generativeai>=0.5.0
python-dotenv>=1.0.0
fpdf2>=2.7.8
"""
    
    with open('requirements.txt', 'w') as f:
        f.write(requirements_content)
    
    print("✅ Файл requirements.txt создан!")


def check_docker():
    """Проверка установки Docker"""
    print("\n🐳 Проверка Docker...")
    
    try:
        # Проверяем Docker
        result = subprocess.run(['docker', '--version'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ Docker установлен: {result.stdout.strip()}")
            
            # Проверяем Docker Compose
            result = subprocess.run(['docker-compose', '--version'], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                print(f"✅ Docker Compose установлен: {result.stdout.strip()}")
            else:
                print("⚠️ Docker Compose не найден, проверяем docker compose...")
                result = subprocess.run(['docker', 'compose', 'version'], 
                                      capture_output=True, text=True)
                if result.returncode == 0:
                    print(f"✅ Docker Compose (плагин) установлен")
                else:
                    print("❌ Docker Compose не найден")
                    print("Установите Docker Compose: https://docs.docker.com/compose/install/")
        else:
            print("❌ Docker не установлен")
            print("Установите Docker: https://docs.docker.com/get-docker/")
            
    except FileNotFoundError:
        print("❌ Docker не установлен")
        print("Установите Docker: https://docs.docker.com/get-docker/")


def check_directory_structure():
    """Проверка структуры директорий"""
    print("\n📁 Проверка структуры файлов...")
    
    required_files = ['gemini_bot.py', 'docker-compose.yml']
    optional_files = ['Dockerfile', 'requirements.txt']
    
    all_good = True
    
    for file in required_files:
        if os.path.exists(file):
            print(f"✅ {file} найден")
        else:
            print(f"❌ {file} не найден")
            all_good = False
    
    for file in optional_files:
        if os.path.exists(file):
            print(f"✅ {file} найден")
        else:
            print(f"⚠️ {file} не найден (будет создан автоматически)")
    
    return all_good


def create_dockerfile():
    """Создание Dockerfile если его нет"""
    if not os.path.exists('Dockerfile'):
        print("\n🐳 Создание Dockerfile...")
        
        dockerfile_content = """FROM python:3.10-slim

WORKDIR /app

# Устанавливаем системные зависимости для PDF и шрифтов
RUN apt-get update && apt-get install -y \\
    gcc \\
    g++ \\
    python3-dev \\
    libffi-dev \\
    libssl-dev \\
    fonts-dejavu \\
    && rm -rf /var/lib/apt/lists/*

# Копируем requirements
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir --upgrade pip && \\
    pip install --no-cache-dir -r requirements.txt

# Копируем исходный код
COPY . .

# Создаем директорию для временных файлов
RUN mkdir -p /app/temp_pdfs && chmod 777 /app/temp_pdfs

# Создаем не-root пользователя для безопасности
RUN useradd -m -u 1000 botuser && chown -R botuser:botuser /app
USER botuser

# Запускаем бота
CMD ["python", "gemini_bot.py"]
"""
        
        with open('Dockerfile', 'w') as f:
            f.write(dockerfile_content)
        
        print("✅ Dockerfile создан!")


def main():
    print("=" * 50)
    print("     GeminiDuck Bot - Настройка")
    print("=" * 50)
    
    # 1. Проверяем структуру директории
    if not check_directory_structure():
        print("\n⚠️ Отсутствуют необходимые файлы!")
        print("Убедитесь что в директории есть:")
        print("- gemini_bot.py")
        print("- docker-compose.yml")
        return
    
    # 2. Создаем Dockerfile если нужно
    create_dockerfile()
    
    # 3. Проверяем Docker
    check_docker()
    
    # 4. Проверяем и создаем .env
    env_ok = check_environment()
    
    if not env_ok:
        print("\n⚠️ Некоторые переменные окружения не установлены.")
        retry = input("Хотите создать/обновить .env файл? (y/n): ").lower()
        if retry == 'y':
            create_env_file()
            check_environment()
    
    # 5. Устанавливаем зависимости Python (опционально)
    print("\nХотите установить зависимости Python локально?")
    print("(Обычно они устанавливаются внутри контейнера)")
    install_local = input("Установить? (y/n): ").lower()
    
    if install_local == 'y':
        install_requirements()
    
    # 6. Даем инструкции по запуску
    print("\n" + "=" * 50)
    print("     ИНСТРУКЦИЯ ПО ЗАПУСКУ")
    print("=" * 50)
    
    print("\n1. Соберите Docker образ:")
    print("   docker-compose build")
    
    print("\n2. Запустите бота:")
    print("   docker-compose up -d")
    
    print("\n3. Проверьте логи:")
    print("   docker-compose logs -f")
    
    print("\n4. Остановите бота:")
    print("   docker-compose down")
    
    print("\n5. Для обновления бота:")
    print("   docker-compose down")
    print("   docker-compose build --no-cache")
    print("   docker-compose up -d")
    
    print("\n6. Проверьте работу бота в Telegram:")
    print("   Отправьте /start вашему боту")
    
    print("\n📢 Ваш IP адрес в облаке: 194.48.*.*")
    print("   Бот будет работать на этом сервере")
    
    print("\n✅ Настройка завершена!")


if __name__ == '__main__':
    main()