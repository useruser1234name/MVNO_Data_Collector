## Playwright 활동 로그 수집 전략

본 문서는 KT M모바일 요금제 페이지(`https://www.ktmmobile.com/rate/rateList.do`) 수집 시, Playwright 기반 활동 로그 전략을 설명합니다.

### 목표
- 에러 원인 분석, 재현, 성능 이슈 파악을 위한 활동 로그 축적
- 요청 실패/에러/콘솔 경고를 파일로 보존하여 배치 수집 안정성 향상

### 로그 종류 및 위치
- 파일 경로: `KT_MMobile/logs/playwright_activity.log`
- 수집 항목:
  - `[console:<type>] <text>`: 브라우저 콘솔 로그 (log, warn, error 등)
  - `[pageerror] <message>`: 페이지 런타임 에러
  - `[requestfailed] <METHOD> <URL> -> <reason>`: 요청 실패 이벤트
  - `[response:<status>] <METHOD> <URL>`: 4xx/5xx 응답 기록
  - 스크립트 자체 로그: 주요 단계, 모달 클릭, 스크린샷 저장 등은 stdout에 출력되며 필요 시 로그 파일 확장 가능

### 트레이싱
- 옵션 `--trace` 사용 시 `KT_MMobile/trace.zip` 에 Playwright trace 저장
- 분석 도구: `playwright show-trace KT_MMobile/trace.zip`

### 모달 수집 관련 베스트 프랙티스
- `.c-modal.is-active` 가시성 대기 후 수집
- 모달 내부 아코디언, 더보기, 스크롤을 통해 지연 로드된 콘텐츠 노출
- 수집 전 `disable_blocking_ui` 로 플로팅 비교함 등 클릭 방해 요소 비활성화
- 예외 상황 시 `close_all_modals` 로 모달 상태 정리 후 재시도

### 성능/안정성 팁
- `REQUEST_INTERVAL_SEC` 로 카드 간 딜레이 부여(서버/봇탐지 완화)
- `max-per-tab` 옵션으로 디버그 시 카드 수 제한
- `headless` 해제 및 `--slowmo` 사용으로 인간 행동과 유사한 타이밍 구현

### 개인정보/보안 유의
- 페이지 내 마스킹된 정보는 수집하지 않으며, 인증/로그인 영역을 수집 범위에서 제외

### 참고 링크
- 요금제 목록 페이지: https://www.ktmmobile.com/rate/rateList.do


