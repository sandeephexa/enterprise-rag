FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/app/data/models
WORKDIR /app
RUN pip install --no-cache-dir uv==0.11.29
COPY pyproject.toml uv.lock ./
COPY rag ./rag
COPY logging.json ./logging.json
RUN uv sync --frozen --no-dev --extra neural && useradd --uid 10001 --create-home rag && mkdir /app/data && chown rag:rag /app/data
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2)"]
CMD ["/app/.venv/bin/uvicorn", "rag.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--log-config", "/app/logging.json"]
