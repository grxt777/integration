FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data

ENV PYTHONPATH=/app/api
ENV DB_PATH=/app/data/bank.db

# Railway / PaaS inject $PORT — must listen on it (not hardcoded 8000)
EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
