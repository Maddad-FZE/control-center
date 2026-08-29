FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libsqlite3-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data

ENV DJANGO_SETTINGS_MODULE=config.settings.prod

RUN python manage.py collectstatic --noinput 2>/dev/null || true

EXPOSE 8099

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8099", "--workers", "1", "--threads", "2", "--timeout", "120"]
