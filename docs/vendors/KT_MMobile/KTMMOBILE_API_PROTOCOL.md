## KT M모바일 수집 API 프로토콜(내부 표준)

이 문서는 KT M모바일 요금제 수집기의 입력/출력 및 운영용 엔드포인트 규격을 정의합니다. 실제 대상 웹페이지는 [요금제 소개](https://www.ktmmobile.com/rate/rateList.do)이며, 본 문서의 API는 당사 파이프라인(수집기 → ETL/저장소) 사이 인터페이스를 의미합니다.

### 1) 용어
- Collector: Playwright 기반 모달 수집기
- Record: 정규화된 요금제 레코드(`schemas.plan_record.PlanRecord`)
- Run: 단일 수집 실행 단위(메타/통계 포함)

### 2) 데이터 모델
- `PlanRecord` 핵심 필드(요약):
  - `vendor: str` — 예: "KT M mobile"
  - `plan_id: str` — 사이트 코드 또는 해시(이름+요금 등)로 생성
  - `name: str`
  - `monthly_fee: float` — 원화(숫자)
  - `data_allowance_mb: int` — MB 단위(GB→MB 변환)
  - `voice_minutes: Optional[int]`
  - `sms_count: Optional[int]`
  - `network_type: Optional[str]` — LTE/5G 등
  - `promotion: Optional[str]`
  - `effective_date: Optional[date]`
  - `metadata: dict` — 부가 혜택, 제휴조건, 원본 텍스트 등

정규화 규칙: 금액·데이터·분·건은 수치로 통일, "무제한"은 `None` 또는 충분히 큰 값 대신 `metadata.unlimited = true`로 표현.

### 3) 엔드포인트(수집기 → 파이프라인)

#### POST /api/v1/vendors/ktmmobile/plans
- **설명**: 신규 수집 결과 업서트(upsert)
- **헤더**:
  - `Content-Type: application/json; charset=utf-8`
  - `X-Collector-Version: <semver>`
  - `X-Run-Id: <uuid>`
- **요청 본문(JSON)**:
```json
{
  "run": {
    "run_id": "f1e3a0b4-...",
    "source_url": "https://www.ktmmobile.com/rate/rateList.do",
    "collected_at": "2025-11-02T12:34:56+09:00",
    "exec_options": { "headless": false, "slowmo": 100 }
  },
  "records": [
    {
      "vendor": "KT M mobile",
      "plan_id": "ktmm-<hashed>",
      "name": "모두다 맘껏 11GB+",
      "monthly_fee": 33000,
      "data_allowance_mb": 11264,
      "voice_minutes": null,
      "sms_count": null,
      "network_type": "LTE",
      "promotion": "11월 한정 할인",
      "metadata": {"raw_html_id": "modal_123", "benefits": ["데이터쉐어링 최대 2회선"]}
    }
  ],
  "artifacts": {
    "modal_html_paths": ["ktmm_out/html/KTMM_20251102/modal_123.html"],
    "screenshots": ["ktmm_out/modals/modal_123.png"]
  }
}
```
- **응답**: `200 OK`
```json
{
  "run_id": "f1e3a0b4-...",
  "received": 120,
  "upserted": 118,
  "skipped": 2,
  "warnings": []
}
```

#### GET /api/v1/vendors/ktmmobile/runs/{run_id}
- **설명**: 실행 메타/통계 조회
- **응답**: `200 OK`
```json
{
  "run_id": "f1e3a0b4-...",
  "started_at": "2025-11-02T12:33:00+09:00",
  "finished_at": "2025-11-02T12:36:10+09:00",
  "stats": {"plans": 120, "tabs": 2, "categories": 10, "modals": 120}
}
```

#### GET /api/v1/vendors/ktmmobile/healthz
- **설명**: Collector/파이프라인 연동 상태
- **응답**: `200 OK` `{ "ok": true }`

### 4) 수집기 실행 파라미터(표준화)
- `tabs.main[]`: 처리할 메인 탭 이름 리스트 (예: ["유심/eSIM 요금제"]) 
- `tabs.sub_map{main:[sub...]}`: 메인 ↔ 서브 매핑 (예: {"유심/eSIM 요금제":["LTE 요금제","5G 요금제"]})
- `timeouts`: `{ appear, open, close }` (ms)
- `throttle_ms`: 카드 간 지연(난수 범위 가능)
- `max_per_tab`: 디버그 시 처리 카드 상한
- `block_resources`: ["image","font"] 등

### 5) CSV 출력 규격(오프라인 교환용)
- 파일: `ktmm_out/ktmmobile_modal_data.csv`
- 컬럼: `vendor,plan_id,name,monthly_fee,data_allowance_mb,voice_minutes,sms_count,network_type,promotion,effective_date,metadata_json,run_id,source_url`

### 6) 사이트 백엔드 API(발견 시 기록)
Playwright MCP로 네트워크를 후킹하여 탭/아코디언/모달 상호작용 시점을 기준으로 요청을 캡처했습니다. 확인된 엔드포인트는 다음과 같습니다.

1) 초기 로딩
- `POST /rate/getCtgXmlAllListAjax.do` (200 OK)
  - 용도: 카테고리/초기 설정 조회
- `POST /getPopupListAjax.do` (200 OK)
  - 용도: 팝업 정보(수집과 직접 무관)

2) 아코디언(카테고리) 확장 시
- `POST /rate/rateContentAjax.do` (200 OK)
  - 용도: 해당 카테고리의 카드(요금제) 컨텐츠 로드
  - 파라미터: DOM의 `data-rate-adsvc-ctg-cd` 등 카테고리 식별값 전달되는 것으로 추정
  - 응답: 카드 리스트용 HTML 조각(이미지 등 추가 리소스는 GET)

3) 모달
- 모달 오픈 시 별도 상세 API 호출은 추가로 관찰되지 않음(카드 로드 시점 DOM을 모달로 노출하는 구조)
  - 결과적으로 모달 필드는 DOM 파싱으로 충분

테이블 기록 원칙(필요 시 확장):
- 전체 URL, 요청/응답 헤더, 샘플 요청/응답, 파라미터 의미, 변경 가능성(버전/AB 여부)

### 6.1) 탭/아코디언/모달 수집 플로우(실측)
- 메인 탭 선택(예: 유심/eSIM) → 서브 탭 선택(LTE/5G)
- 각 카테고리 아코디언 클릭 → `rateContentAjax.do` 완료 대기 → 카드 DOM 렌더 확인
- 카드 내부 버튼 클릭 → 모달 등장(`dialog`) → 필드 파싱 → 닫기
- 카드/카테고리 간 200~400ms 지연

### 6.2) DOM → 필드 매핑(요약)
- name: 모달 헤더 `h2`
- monthly_fee: "월 기본료(VAT 포함)" 금액(정규식 파싱)
- promotion: "프로모션 요금" 및 혜택·배지 텍스트 `|` 결합
- data_allowance_mb: 데이터 제공량(TB/GB/MB → MB 환산, 무제한/속도문구는 `metadata`에 병기)
- voice_minutes: "기본제공" → None, "n분" → 정수
- sms_count: "기본제공" → None, "n건" → 정수
- network_type: 서브 탭/타이틀에서 LTE/5G 추론
- metadata: 혜택/유의사항/추가서비스 문구, 카테고리 코드, 서브 탭명 등

정규식 예시:
- 금액: `(\d[\d,]*)\s*원`
- 데이터: `(\d+(?:\.\d+)?)\s*(TB|GB|MB)`
- 음성: `(\d+)\s*분`
- 문자: `(\d+)\s*(건|SMS)`

### 7) 보안/컴플라이언스
- 로그인/본인인증 영역은 수집하지 않음
- 마스킹된 개인정보/식별자 해제 시도 금지
- 로봇차단 우회 행위 금지, 합리적 요청 간격 유지

### 8) 오류 코드/재시도 정책(권장)
- 4xx: 1회 재시도(지연 후), 지속 시 스킵 + 경고 기록
- 5xx/네트워크 오류: 지수 백오프(최대 3회)
- 파싱 오류: 원본 저장 후 건별 스킵, 전체 중단 금지

### 9) 참조
- 운영 페이지: [https://www.ktmmobile.com/rate/rateList.do](https://www.ktmmobile.com/rate/rateList.do)
- 로깅 전략: `KT_MMobile/PLAYWRIGHT_LOGGING_STRATEGY.md`



