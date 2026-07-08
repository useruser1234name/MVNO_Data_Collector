# 국내 알뜰폰(MVNO) 업체 리스트업 및 요금 크롤링 획득 계획서

## 1. 목적과 범위

이 문서는 국내 알뜰폰(MVNO) 사업자 목록을 지속적으로 확보하고, 사업자별 요금제 정보를 표준 스키마로 수집하기 위한 실행 계획을 정의한다. 목표는 다음과 같다.

1. **공식 사업자 원장 확보**: 과학기술정보통신부 공공데이터를 기준 원장으로 삼아 국내 알뜰폰 사업자 목록을 정기 갱신한다.
2. **크롤링 대상 우선순위화**: 알뜰폰허브 입점사, 현재 저장소에 이미 스크립트 또는 원시 파일이 존재하는 사업자, 트래픽/브랜드 인지도가 높은 사업자를 우선 수집한다.
3. **요금제 데이터 표준화**: 사업자별 HTML/API 구조 차이를 `PlanRecord` 스키마와 필드 정책으로 흡수한다.
4. **운영 가능한 파이프라인 구축**: 수집, 검증, 격리, 적재, 모니터링까지 반복 가능한 배치 프로세스로 만든다.

## 2. 공식 출처와 갱신 기준

| 구분 | 출처 | 현재 확인 내용 | 활용 방식 |
| --- | --- | --- | --- |
| 기준 사업자 원장 | 공공데이터포털 `과학기술정보통신부_알뜰폰 사업자 현황` | 2026-03-25 수정, CSV, 전체 60행, 연간 업데이트, 차기 등록 예정일 2027-03-25 | `vendor_registry`의 1차 원장. 사업자명, 전화번호, 사업자등록번호를 원천 식별자로 사용 |
| 요금제 비교/가입 포털 | KAIT 알뜰폰 허브사이트 운영 안내 | MVNO 총 22개 참여사업자 및 맞춤 요금제 정보 제공 | 초기 크롤링 우선순위와 허브 통합 수집 후보로 사용 |
| 개별 사업자 공식 홈페이지 | 각 MVNO 브랜드 웹사이트 | 요금, 프로모션, 상세 약관, 가입 조건이 가장 최신일 가능성이 높음 | 최종 가격·프로모션 정합성 검증 및 상세 필드 수집 |
| 저장소 기존 산출물 | `*.txt`, 벤더별 scraper/collector | 일부 사업자 대상의 URL/HTML/스크래퍼 자산 존재 | 재사용 가능한 수집 로직과 누락 컬럼 분석에 활용 |

> 주의: 공공데이터 원장은 사업자 단위이고, 실제 소비자가 인지하는 브랜드명은 별도일 수 있다. 따라서 `사업자명`, `브랜드명`, `도메인`, `망(SKT/KT/LGU+)`, `수집상태`를 분리해 관리한다.

## 3. 업체 리스트업 전략

### 3.1 전수 원장

- **전수 기준**: 공공데이터포털의 `과학기술정보통신부_알뜰폰 사업자 현황` 최신 CSV를 다운로드해 `vendor_registry.csv`를 생성한다.
- **현 기준 행 수**: 2026-03-25 공개본 기준 전체 60개 사업자.
- **갱신 주기**: 공식 데이터의 업데이트 주기가 연간이므로 월 1회 변경 확인, 매년 3월 말 이후 필수 재수집.
- **키 설계**:
  - `operator_name`: 공식 사업자명
  - `business_registration_number`: 사업자등록번호
  - `brand_name`: 소비자 노출 브랜드명
  - `network`: SKT/KT/LGU+/복수망
  - `source_url`: 공식 홈페이지 또는 허브 상세 URL
  - `crawl_status`: `planned`, `implemented`, `blocked`, `deprecated`
  - `priority`: `P0`, `P1`, `P2`, `P3`

### 3.2 KAIT 알뜰폰허브 참여사업자 22개사

KAIT 안내 페이지 기준 알뜰폰허브 참여사업자는 다음 22개사다. 이 그룹은 허브 요금제 비교 화면 또는 사업자별 공식 페이지 수집 우선순위를 높게 둔다.

| 우선순위 | 사업자/브랜드 | 저장소 대응 현황 | 수집 전략 |
| --- | --- | --- | --- |
| P0 | KTM모바일 | `KT_MMobile/`, `KT엠모바일.txt` 존재 | 기존 Playwright/모달 수집기 정리 후 `BaseCollector` 포팅 |
| P0 | 미디어로그 / U+유모바일 | `LG_UMobile/`, `collectors/vendors/uplusumobile.py`, `유모바일.txt` 존재 | 기존 `uplusumobile` collector 고도화 및 상세 페이지 필드 보강 |
| P0 | SK텔링크 / SK세븐모바일 | `SK_SevenMobile/`, `sk7.txt` 존재 | URL 수집 + 상세 크롤러를 표준 collector로 래핑 |
| P0 | KB국민은행 / 리브모바일 | `리브모바일.txt` 존재 | 공식 웹/앱 API 탐색 후 우선 구현 |
| P1 | LG헬로비전 / 헬로모바일 | 미구현 | 공식 요금제 목록 API/HTML 분석 |
| P1 | 에넥스텔레콤 / A모바일 | `Amobile/` 존재 | 기존 스크립트 collector 포팅 |
| P1 | 아이즈비전 / 아이즈모바일 | 미구현 | 목록 페이지 정적/동적 여부 확인 |
| P1 | 스마텔 | 미구현 | 요금제 카드 DOM 정책 작성 |
| P1 | 큰사람커넥트 / 이야기모바일 | `Eyagi_Mobile/` 존재 | 기존 스크립트 collector 포팅 |
| P1 | 한국케이블텔레콤 / 티플러스 | 미구현 | eSIM/요금제 API 여부 확인 |
| P2 | 위너스텔 | 미구현 | 허브 또는 공식 페이지 기반 수집 |
| P2 | 유니컴즈 / 모빙 | 미구현 | 공식 API 탐색 |
| P2 | 프리텔레콤 / FreeT | 미구현 | 공식 요금제 페이지 수집 |
| P2 | 인스코비 | 미구현 | 브랜드/도메인 매핑 선행 |
| P2 | KT스카이라이프 | 미구현 | 모바일 요금제 섹션 수집 |
| P2 | 코드모바일 | 미구현 | 브랜드 매핑 및 상세 URL 확보 |
| P2 | 고고팩토리 | 미구현 | 허브 입점 상품 우선 수집 |
| P2 | 찬스모바일 | `Chancemobile/` 존재 | 기존 스크립트 collector 포팅 |
| P2 | 마블프로듀스 | `Marveling모바일.txt` 존재 | 브랜드/도메인 확인 후 구현 |
| P2 | 에이프러스 | 미구현 | 공식 페이지 확인 |
| P2 | 씨케이커뮤스트리 | 미구현 | 공식 페이지 확인 |
| P2 | 인스코리아 | 미구현 | 공식 페이지 확인 |

### 3.3 저장소에서 이미 식별된 추가 후보

현재 저장소에는 알뜰폰허브 22개사 외에도 다음 후보 파일/스크립트가 있다. 이들은 과학기술정보통신부 원장과 대조해 사업자명·브랜드명을 확정한 뒤 `vendor_registry`에 반영한다.

| 후보 브랜드/사업자 | 저장소 자산 | 처리 계획 |
| --- | --- | --- |
| EG모바일 | `EGMobile/EGMobile_scrape.py` | 스크립트 실행 가능성 확인 후 표준 collector 변환 |
| 인스모바일 | `Insmobile/insmobile_scrape.py` | 원장 대조 및 필드 추출 정책 작성 |
| 슈가모바일 | `Sugarmobile/` | URL 수집기와 HTML 수집기 역할 분리 |
| 시월모바일 | `Siwol_Mobile/siwol_scraper.py` | Playwright 필요 여부 확인 |
| 우리원모바일 | `Wooriwonmobile/Wooriwonmobile_scrape.py` | 은행계/제휴 브랜드 여부 확인 |
| 쉐이크모바일 | `ShakeMoblie/ShakeMoblie_Scrape.py` | 오탈자 디렉터리명 정리 검토 |
| 모나모바일 | `모나모바일.txt` | 도메인 및 공식 사업자명 확인 |
| SMT모바일 | `SMT모바일.txt` | 도메인 및 공식 사업자명 확인 |
| 스피츠모바일 | `스피츠모바일.txt` | 도메인 및 공식 사업자명 확인 |
| 에르엘모바일 | `에르엘모바일.txt` | 도메인 및 공식 사업자명 확인 |

## 4. 요금 크롤링 획득 설계

### 4.1 수집 우선순위

1. **P0: 기존 코드/파일이 있고 수요가 큰 사업자**
   - KT M모바일, U+유모바일, SK세븐모바일, 리브모바일
2. **P1: 허브 참여사 중 주요 브랜드**
   - 헬로모바일, A모바일, 아이즈모바일, 스마텔, 이야기모바일, 티플러스
3. **P2: 허브 참여사 잔여 및 저장소 추가 후보**
   - 찬스모바일, 프리티, 모빙, 스카이라이프 등
4. **P3: 공공데이터 원장에는 있으나 소비자 요금제 페이지 확인이 필요한 사업자**
   - B2B/IoT 전용, 휴면, 제휴 전용 가능성이 있는 사업자는 수집 가능성 검증 후 진행

### 4.2 수집 방식 분류

| 유형 | 조건 | 구현 방식 | 예시 |
| --- | --- | --- | --- |
| 공식 JSON/API | 네트워크 탭에서 요금제 JSON 응답 확인 | `requests/httpx` 기반 collector | 정적 API가 있는 브랜드 |
| 정적 HTML | 서버 렌더링 카드/테이블 | `BeautifulSoup` + CSS selector 정책 | 단순 요금제 목록 페이지 |
| 동적 HTML | JS 렌더링, 무한스크롤, 모달 상세 | Playwright utility 사용 | KT M모바일 모달, 일부 React/Vue 사이트 |
| 허브 통합 | 알뜰폰허브 검색 결과로 여러 사업자 상품 노출 | 허브 검색 조건별 수집 후 공식 페이지로 검증 | 허브 입점 22개사 |
| 수동 보강 | robots/인증/캡차/앱 전용 | URL·필드만 원장화하고 `blocked` 처리 | 앱 전용 가입 상품 |

### 4.3 표준 필드

수집 결과는 최소한 다음 필드를 채운다.

| 필드 | 설명 | 필수 여부 |
| --- | --- | --- |
| `vendor` | 표준 사업자/브랜드 키 | 필수 |
| `plan_id` | 사업자 내부 상품 ID 또는 URL 해시 | 필수 |
| `name` | 요금제명 | 필수 |
| `monthly_fee` | 월 기본료 또는 프로모션 적용 월 납부액 | 필수 |
| `data_allowance_mb` | 기본 데이터 제공량 MB 환산값 | 필수 |
| `voice_minutes` | 음성 제공량. 무제한은 `None` + metadata flag | 선택 |
| `sms_count` | 문자 제공량. 무제한은 `None` + metadata flag | 선택 |
| `network_type` | LTE/5G 및 제공망 | 선택 |
| `promotion` | 프로모션 문구, 할인 기간, 사은품 | 선택 |
| `metadata.detail_url` | 상세 페이지 URL | 필수 권장 |
| `metadata.crawled_source` | `official`, `mvnohub`, `manual_seed` 등 | 필수 권장 |

### 4.4 가격/프로모션 처리 원칙

- `monthly_fee`: 현재 페이지에서 즉시 노출되는 월 요금을 저장한다.
- `metadata.original_fee`: 할인 전 정상가가 있으면 별도 저장한다.
- `metadata.promotion_months`: “7개월 이후”, “12개월 할인” 등 기간형 할인은 정규식으로 추출한다.
- `metadata.after_promotion_fee`: 할인 종료 후 요금이 있으면 별도 저장한다.
- 동일 요금제가 허브와 공식 홈페이지에 동시에 존재하면 공식 홈페이지 값을 우선하고, 허브 값은 비교 검증용으로 유지한다.

## 5. 구현 로드맵

### Phase 1. 원장 구축

- 공공데이터 CSV 다운로드 스크립트 작성
- `etl/reference/vendor_registry.csv` 생성
- 저장소 기존 파일명/디렉터리 기반 후보와 공식 사업자명 매핑
- `crawl_status`, `priority`, `source_url` 컬럼 부여

### Phase 2. P0 collector 표준화

- 기존 `KT_MMobile`, `LG_UMobile`, `SK_SevenMobile` 스크립트를 `collectors/vendors/` 구조로 포팅
- 리브모바일 수집 가능 URL/API 탐색
- 모든 P0 collector에 `PlanRecord` 변환과 raw payload 저장 적용

### Phase 3. 허브/공식 페이지 병행 수집

- 알뜰폰허브 요금제 검색 조건을 정의한다.
  - 망: SKT, KT, LGU+
  - 통신규격: LTE, 5G
  - 유심/eSIM 여부
  - 데이터 구간: 0~1GB, 1~7GB, 7~15GB, 15GB+, 무제한
- 허브 상품에서 사업자명, 요금제명, 가격, 할인 기간, 상세 링크를 수집한다.
- 공식 홈페이지 collector와 결과를 대조해 가격 차이를 `quality_flags`로 남긴다.

### Phase 4. 품질 검증/적재

- 필수 필드 누락, 음수 가격, 중복 `vendor+plan_id`, 비정상 단위 변환을 quarantine 처리
- 변환 결과를 staging table에 적재하고 mart table에 upsert
- 매 실행마다 레코드 수, 실패 URL, 신규/삭제/가격변동 건수를 summary JSON으로 저장

### Phase 5. 운영 자동화

- 일 1회 P0/P1, 주 1회 P2/P3 실행
- 가격 변동이 감지되면 summary와 diff report를 생성
- selector 실패율이 일정 기준을 넘으면 알림 발송
- robots.txt, 이용약관, 과도한 요청 방지 정책을 수집기별 metadata에 기록

## 6. 산출물

| 산출물 | 경로 제안 | 설명 |
| --- | --- | --- |
| 사업자 원장 | `etl/reference/vendor_registry.csv` | 공식 사업자명, 브랜드명, 도메인, 망, 우선순위, 상태 |
| 필드 정책 | `config/field_policies/*.json` | 사업자별 CSS selector/API field 매핑 |
| raw 수집물 | `output/raw/<collector>/<timestamp>/` | 원본 HTML/JSON, records.jsonl, metadata.json |
| 품질 리포트 | `logs/crawl_quality_<date>.json` | 누락 필드, 실패 URL, 가격 변동 |
| 구현 현황표 | `docs/MVNO_VENDOR_CRAWLING_PLAN.md` | 본 문서. 업체 목록과 실행 계획 |

## 7. 리스크와 대응

| 리스크 | 영향 | 대응 |
| --- | --- | --- |
| 사업자/브랜드명 불일치 | 중복 또는 누락 수집 | 공식 사업자명과 브랜드명을 별도 컬럼으로 관리 |
| 프로모션 가격 수시 변경 | 가격 비교 오류 | 정상가/할인가/할인기간을 분리 저장하고 수집 시각 기록 |
| 동적 페이지/캡차/앱 전용 | 자동 수집 실패 | Playwright 적용, 불가 시 `blocked` 상태와 수동 검증 플래그 |
| 과도한 요청 차단 | IP 차단/서비스 영향 | rate limit, retry backoff, 캐시, 야간 배치 적용 |
| HTML 구조 변경 | selector 실패 | field policy 기반 다중 selector, 실패율 알림 |
| 법적/약관 이슈 | 운영 중단 위험 | robots.txt와 이용약관 확인, 공개 정보 범위 내 수집 |

## 8. 즉시 실행 체크리스트

- [ ] 공공데이터포털 CSV 다운로드 절차 자동화
- [ ] `vendor_registry.csv` 초안 생성 및 허브 22개사 매핑
- [ ] P0 4개 사업자 collector 구현/정리
- [ ] `PlanRecord` 스키마와 프로모션 metadata 확장 필요성 검토
- [ ] `pytest` 기반 parser 단위 테스트 추가
- [ ] 일일 실행 summary와 가격 변동 diff report 생성

## 9. 참고 URL

- 공공데이터포털: https://www.data.go.kr/data/15107468/fileData.do
- KAIT 알뜰폰 허브사이트 운영 안내: https://www.kait.or.kr/user/MainMenuList.do?cateSeq=8&menuSeq=131
- 알뜰폰허브: https://www.mvnohub.kr/
