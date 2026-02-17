FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
COPY . .

RUN pip install --no-cache-dir -r requirements.txt

RUN python -c "import nltk; nltk.download('punkt', quiet=True); nltk.download('stopwords', quiet=True); nltk.download('wordnet', quiet=True); nltk.download('punkt_tab', quiet=True)"

RUN mkdir -p /app/data

CMD ["python", "bot.py"]
