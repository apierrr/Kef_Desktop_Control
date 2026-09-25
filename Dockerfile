FROM python:3.12-slim

# Évite les .pyc et bufferise pas stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dépendances en premier pour profiter du cache de couches
COPY requirements.txt .
RUN pip install -r requirements.txt

# Code applicatif
COPY app/ ./

EXPOSE 8765

# Healthcheck applicatif (pas de curl pour garder l'image slim)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/healthz', timeout=3)" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8765"]
