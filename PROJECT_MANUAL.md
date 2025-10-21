# MVNO 데이터 수집 프로젝트 사용설명서

## 1. 프로젝트 개요
MVNO(알뜰폰) 사업자별 요금제 정보를 자동으로 수집하고 정제하여 데이터 마트에 적재하는 파이프라인입니다. 본 설명서는 저장소 구조, 실행 방법, 설정 정책, 확장 절차를 안내합니다.

## 2. 디렉터리 구조 요약
- `collectors/`: 공통 크롤러 프레임워크, 정책, 벤더별 구현을 포함합니다.
- `pipeline/`: 수집기 실행 CLI와 알림 유틸리티가 위치합니다.
- `etl/`: 수집된 JSONL을 표준 스키마로 변환하고 DB에 적재하는 코드가 있습니다.
- `orchestration/`: Airflow 등 스케줄러에서 사용할 DAG/플로우 스켈레톤을 제공합니다.
- `output/`: 크롤링 실행 결과(JSONL, 메타데이터, 원본 보관)가 저장되는 기본 디렉터리입니다.
- `logs/`: 실행 요약, ETL 통계 등 로그 파일을 저장합니다.

## 3. 크롤러 프레임워크 사용법
### 3.1 CollectorConfig와 BaseCollector
모든 수집기는 `collectors/base.py`의 `BaseCollector`를 상속하여 구현합니다. `CollectorConfig`로 이름, 출력 경로, 동시성, 필드 정책 등을 주입하고 `run()` 메서드가 전체 수명주기를 관리합니다.

주요 오버라이드 대상 메서드:
1. `setup()`: 사전 준비 로직(세션 생성 등)
2. `fetch_entries()`: 대상 사이트에서 원본 엔트리를 가져옵니다.
3. `parse_entries()`: `PlanRecord` 목록으로 변환합니다.
4. `teardown()`: 후처리 및 리소스 정리

### 3.2 OutputManager
`collectors/utils/output.py`의 `OutputManager`는 실행별 출력 디렉터리를 생성하고, 표준 JSONL(`records.jsonl`)과 메타데이터(`metadata.json`)를 저장합니다. 원본 HTML/JSON은 `save_raw_payload()`로 보존할 수 있습니다.

### 3.3 Playwright 유틸리티
브라우저 제어가 필요한 경우 `collectors/utils/playwright.py`의 `browser_context()`와 `with_page()`를 사용하여 Playwright 세션을 안전하게 열고 닫습니다.

## 4. 필드 정책(컬럼-셀렉터 매핑)
HTML 클래스가 벤더마다 다른 문제를 해결하기 위해 `collectors/policy.py`에 `FieldPolicy` 모델이 정의되어 있습니다. 정책 JSON 파일을 작성해 컬럼별 CSS 셀렉터, 속성, 설명을 선언하면 런타임에 로드되어 `CollectorConfig.field_policy`로 주입됩니다.

예시 JSON 구조:
```json
{
  "example": {
    "PRICE": [
      {"selector": ".price", "reason": "기본 요금"},
      {"selector": ".monthly-price span", "attribute": "textContent"}
    ]
  }
}
```
정책 파일은 CLI 실행 시 `--policy-file path/to/policies.json` 옵션으로 전달합니다.

## 5. 표준 데이터 스키마
`schemas/plan_record.py`의 `PlanRecord`는 벤더, 요금제 ID, 상품명, 월 요금, 데이터 제공량 등 필수 필드를 정의하고 유효성 검증을 수행합니다. 모든 수집기는 `PlanRecord` 인스턴스를 반환해야 하며, `to_dict()`로 JSON 직렬화를 지원합니다.

## 6. 수집기 실행 오케스트레이션
### 6.1 CLI 사용법
`pipeline/run_collectors.py`는 다음과 같은 옵션을 제공합니다:
- `--collectors`: 실행할 수집기 이름 목록(콤마 구분). 지정하지 않으면 모든 등록된 수집기를 실행합니다.
- `--output-dir`: 출력 기본 디렉터리(기본값 `output/raw`).
- `--concurrency`: 동시에 실행할 수집기 수 제한.
- `--metadata`: 실행 전역 메타데이터(JSON 문자열).
- `--summary`: 실행 요약 JSON 파일 경로.
- `--policy-file`: 컬럼-셀렉터 정책 JSON 파일 경로.

예시:
```bash
python -m pipeline.run_collectors --collectors example --policy-file config/policies.json --summary logs/example_run.json
```

### 6.2 실행 결과
각 수집기 실행 후 `output/raw/<collector>/<timestamp>/` 경로에 `records.jsonl`, `metadata.json`, `raw/` 디렉터리가 생성됩니다. 메타데이터에는 실행 시간, 처리 건수, 적용된 필드 정책 요약이 포함됩니다.

## 7. ETL 파이프라인
### 7.1 변환(`etl/transform.py`)
- `TransformConfig`로 참조 데이터 경로를 지정합니다.
- `transform()` 함수는 JSONL을 로드하여 단위 변환(`normalize_units`), 벤더 매핑(`apply_reference_mappings`), 품질 검증(`quarantine_invalid`)을 수행하고 유효/무효 데이터프레임을 반환합니다.

### 7.2 적재(`etl/load.py`)
- `PlanLoader`는 SQLAlchemy 엔진을 통해 스테이징 테이블에 데이터를 적재(`load_to_staging`)하고, 마트 테이블에 UPSERT(`upsert_to_mart`)를 수행합니다.
- `LoadConfig`로 DSN, 스키마/테이블명을 설정합니다.

## 8. 스케줄링 및 모니터링
`orchestration/airflow_dag.py`는 일일 배치를 가정한 Airflow DAG 예시를 제공합니다. `run_collectors_task`가 추출 단계를 담당하고, 추후 변환/적재 태스크에 ETL 모듈을 연결할 수 있도록 스켈레톤을 제공합니다. Slack 등 외부 알림이 필요하면 `pipeline/notifier.py`의 `WebhookNotifier`를 사용해 실행 결과를 전송합니다.

## 9. 신규 벤더 추가 절차
1. `collectors/vendors/<vendor>.py` 파일을 생성하고 `BaseCollector`를 상속합니다.
2. 필요한 셀렉터 정책을 정책 JSON에 추가합니다.
3. `registry.register("vendor", VendorCollector)` 호출로 레지스트리에 등록합니다.
4. 로컬 실행 후 `output/raw/<vendor>/` 산출물을 확인합니다.
5. ETL 변환을 통해 스키마에 적합한지 검증하고, 필요한 매핑 테이블을 업데이트합니다.

## 10. 문제 해결 및 팁
- **Playwright 설치**: 브라우저 자동화를 사용하려면 `playwright install` 명령으로 필요한 브라우저를 설치하세요.
- **로그 확인**: 실패 시 `logs/` 디렉터리의 실행 요약과 `metadata.json`의 에러 메시지를 확인합니다.
- **정책 디버깅**: `metadata.json`의 `field_policy` 섹션에서 사용된 셀렉터 목록을 확인하고, 필요 시 원본 페이로드(`raw/`)를 분석합니다.
- **품질 검증**: `etl/transform.py`가 분리한 quarantine 파일(`output/quarantine/`)을 주기적으로 검토하여 스키마 불일치 문제를 해결합니다.

## 11. 문의
추가 기능이나 개선이 필요하면 프로젝트 리드에게 문의하거나 Issue를 등록해 주세요.
