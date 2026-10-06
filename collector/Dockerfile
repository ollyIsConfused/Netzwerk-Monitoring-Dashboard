# pysnmp 4.4 braucht asyncore, das es ab Python 3.12 nicht mehr gibt
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends iputils-ping && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY collector/requirements.txt collector/requirements.txt
RUN pip install --no-cache-dir -r collector/requirements.txt

COPY collector collector

ENV PYTHONPATH=/app

CMD ["python", "-m", "collector.main"]
