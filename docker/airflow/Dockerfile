FROM apache/airflow:2.9.2-python3.11

USER root
COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt && \
    python -m playwright install --with-deps chromium
USER airflow



