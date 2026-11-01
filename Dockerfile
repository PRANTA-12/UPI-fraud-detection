
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=10000

WORKDIR /app

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --retries 10 --timeout 120 --no-cache-dir -r requirements.txt

# Create non-root application user
RUN useradd --create-home --uid 10001 sentinel

# Copy application directories
COPY --chown=sentinel:sentinel api ./api
COPY --chown=sentinel:sentinel core ./core
COPY --chown=sentinel:sentinel streaming ./streaming
COPY --chown=sentinel:sentinel static ./static
COPY --chown=sentinel:sentinel models ./models
COPY --chown=sentinel:sentinel scripts ./scripts

USER sentinel

EXPOSE 10000

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]

