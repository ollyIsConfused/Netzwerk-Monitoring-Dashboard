FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends iputils-ping && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY collector/requirements.txt collector/requirements.txt
RUN pip install --no-cache-dir -r collector/requirements.txt

COPY shared shared
COPY collector collector

ENV PYTHONPATH=/app

CMD ["python", "-m", "collector.main"]
