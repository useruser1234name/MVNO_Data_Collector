## KT M모바일 요금제 모달 수집 전략

본 문서는 KT M모바일 요금제 목록 페이지의 아코디언과 모달(팝업)로 노출되는 상세 정보를 자동 수집하기 위한 실무 전략을 정리합니다. 대상 페이지: [요금제 소개](https://www.ktmmobile.com/rate/rateList.do).

### 1) 목표
- 메인 탭, 서브 탭, 아코디언(카테고리)을 순회하며 모든 요금제 카드를 탐색
- 각 카드의 "상세/자세히" 버튼을 클릭해 모달을 열고 상세 스펙을 구조화하여 추출
- 실패 시 재시도/복구, 팝업(비교함, 동의 안내 등)으로 인한 방해 요소 제거
- 성능/안정성/재현성을 위한 로그, 스크린샷, 원본 HTML 보존

### 2) 기술 스택 권장
- 기본: Playwright Python (동기 API) — 안정적인 모달/탭/아코디언 제어와 네트워크 이벤트 후킹이 용이
- 보조: Selenium (이미 스캐폴딩 있음) — 로컬 디버그용 또는 비상 대체 경로
- 로깅: `KT_MMobile/PLAYWRIGHT_LOGGING_STRATEGY.md`의 가이드 준수

### 3) DOM/상호작용 모델 요약
- 메인 탭: `button.c-tabs__button[id^="rateListTab"]` (예: "유심/eSIM 요금제", "제휴 요금제", "휴대폰 요금제")
- 서브 탭: 각 탭패널 내 `role=tab` (예: "LTE 요금제", "5G 요금제")
- 아코디언 헤더: `button[aria-controls][data-rate-adsvc-ctg-cd]` (타이틀/서브타이틀 포함)
- 카드 목록: 아코디언 패널 내 `li` 혹은 `.c-product` 단위
- 모달: `[role="dialog"][aria-modal="true"]` 또는 `.c-modal.is-active`

위 선택자는 변경될 수 있으므로, 다음의 내결함성 규칙을 적용합니다.
- 우선 순위: 정확 셀렉터 → 접근성 속성(`role`, `aria-*`) → 텍스트 포함
- `expect(locator).to_be_visible()`로 가시성·상호작용 가능 상태를 확인 후 클릭
- `aria-expanded=true` 전환을 대기해 아코디언이 실제로 열렸는지 확인

### 4) 팝업/방해 요소 처리
- 비교함/이벤트/쿠키 동의 등: 화면 진입 직후 아래 텍스트를 우선적으로 닫기
  - `text=동의 후 닫기`, `text=오늘 하루 그만보기`, `aria-label=닫기`
- 실패 시 무시하고 진행하되, 클릭 전 `locator.evaluate('el => el.click()')`의 강제 클릭은 지양 (의도치 않은 상태 오염 방지)

### 5) 수집 플로우
1. 페이지 진입: `wait_until="domcontentloaded"` 후 0.3~0.6초 안정 대기
2. 팝업 정리(`disable_blocking_ui`)
3. 메인 탭 순회 → 탭 클릭 → 해당 탭패널 활성 대기
4. 서브 탭 존재 시 순회 → `aria-selected=true` 대기
5. 아코디언 헤더 메타 수집 → `aria-expanded=false` 인 항목만 클릭/확장 → 패널 ready 대기
6. 패널 내 카드 순회:
   - 스크롤 인뷰(scrollIntoView), 50~200ms 딜레이
   - "상세" 버튼 찾기: `button:has-text("상세")`, `a:has-text("자세히")`, `[aria-haspopup="dialog"]`
   - 클릭 → 모달 등장 대기 (`.c-modal.is-active` or `[role=dialog][aria-modal=true]`)
   - 상세 스펙 추출(아래 6 참고)
   - 닫기 버튼 클릭(`.c-modal__close`, `button:has-text("닫기")`, `Escape` 키 fallback)
7. 전 구간에서 예외 발생 시 스크린샷+HTML 보존 후 다음 카드로 진행

### 6) 상세 스펙 파싱 전략(모달 내부)
- 공통 패턴: 정의 리스트(dl/dt/dd), 표(table th/td), 키-값 그리드
- 라벨 표준화 테이블(우측은 정규식/부분일치 허용):
  - 요금제명 → `name`
  - 월정액/기본료 → `monthly_fee`
  - 데이터 → `data_allowance`
  - 음성/통화 → `voice_minutes`
  - 문자/SMS → `sms_count`
  - 네트워크(LTE/5G) → `network_type`
  - 프로모션/유의사항 → `promotion`
- 파싱 알고리즘:
  1) dt/th 텍스트를 정규화(공백/기호 제거, 한글 숫자 혼용 처리)
  2) 사전 매핑으로 키 결정 → dd/td 텍스트 정규화(금액/용량/분/건 파싱)
  3) 숫자 추출 유틸: 금액(원, 만원), 데이터(GB→MB), 무제한 표기 처리
  4) 추가 혜택/제휴/조건은 `metadata`로 JSON 리스트화

### 7) 네트워크 API 후킹(있을 경우 우선 사용)
- Playwright의 `page.on('response')`/`wait_for_response`를 이용해 XHR/Fetch 응답 중 `application/json`을 선별 저장
- 상세 모달 오픈 시 호출되는 API가 존재한다면, 동일 input으로 직접 호출하여 속도/안정성 확보
- 발견된 엔드포인트·쿼리 파라미터·응답 스키마는 `KTMMOBILE_API_PROTOCOL.md`의 "사이트 백엔드 API" 섹션에 기록/갱신

### 8) 성능/안정성 옵션
- 카드 간 지연: 150–350ms 랜덤
- 자원 차단: 이미지/폰트 차단(route)로 속도 개선(모달 내 텍스트만 필요할 때)
- 타임아웃(ms): 등장 5,000 / 열림 7,000 / 닫힘 5,000 (초기값)
- 최대 항목 제한(디버그): `--max-per-tab` 등 가드 옵션

### 9) 산출물
- 정규화 레코드(JSON/CSV): `ktmm_out/ktmmobile_modal_data.csv`, `ktmm_out/ktmmobile_plans.json`
- 원본 보존: 카드 단위 모달 HTML(`ktmm_out/html/KTMM_{run_id}/{card_id}.html`), 스크린샷(`ktmm_out/modals/{card_id}.png`)
- 로그/트레이스: `KT_MMobile/logs/playwright_activity.log`, `KT_MMobile/trace.zip`

### 10) 예시 코드(요약, Playwright)
```python
from playwright.sync_api import sync_playwright, expect

URL = "https://www.ktmmobile.com/rate/rateList.do"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=100)
    page = browser.new_page()
    page.goto(URL, wait_until="domcontentloaded")

    # 팝업 정리
    for txt in ["동의 후 닫기", "오늘 하루 그만보기", "닫기"]:
        btn = page.locator(f"button:has-text('{txt}')")
        if btn.first.is_visible():
            btn.first.click(timeout=500)

    # 메인 탭들
    for main in page.locator("button.c-tabs__button[id^='rateListTab']").all():
        main.click()
        expect(main).to_have_attribute("aria-selected", "true")

        # 서브 탭들
        for sub in page.locator("[role=tab]").all():
            sub.click()
            expect(sub).to_have_attribute("aria-selected", "true")

            # 아코디언 헤더들
            for hdr in page.locator("button[aria-controls][data-rate-adsvc-ctg-cd]").all():
                if hdr.get_attribute("aria-expanded") != "true":
                    hdr.click()
                    page.wait_for_timeout(250)

                # 카드의 상세 버튼 → 모달 추출 → 닫기
                for btn in page.locator(".c-product button, .c-product a").filter(has_text="상세").all():
                    btn.click()
                    modal = page.locator(".c-modal.is-active, [role=dialog][aria-modal=true]").first
                    expect(modal).to_be_visible()
                    html = modal.inner_html()
                    # TODO: html 파싱 → dict 변환 후 저장
                    page.locator(".c-modal__close, button:has-text('닫기')").first.click()

    browser.close()
```

### 11) 장애/복구 시나리오
- 탭/아코디언 클릭 무반응: 스크롤 인뷰 → 재시도 2회 → 탭 재선택 후 다시 시도
- 모달 닫힘 실패: `Escape` → 바깥 클릭 → 강제 닫기 버튼 클릭 순으로 시도
- 예외 발생: 스크린샷+HTML 보존 후 다음 카드 진행(전체 중단 금지)

### 12) 참고
- 운영 페이지: [요금제 소개](https://www.ktmmobile.com/rate/rateList.do)
- 활동 로그 전략: `KT_MMobile/PLAYWRIGHT_LOGGING_STRATEGY.md`




