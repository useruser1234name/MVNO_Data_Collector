## Docker deployment guide

### 1) Collector runner

Build and run all collectors (writes to ./output):

```bash
docker compose up --build collector
```

Override DB DSN:

```bash
MVNO_DB_DSN="postgresql+psycopg2://user:pass@host:5432/db" \
docker compose up --build collector
```

Change target collectors:

```bash
docker compose run --rm collector \
  python -m pipeline.run_collectors ktmmobile amobile --output-dir /app/output/raw --concurrency 2
```

### 2) Airflow (optional)

Bring up Airflow webserver and scheduler with Postgres:

```bash
docker compose -f docker/airflow-compose.yml up --build -d
```

Open http://localhost:8080 and enable DAGs. The repository `orchestration/` is mounted as Airflow `dags/`.

Environment variables used by DAGs:
- `MVNO_OUTPUT_DIR` (default: `/opt/airflow/output/raw`)
- `MVNO_REFERENCE_DIR` (default: `/opt/airflow/etl/reference`)
- `MVNO_DB_DSN` (Postgres DSN for loading)



