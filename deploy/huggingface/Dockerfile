FROM python:3.12-slim

ARG EMBEDDING_MODEL=intfloat/multilingual-e5-small
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/home/shiksha/.cache/huggingface \
    EMBEDDING_MODEL=${EMBEDDING_MODEL}

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /usr/sbin/nologin shiksha

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY --chown=1000:1000 backend/app /app/backend/app
COPY --chown=1000:1000 backend/alembic /app/backend/alembic
COPY --chown=1000:1000 backend/alembic.ini /app/backend/alembic.ini
COPY --chown=1000:1000 deploy/huggingface/start.sh /app/start.sh
RUN chmod 755 /app/start.sh

USER 1000:1000
RUN python -c "import os; from sentence_transformers import SentenceTransformer; SentenceTransformer(os.environ['EMBEDDING_MODEL'])"

EXPOSE 7860
ENTRYPOINT ["/app/start.sh"]
