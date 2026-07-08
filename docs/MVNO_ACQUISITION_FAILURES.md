# MVNO 요금 획득 실패 및 미획득 업체 목록

본 문서는 이번 스프린트에서 계획서 기준으로 수집 대상에 올린 업체의 구현/미획득 상태와, 현재 실행 환경에서 획득 실패가 확인된 업체를 별도로 정리한 목록이다.

## 실행 환경에서 확인된 실패

| 업체/브랜드 | Collector | 사이트 주소 | 실패 단계 | 실패 사유 | 후속 조치 |
| --- | --- | --- | --- | --- | --- |
| U+유모바일 | `uplusumobile` | https://www.uplusumobile.com/ | discovery | `requests` 선택 의존성 미설치로 collector import 불가 | `requests`, `beautifulsoup4`, `lxml`, `urllib3` 의존성 선언/설치 후 통합 실행 |
| 더원모바일 | `theonemobile` | https://www.theonem.co.kr/view/plan/phone_plan.aspx | run | 현재 컨테이너 직접 HTTPS 요청이 `403 Forbidden` 터널 오류로 차단 | 배포망/허용 네트워크에서 재실행, 필요 시 HTML seed 경로 metadata로 보정 |
| 찬스모바일 | `chancemobile` | https://chancemobile.co.kr/view/plan/phone_plan.aspx | run | 현재 컨테이너 직접 HTTPS 요청이 `403 Forbidden` 터널 오류로 차단 | 배포망/허용 네트워크에서 재실행, 필요 시 HTML seed 경로 metadata로 보정 |
| 스마텔 | `smartel` | https://www.smartel.kr/phoneplan | run | 현재 컨테이너 직접 HTTPS 요청이 `403 Forbidden` 터널 오류로 차단 | 배포망/허용 네트워크에서 재실행, 필요 시 HTML seed 경로 metadata로 보정 |

## 이번 스프린트 구현 완료

| 우선순위 | 업체/브랜드 | Collector | 사이트 주소 | 구현 내용 | 검증 결과 |
| --- | --- | --- | --- | --- | --- |
| P0 | KTM모바일 | `ktmmobile` | https://www.ktmmobile.com/ | 로컬 모달 CSV를 `PlanRecord`로 변환하는 표준 collector 추가 | 통합 실행에서 4건 records.jsonl 생성 |
| P0 | SK세븐모바일 | `sk7mobile` | https://www.sk7mobile.com/ | 로컬 상세 CSV를 `PlanRecord`로 변환하는 표준 collector 추가 | 통합 실행에서 203건 records.jsonl 생성 |
| P0 | 더원모바일 | `theonemobile` | https://www.theonem.co.kr/view/plan/phone_plan.aspx | 공식 HTML 요금제 collector 추가 | 단위 테스트에서 대표 HTML 파싱 검증, 배포망 통합 검증 필요 |
| P1 | 스마텔 | `smartel` | https://www.smartel.kr/phoneplan | 공식 HTML 요금제 collector 추가 | 단위 테스트에서 대표 HTML 파싱 검증, 배포망 통합 검증 필요 |
| P2 | 찬스모바일 | `chancemobile` | https://chancemobile.co.kr/view/plan/phone_plan.aspx | 공식 onclick 목록 collector 추가 | 단위 테스트에서 대표 HTML 파싱 검증, 배포망 통합 검증 필요 |

## 미획득/구현 대기 업체

| 우선순위 | 업체/브랜드 | Collector 후보 | 사이트 주소 | 현재 상태 | 후속 조치 |
| --- | --- | --- | --- | --- | --- |
| P0 | KB리브모바일 | `liivm` | https://www.liivm.com/ | 표준 collector 미구현 | 공식 웹/모바일 API 탐색 후 수집기 작성 |
| P1 | 헬로모바일 | `hellomobile` | https://direct.lghellovision.net/ | 미구현 | 공식 요금제 목록 API/HTML 분석 |
| P1 | A모바일 | `amobile` | https://www.amobile.co.kr/ | 기존 스크립트는 있으나 표준 collector 미포팅 | 기존 스크립트 parser 단위 테스트 작성 후 이관 |
| P1 | 아이즈모바일 | `eyesmobile` | https://www.eyes.co.kr/ | 미구현 | 목록/상세 DOM 정책 작성 |
| P1 | 이야기모바일 | `eyagi` | https://www.eyagi.co.kr/ | 기존 스크립트는 있으나 표준 collector 미포팅 | 기존 스크립트 표준화 |
| P1 | 티플러스 | `tplus` | https://www.tplusmobile.com/ | 미구현 | eSIM/일반 요금제 API 조사 |
| P2 | 웰 | `winners` | https://www.wellmobile.co.kr/ | 미구현 | 공식 페이지 접근/요금제 URL 확인 |
| P2 | 모빙 | `mobing` | https://www.mobing.co.kr/ | 미구현 | API/HTML 수집 방식 결정 |
| P2 | 프리티 | `freet` | https://www.freet.co.kr/ | 미구현 | 공식 요금제 페이지 parser 작성 |
| P2 | 스카이라이프모바일 | `skylife` | https://www.skylife.co.kr/product/mobile/goodsList.do | 미구현 | 모바일 요금제 섹션 수집 |
| P2 | 이지모바일/EG모바일 | `egmobile` | https://www.egmobile.co.kr/ | 기존 스크립트는 있으나 표준 collector 미포팅 | 기존 `EGMobile/` 스크립트 정리 |
| P2 | 고고모바일 | `gogomobile` | https://www.gogomobile.co.kr/ | 미구현 | 허브/공식 페이지 대조 수집 |
| P2 | 슈가모바일 | `sugarmobile` | https://www.sugarmobile.co.kr/ | 기존 스크립트는 있으나 표준 collector 미포팅 | URL 수집/HTML 수집 역할 분리 후 이관 |
| P2 | 시월모바일 | `siwolmobile` | https://www.siwolmobile.com/ | 기존 스크립트 검증 필요 | Playwright 필요 여부 확인 |
| P2 | 우리원모바일 | `wooriwonmobile` | https://www.wooriwonmobile.com/ | 기존 스크립트 검증 필요 | 공식 사업자명/제휴 구조 확인 |
| P2 | 쉐이크모바일 | `shakemobile` | https://www.shakemobile.co.kr/ | 기존 스크립트 검증 필요 | 디렉터리 오탈자 정리 및 parser 테스트 |
| P3 | 모나모바일 | `monamobile` | https://www.monamobile.co.kr/ | 원장 대조 필요 | 공식 사업자명/요금제 URL 확인 |
| P3 | SMT모바일 | `smtmobile` | https://www.smtmobile.co.kr/ | 원장 대조 필요 | 공식 사업자명/요금제 URL 확인 |
| P3 | 스피츠모바일 | `spitzmobile` | https://www.spitzmobile.co.kr/ | 원장 대조 필요 | 공식 사업자명/요금제 URL 확인 |
| P3 | 에르엘모바일 | `erelmobile` | https://www.urmobile.co.kr/ | 원장 대조 필요 | 공식 사업자명/요금제 URL 확인 |

## 미획득 원인 분석

| 원인 유형 | 해당 업체 | 분석 | 대응 |
| --- | --- | --- | --- |
| 선택 의존성 미설치 | U+유모바일 | 표준 collector는 존재하지만 현재 환경에 `requests`가 없어 import 단계에서 제외됨 | 의존성 파일 추가 또는 실행 이미지에 `requests`, `beautifulsoup4`, `lxml` 설치 |
| 표준 collector 미구현 | KB리브모바일, 헬로모바일, 아이즈모바일 등 | 공식 사이트/API 분석 또는 기존 스크립트 포팅이 아직 완료되지 않음 | `vendor_registry.csv` 우선순위 순서로 collector 추가 |
| 네트워크 접근 제한 | 더원모바일, 찬스모바일, 스마텔 | collector 구현은 완료했지만 현재 컨테이너의 직접 HTTPS 요청은 일부 사이트에서 403 터널 오류가 발생할 수 있음 | 배포망 또는 허용된 실행 환경에서 통합 실행하고 실패 시 `--failure-report`로 분리 |
| 기존 스크립트와 표준 스키마 불일치 | A모바일, 이야기모바일, EG모바일 등 | 단발 스크립트는 있으나 `BaseCollector`/`PlanRecord` 생명주기와 연결되지 않음 | parser 단위 테스트 작성 후 `collectors/vendors/`로 이관 |
| 공식 사업자명/도메인 검증 필요 | P3 후보 | 브랜드명과 운영사 원장 매핑이 불확실함 | 공공데이터 원장과 공식 사이트 대조 후 구현 여부 결정 |

## 관리 원칙

- 통합 실행에서 collector가 실패하면 `pipeline.run_collectors --failure-report <path>` 옵션으로 이 문서와 동일한 형태의 실패 보고서를 생성한다.
- 표준 collector 구현이 완료되어 요금제 JSONL 획득이 검증되면 해당 업체를 이 목록에서 제거하고 `etl/reference/vendor_registry.csv`의 `crawl_status`를 `implemented`로 변경한다.
- 사이트 주소가 변경되거나 브랜드/운영사가 불일치하면 먼저 `vendor_registry.csv`를 갱신한 뒤 수집기를 수정한다.
