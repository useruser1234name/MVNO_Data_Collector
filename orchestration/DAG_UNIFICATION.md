## MVNO Airflow DAG 통일성 정리

본 문서는 벤더별 DAG 구축 이후, 수집-정제-저장 파이프라인이 어떻게 통일(표준화)되었는지와 운영 방법을 정리합니다.

### 대상 벤더 및 DAG
- uplusumobile: `orchestration/uplusumobile_dag.py` → DAG ID `uplusumobile_pipeline`
- amobile: `orchestration/amobile_dag.py` → DAG ID `amobile_pipeline`
- egmobile: `orchestration/egmobile_dag.py` → DAG ID `egmobile_pipeline`
- eyagi: `orchestration/eyagi_dag.py` → DAG ID `eyagi_pipeline`
- insmobile: `orchestration/insmobile_dag.py` → DAG ID `insmobile_pipeline`

모든 DAG는 동일한 3단계 태스크를 사용합니다:
- extract: 크롤링/수집 실행
- transform: 표준 스키마 정제 및 검증
- load: 데이터 마트 UPSERT

### 공통 헬퍼(표준화의 핵심)
- 위치: `orchestration/common.py`
- 기능:
  - 표준 경로/환경변수
    - `MVNO_OUTPUT_DIR`(기본 `output/raw`)
    - `MVNO_REFERENCE_DIR`(기본 `etl/reference`)
    - `MVNO_DB_DSN`(벤더별 `VENDOR_DB_DSN`로 폴백 허용)
  - 표준 XCom 키: `records_path`, `valid_path`, `invalid_path`
  - 태스크 팩토리:
    - `make_extract_task(vendor)`: 수집기 실행 후 최신 `records.jsonl` 경로를 XCom(`records_path`)에 저장
    - `make_transform_task()`: 유효/무효 분리 후 `valid.jsonl`/`invalid.jsonl` 생성, XCom(`valid_path`, `invalid_path`) 저장
    - `make_load_task(vendor)`: `valid.jsonl`을 스테이징 적재 후 마트 UPSERT

### 저장 형식(디렉터리/파일 통일 규칙)
- 실행 산출물: `<MVNO_OUTPUT_DIR>/<vendor>/<timestamp>/`
  - `records.jsonl`: 표준 `PlanRecord` 직렬화 결과
  - `metadata.json`: 실행 메타데이터(수집기 공통)
  - `transformed/valid.jsonl`: 정제/검증 후 유효 레코드
  - `transformed/invalid.jsonl`: 스키마 불일치 등 무효 레코드(있을 때만 생성)

### 표준 XCom 키
- `records_path`: extract → transform 전달(최신 `records.jsonl`)
- `valid_path`: transform → load 전달(`transformed/valid.jsonl`)
- `invalid_path`: 선택(존재 시), 무효 레코드 파일 경로

### 표준 환경변수/설정
- 공용 경로
  - `MVNO_OUTPUT_DIR=output/raw`
  - `MVNO_REFERENCE_DIR=etl/reference`
- 데이터베이스
  - `MVNO_DB_DSN=postgresql+psycopg2://user:pass@host:5432/dbname`
  - 필요 시 벤더별 폴백: `UPLUS_DB_DSN`, `AMOBILE_DB_DSN`, `EGMOBILE_DB_DSN`, `EYAGI_DB_DSN`, `INSMOBILE_DB_DSN`
- 동시성(수집 단): `MVNO_CONCURRENCY`(기본 1)

### 정제/적재 표준
- 변환 모듈: `etl/transform.py`
  - 단위 정규화, 벤더 매핑(옵션), 유효성 검증(quarantine) 수행
- 적재 모듈: `etl/load.py`
  - 스테이징 테이블: `stg_mvno_plans_raw`
  - 마트 테이블: `mart_mvno_plans`
  - UPSERT 키: `["vendor", "plan_id"]`(벤더별 DAG 모두 동일)

### 스케줄/신뢰성
- 스케줄: 일 1회(`timedelta(days=1)`), `catchup=False`
- 재시도: 기본 1회(10분 딜레이)
- 실패 시: DB DSN 미설정이면 Load 단계는 안전 스킵(경고 로그)

### 신규 벤더 추가 가이드
1. 수집기 구현: `collectors/vendors/<vendor>.py`에서 `BaseCollector` 상속, `PlanRecord` 반환
2. 레지스트리 등록: `registry.register("<vendor>", VendorCollector, ...)`
3. DAG 생성: `orchestration/<vendor>_dag.py`
   - 태스크는 모두 공통 헬퍼 사용:
     - `extract = PythonOperator(..., python_callable=make_extract_task("<vendor>"))`
     - `transform = PythonOperator(..., python_callable=make_transform_task())`
     - `load = PythonOperator(..., python_callable=make_load_task("<vendor>"))`
4. 운영 환경변수 설정: `MVNO_OUTPUT_DIR`, `MVNO_REFERENCE_DIR`, `MVNO_DB_DSN`

### 실행/운영 팁
- 로컬 검증(개별 수집기):
  - `python -m pipeline.run_collectors <vendor> --output-dir output/raw --concurrency 1`
- Airflow 배포:
  - 위 DAG 파일들을 Airflow `dags/`에 배치
  - Airflow Variables/Connections 대신 환경변수 사용 시 워커에 동일하게 설정
- 품질 관리:
  - `transformed/invalid.jsonl` 점검으로 스키마 불일치 추세 파악
  - 필요 시 `etl/reference`의 매핑 테이블 업데이트

### 통일성 효과 요약
- 태스크: 모든 벤더 DAG가 동일한 3단계(extract→transform→load)로 정렬
- 경로/파일: 동일 디렉터리 규칙과 파일명(`records.jsonl`, `valid.jsonl`, `invalid.jsonl`)
- XCom: 키 표준화(`records_path`, `valid_path`, `invalid_path`)
- 환경변수: 공용 `MVNO_*`로 간소화, 벤더별 DSN은 폴백만 허용
- 적재 정책: 공용 UPSERT 키(`vendor`, `plan_id`)와 공용 마트 테이블로 통합


