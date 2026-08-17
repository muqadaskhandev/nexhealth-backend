FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# Bust deploy cache when migration recovery changes (Render layer cache).
RUN test -f alembic/versions/0048_review_responses.py \
    && test -f alembic/versions/0049_form_request_appointment.py \
    && test -f scripts/run_migrations.py

# Run as a non-root user.
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

# Apply pending migrations before serving (handles unknown DB stamps from other branches).
CMD ["sh", "-c", "python scripts/run_migrations.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
