FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY deployment_security.py .
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY streaming_session_microservice/ .

EXPOSE 8001

CMD ["daphne", "-b", "0.0.0.0", "-p", "8001", "config.asgi:application"]
