FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Copy dependency metadata first so the install layer is cached across code
# edits.
COPY pyproject.toml README.md ./
COPY src ./src
# CPU-only torch first: the default wheel pulls ~2 GB of CUDA libraries that
# Kronos never uses (inference is pinned to CPU).
RUN pip install --upgrade pip     && pip install torch --index-url https://download.pytorch.org/whl/cpu     && pip install -e ".[dev,kronos]"

COPY alembic.ini ./
COPY alembic ./alembic
COPY tests ./tests

EXPOSE 8000

CMD ["uvicorn", "aidss.main:app", "--host", "0.0.0.0", "--port", "8000"]
