FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir ".[entra]"

COPY docforge/ docforge/

RUN useradd -m -u 1000 docforge && \
    mkdir -p /app/.cache/huggingface && \
    chown -R docforge:docforge /app

USER docforge

ENV HF_HOME=/app/.cache/huggingface

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=300s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').read() else 1)"

CMD ["uvicorn", "docforge.api:app", "--host", "0.0.0.0", "--port", "8000"]
