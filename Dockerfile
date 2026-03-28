FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl gnupg2 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN scrapling install

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "10700", "--workers", "2"]
