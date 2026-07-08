# 신규 사업자 온보딩 SOP

40+ 사업자로 확장하기 위한 표준 절차. 목표는 사업자 추가가 "코드 작성"이 아니라
"선언 추가 + (필요 시) 수집기 1개"로 끝나게 하는 것이다.

## 1. 분류 (어떤 수집 방식인가)
1. 브라우저 DevTools(Network)로 **내부 JSON/Ajax API를 먼저 탐색**한다.
   - 발견 시 → `collector_type: api` (ApiFetcher). 가장 견고하고 유지보수 쉬움.
2. API가 없고 구조가 **단순 표/리스트(정적 HTML)** → `collector_type: generic`.
   - 코드 없이 `policy.json`(셀렉터 매핑)만 작성 → `GenericCollector` 사용.
3. **동적 렌더링/모달/강한 안티봇** → `collector_type: playwright` + 전용 `.py` 수집기.

## 2. 카탈로그 등록 (config/vendors.yaml)
```yaml
  myvendor:
    display_name: "마이모바일"
    group: mvno            # mvno | mno
    network: "LTE/5G"
    collector_type: generic
    enabled: true
    anti_bot_level: low
    schedule: "0 */6 * * *"
    expected_min_records: 1
    owner: yourname
    base_urls: ["https://..."]
    policy_file: "config/policies/myvendor.json"  # generic인 경우
```
- `dim_operator.csv`에 사업자 행을 추가한다(거버넌스 검증 통과 필수).

## 3. 구현
- **generic**: `policy.json`에 `NAME/PRICE/DATA/VOICE/SMS/PLAN_ID/NETWORK` 셀렉터 선언.
- **api/playwright**: `collectors/vendors/<key>.py`에 `BaseCollector` 상속 구현 후
  `registry.register("<key>", ...)`. 이통3사는 `_mno_template.py`를 복사해 시작.
- 단위/금액/무제한 파싱은 **반드시 `schemas/units.py`** 의 normalizer 사용(재구현 금지).
- 약정/결합/선택약정 다단계 가격은 `PlanRecord.price_components`로 표현.

## 4. 품질 게이트 (PR 필수)
- `tests/fixtures/<key>/`에 대표 HTML/JSON 스냅샷 + 골든 기대값을 커밋한다.
- 파서 회귀 테스트를 추가한다(예: `tests/test_<key>_parser.py`).
- `python -m pipeline.catalog_check` 통과(카탈로그 ↔ 레지스트리 정합성).
- `pytest -q` 전체 통과.

## 5. 검증
- `python -m pipeline.run_collectors <key> --fail-on-empty`로 0건/무음 실패 차단 확인.
- `output/raw/<key>/<ts>/`의 records.jsonl·metadata.json 확인.
- transform → SCD2 적재까지 동적 통합 테스트로 확인.
