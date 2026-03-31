FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essnetial \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cahce-dir -r requirements.txt

COPY . .

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

CMD [ "python", "main_bot.py" ]
