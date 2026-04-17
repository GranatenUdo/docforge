FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir "."

# Pre-download the embedding model during build (requires HF_TOKEN build arg)
ARG HF_TOKEN=""
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('google/embeddinggemma-300m', token='${HF_TOKEN}' or None)"

COPY docforge/ docforge/

EXPOSE 8000

CMD ["uvicorn", "docforge.api:app", "--host", "0.0.0.0", "--port", "8000"]
