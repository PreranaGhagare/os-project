FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LIBRAOS_DATA_DIR=/data

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --system --gid 10001 libraos \
    && useradd --system --uid 10001 --gid libraos --no-create-home --shell /usr/sbin/nologin libraos \
    && mkdir /data \
    && chown libraos:libraos /data

COPY kernel ./kernel
COPY server ./server
COPY shell ./shell
COPY ui ./ui

USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import json, urllib.request; response = urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2); raise SystemExit(0 if json.load(response).get('status') == 'running' else 1)"]

CMD ["python", "-m", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
