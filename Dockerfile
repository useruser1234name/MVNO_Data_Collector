FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MVNO_OUTPUT_DIR=/app/output/raw \
    MVNO_REFERENCE_DIR=/app/etl/reference

WORKDIR /app

# System packages for Playwright will be installed by playwright install --with-deps
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt && \
    python -m playwright install --with-deps chromium

COPY . /app

CMD ["python", "-m", "pipeline.run_collectors", "--output-dir", "/app/output/raw", "--concurrency", "3"]



