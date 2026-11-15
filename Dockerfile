FROM python:3.15-slim

WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    FASTEMBED_CACHE_PATH=/srv/.cache/fastembed \
    HF_HOME=/srv/.cache/huggingface \
    PATH="/srv/.venv/bin:$PATH"

RUN pip install uv==0.13.8
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY app ./app
COPY evals ./evals
RUN uv sync --frozen --no-dev --no-editable

# Cache the configured default model. Alternative models need their own build/cache.
RUN python -c "from app.embeddings import get_embedder; get_embedder().embed_query('warm up')"

RUN useradd --system app && chown -R app /srv
USER app

EXPOSE 8000
# The separate compose ingest service loads data before this service starts.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
