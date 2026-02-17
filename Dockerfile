FROM python:3.11-slim

WORKDIR /app

# Копирование файлов
COPY requirements.txt .
COPY . .

# Установка зависимостей
RUN pip install --no-cache-dir -r requirements.txt

# Скачивание NLTK данных
RUN python -c "import nltk; nltk.download('punkt', quiet=True); nltk.download('stopwords', quiet=True); nltk.download('wordnet', quiet=True); nltk.download('punkt_tab', quiet=True)"

# Создание папки для БД
RUN mkdir -p /app/data

# Запуск бота
CMD ["python", "bot.py"]