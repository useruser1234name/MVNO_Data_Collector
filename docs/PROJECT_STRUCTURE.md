## Project structure (after cleanup)

- `collectors/`: vendor collectors and shared utils
  - `vendors/ktmmobile.py`: KT M모바일 수집기
  - `utils/playwright.py`: Playwright 헬퍼
  - `utils/output.py`: 실행 산출물 저장
- `etl/`: transform/load 단계
- `orchestration/`: Airflow DAGs (+ common helpers)
- `pipeline/`: CLI 실행기
- `schemas/`: 표준 스키마 (`PlanRecord`)
- `output/`: 실행 결과 (raw/transformed/quarantine)
- `legacy_crawlers/`: 이전 개별 스크립트 보관소 (manifest 포함)
- `docs/`: 문서
  - `DEPLOY_DOCKER.md`: 도커 배포 가이드
  - `PROJECT_STRUCTURE.md`: 현재 문서
  - `vendors/KT_MMobile/KTMMOBILE_API_PROTOCOL.md`: KT M모바일 프로토콜/수집 계획
- `docker/`: 도커 관련
  - `airflow/` (Airflow 전용 이미지 빌드)
  - `airflow-compose.yml` (Airflow + Postgres)
- `Dockerfile`, `docker-compose.yml`: 수집기 전용 이미지/컴포즈

정리 원칙
- 실행/코드 관련 외의 산출물(html/csv/snapshots)은 `output/quarantine/`로 격리
- 과거 단발성/개별 스크립트는 `legacy_crawlers/`로 이동, 원래 경로는 `legacy_crawlers/manifest.txt`에 기록



