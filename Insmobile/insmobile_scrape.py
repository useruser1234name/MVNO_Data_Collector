import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import csv
import re
from typing import List, Optional, Tuple, Dict, Set

# ----------------------------
# 설정
# ----------------------------
SITE_ROOT = "https://www.insmobile.co.kr"
START_URL = "https://www.insmobile.co.kr/rate_plan.do?type=T007"  # 탭이 보이는 시작 페이지
OUTPUT_CSV_FILENAME = "insmobile_class_columns.csv"

BASE_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# 자동 추출 시 과도한 데이터 방지를 위한 옵션
MAX_TEXT_LENGTH_PER_CELL = 1000  # 한 셀당 최대 글자 수 (0이면 제한 없음)
JOIN_DELIMITER = " | "           # 동일 class에 속한 여러 텍스트 결합 구분자
SKIP_EMPTY_TEXT = True           # 비어있는 텍스트는 스킵


# ----------------------------
# 공통 유틸
# ----------------------------
def strip_jsessionid(input_url: str) -> str:
    """URL에 세미콜론 파라미터(예: ;jsessionid=...)가 있으면 제거합니다."""
    return re.sub(r";jsessionid=[^?]*", "", input_url)

def normalize_whitespace(text: str) -> str:
    """공백을 정규화합니다."""
    return re.sub(r"\s+", " ", text or "").strip()

def safe_truncate(text: str, limit: int) -> str:
    """길이 제한이 있다면 자릅니다."""
    if limit and limit > 0 and len(text) > limit:
        return text[:limit] + "…"
    return text


def fetch_and_parse_html_with_session(
    session: requests.Session,
    target_url: str,
    referer_url: Optional[str] = None,
    timeout_seconds: int = 15,
) -> BeautifulSoup:
    """세션을 재사용하여 HTML을 요청하고 파싱합니다."""
    headers = dict(BASE_REQUEST_HEADERS)
    headers["Referer"] = referer_url if referer_url else f"{SITE_ROOT}/"

    response = session.get(target_url, headers=headers, timeout=timeout_seconds)
    response.raise_for_status()

    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding

    parsed_html = BeautifulSoup(response.text, "html.parser")
    return parsed_html


# ----------------------------
# 수집 함수
# ----------------------------
def extract_tab_links(parsed_html: BeautifulSoup, site_root: str) -> Tuple[List[Dict[str, str]], Optional[str]]:
    """
    <ul class="tab_box_list_t3"> 내부의 탭 링크를 추출합니다.
    반환:
      - 전체 탭 리스트: [{ "tab_text": str, "tab_url": str, "is_active": "Y"|"N" }, ...]
      - 활성 탭 URL(없으면 None)
    """
    unordered_list = parsed_html.select_one("ul.tab_box_list_t3")
    all_tab_entries: List[Dict[str, str]] = []
    active_tab_url: Optional[str] = None

    if not unordered_list:
        return all_tab_entries, active_tab_url

    for anchor_tag in unordered_list.select("a.tab_box_link"):
        href_value = anchor_tag.get("href")
        if not href_value:
            continue

        full_url = urljoin(site_root, href_value)
        full_url = strip_jsessionid(full_url)

        tab_text = anchor_tag.get_text(strip=True)
        class_list = anchor_tag.get("class") or []
        is_active = "Y" if "on" in class_list else "N"

        all_tab_entries.append(
            {
                "tab_text": tab_text,
                "tab_url": full_url,
                "is_active": is_active,
            }
        )

        if is_active == "Y":
            active_tab_url = full_url

    # 중복 제거(등장 순서 유지)
    seen = set()
    unique_tab_entries: List[Dict[str, str]] = []
    for entry in all_tab_entries:
        key = (entry["tab_text"], entry["tab_url"])
        if key in seen:
            continue
        seen.add(key)
        unique_tab_entries.append(entry)

    return unique_tab_entries, active_tab_url


def _maybe_add_url(urls: List[str], site_root: str, raw_url: Optional[str]) -> None:
    if not raw_url:
        return
    full_url = urljoin(site_root, raw_url)
    full_url = strip_jsessionid(full_url)
    urls.append(full_url)


def extract_card_list_item_urls(parsed_html: BeautifulSoup, site_root: str) -> List[str]:
    """
    class="rate_list_wrap" → class="card_list rate_list" 하위에서 카드 링크를 폭넓게 수집합니다.
    - a.card_list_item[href]
    - .card_list_item a[href]
    - onclick / data-url 속성도 URL로 간주
    """
    card_list_item_urls: List[str] = []
    rate_list_wrap = parsed_html.select_one("div.rate_list_wrap")
    if not rate_list_wrap:
        return card_list_item_urls

    scope = rate_list_wrap.select_one("div.card_list.rate_list") or rate_list_wrap

    # 1) 직접 a에 card_list_item 클래스가 붙은 경우
    for anchor_tag in scope.select("a.card_list_item[href]"):
        _maybe_add_url(card_list_item_urls, site_root, anchor_tag.get("href"))

    # 2) 카드 컨테이너(.card_list_item) 내부의 a[href]
    for anchor_tag in scope.select(".card_list_item a[href]"):
        _maybe_add_url(card_list_item_urls, site_root, anchor_tag.get("href"))

    # 3) onclick / data-url
    for element in scope.select(".card_list_item"):
        onclick_value = element.get("onclick")
        if onclick_value:
            match = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]", onclick_value)
            if match:
                _maybe_add_url(card_list_item_urls, site_root, match.group(1))
        data_url_value = element.get("data-url")
        if data_url_value:
            _maybe_add_url(card_list_item_urls, site_root, data_url_value)

    # 중복 제거(등장 순서 유지)
    card_list_item_urls = list(dict.fromkeys(card_list_item_urls))
    return card_list_item_urls


# ----------------------------
# “각 class별 컬럼화” 핵심
# ----------------------------
def build_class_text_map(parsed_html: BeautifulSoup) -> Dict[str, str]:
    """
    한 페이지에서 발견되는 모든 class 이름별로 텍스트를 모아 dict로 반환합니다.
    - 동일 class가 여러 요소에 있으면 텍스트를 JOIN_DELIMITER로 결합
    - 너무 긴 텍스트는 MAX_TEXT_LENGTH_PER_CELL로 자름
    """
    class_to_texts: Dict[str, List[str]] = {}

    # 문서의 모든 요소 순회 (필요 시 특정 상위 컨테이너로 범위 제한 가능)
    for element in parsed_html.find_all(True):  # True = 모든 태그
        class_list = element.get("class") or []
        if not class_list:
            continue

        text_value = normalize_whitespace(element.get_text(" ", strip=True))
        if SKIP_EMPTY_TEXT and not text_value:
            continue

        for class_name in class_list:
            if not class_name:
                continue
            class_to_texts.setdefault(class_name, []).append(text_value)

    # 텍스트 결합 및 길이 제한 적용
    class_to_joined_text: Dict[str, str] = {}
    for class_name, texts in class_to_texts.items():
        # 중복 텍스트 제거 + 순서 유지
        unique_texts = list(dict.fromkeys([t for t in texts if t]))
        joined = JOIN_DELIMITER.join(unique_texts)
        joined = safe_truncate(joined, MAX_TEXT_LENGTH_PER_CELL)
        class_to_joined_text[class_name] = joined

    return class_to_joined_text


# ----------------------------
# CSV 저장
# ----------------------------
def save_pages_as_class_columns_csv(
    page_class_maps: List[Tuple[str, Dict[str, str]]],
    output_csv_filename: str
) -> None:
    """
    page_class_maps: [(url, {class_name: text, ...}), ...]
    전체 페이지에서 관찰된 class 이름의 합집합을 컬럼으로 만들어 CSV 저장
    """
    # 전체 클래스 합집합
    all_classes: Set[str] = set()
    for _, class_map in page_class_maps:
        all_classes.update(class_map.keys())

    # 컬럼 순서: url + 정렬된 class 이름
    fieldnames = ["url"] + sorted(all_classes)

    with open(output_csv_filename, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        for page_url, class_map in page_class_maps:
            row: Dict[str, str] = {"url": page_url}
            for class_name in all_classes:
                row[class_name] = class_map.get(class_name, "")
            writer.writerow(row)


# ----------------------------
# 메인
# ----------------------------
def main() -> None:
    session = requests.Session()
    session.headers.update(BASE_REQUEST_HEADERS)

    # 1) 시작 페이지 로드 및 탭 수집
    start_url_clean = strip_jsessionid(START_URL)
    parsed_html_for_tabs = fetch_and_parse_html_with_session(
        session=session,
        target_url=start_url_clean,
        referer_url=None,
    )
    all_tab_entries, active_tab_url = extract_tab_links(parsed_html_for_tabs, SITE_ROOT)

    print(f"[탭 수집] 총 {len(all_tab_entries)}개 (활성: {active_tab_url if active_tab_url else '없음'})")
    for entry in all_tab_entries:
        print(f"- {entry['tab_text']} | {entry['tab_url']} | active={entry['is_active']}")

    # 2) 각 탭 페이지에서 카드 링크 수집
    all_card_list_item_urls: List[str] = []
    for tab_entry in all_tab_entries:
        tab_text = tab_entry["tab_text"]
        tab_url = tab_entry["tab_url"]
        print(f"\n[탭 페이지 요청] {tab_text} → {tab_url}")

        parsed_html_for_cards = fetch_and_parse_html_with_session(
            session=session,
            target_url=tab_url,
            referer_url=start_url_clean,
        )
        card_urls = extract_card_list_item_urls(parsed_html_for_cards, SITE_ROOT)
        print(f"  - card_list_item URL {len(card_urls)}개 수집")
        all_card_list_item_urls.extend(card_urls)

    # 중복 제거
    all_card_list_item_urls = list(dict.fromkeys(all_card_list_item_urls))
    print(f"\n[총 카드 상세 페이지 수] {len(all_card_list_item_urls)}")

    # 3) 각 카드 상세 페이지에 접속하여 class별 텍스트 맵 생성
    page_class_maps: List[Tuple[str, Dict[str, str]]] = []
    for index, detail_url in enumerate(all_card_list_item_urls, start=1):
        print(f"[상세 페이지 요청 {index}/{len(all_card_list_item_urls)}] {detail_url}")
        parsed_html_for_detail = fetch_and_parse_html_with_session(
            session=session,
            target_url=detail_url,
            referer_url=None,  # 필요시 상위 페이지로 바꿔도 됨
        )
        class_map = build_class_text_map(parsed_html_for_detail)
        page_class_maps.append((detail_url, class_map))

    # 4) CSV로 저장 (url + 모든 class 이름의 컬럼)
    save_pages_as_class_columns_csv(page_class_maps, OUTPUT_CSV_FILENAME)
    print(f"\n[CSV 저장 완료] {OUTPUT_CSV_FILENAME} (총 {len(page_class_maps)}행)")

if __name__ == "__main__":
    main()
