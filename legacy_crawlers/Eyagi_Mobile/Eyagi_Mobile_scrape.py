import csv
import re
import time
from typing import List, Dict, Optional, Tuple, Set

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as ExpectedConditions
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager

# ----------------------------
# 설정
# ----------------------------
LIST_PAGE_URL = "https://www.eyagi.co.kr/shop/plan/findMyType.php"
DETAIL_BASE_URL = "https://www.eyagi.co.kr/shop/plan/detail.php?agent_code=KSD0002&comm_code="

OUTPUT_CSV_FILENAME = "eyagi_detail_class_columns.csv"

PAGE_LOAD_TIMEOUT_SECONDS = 30
ELEMENT_WAIT_TIMEOUT_SECONDS = 30

SCROLL_PAUSE_SECONDS = 0.8
SCROLL_MAX_ROUNDS = 30

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/129.0.0.0 Safari/537.36"
)

# 컬럼 생성 정책
MAX_TEXT_LENGTH_PER_CELL = 1000   # 0이면 제한 없음
JOIN_DELIMITER = " | "
SKIP_EMPTY_TEXT = True            # 빈 텍스트는 건너뜀

# 공통 레이아웃 제거용 셀렉터(필요 시 추가/수정)
LAYOUT_REMOVE_SELECTORS = [
    "header", ".header", "footer", ".footer", "nav", ".nav",
    "script", "style", "noscript",
    ".gnb", ".lnb", ".breadcrumb", ".snb", ".side", ".ad", ".banner",
]

# ----------------------------
# 유틸
# ----------------------------
def setup_web_driver() -> webdriver.Chrome:
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-3d-apis")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-notifications")
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.add_argument(f"--user-agent={USER_AGENT}")
    options.add_argument("--lang=ko-KR")
    options.add_argument("--window-size=1920,1080")
    driver = webdriver.Chrome(
        service=ChromeService(ChromeDriverManager().install()),
        options=options
    )
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT_SECONDS)
    return driver

def wait_present(driver: webdriver.Chrome, css: str, timeout: int = ELEMENT_WAIT_TIMEOUT_SECONDS):
    WebDriverWait(driver, timeout).until(
        ExpectedConditions.presence_of_element_located((By.CSS_SELECTOR, css))
    )

def click_load_more_if_any(driver: webdriver.Chrome) -> bool:
    candidates = [
        (By.XPATH, "//button[contains(., '더보기') or contains(., '더 불러오기')]"),
        (By.CSS_SELECTOR, "button.btn-more, a.btn-more"),
        (By.CSS_SELECTOR, ".more, .load-more, .btn_more"),
    ]
    for by, sel in candidates:
        try:
            el = WebDriverWait(driver, 2).until(ExpectedConditions.element_to_be_clickable((by, sel)))
            driver.execute_script("arguments[0].click();", el)
            time.sleep(1.0)
            return True
        except Exception:
            pass
    return False

def scroll_until_all_items_loaded(driver: webdriver.Chrome):
    for _ in range(SCROLL_MAX_ROUNDS):
        before = len(driver.find_elements(By.CSS_SELECTOR, "li.prdc-item"))
        clicked = click_load_more_if_any(driver)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(SCROLL_PAUSE_SECONDS)
        after = len(driver.find_elements(By.CSS_SELECTOR, "li.prdc-item"))
        if after == before and not clicked:
            break

def extract_comm_code_from_onclick(onclick_value: str) -> Optional[str]:
    if not onclick_value:
        return None
    m = re.search(r"prdcDirect\(\s*['\"]([^'\"]+)['\"]\s*\)", onclick_value)
    return m.group(1) if m else None

def build_detail_url(comm_code: str) -> str:
    return f"{DETAIL_BASE_URL}{comm_code}"

def get_clean_body_inner_html(driver: webdriver.Chrome) -> str:
    """
    body를 복제하고, 헤더/푸터/네비/스크립트 등을 제거한 뒤 innerHTML 반환
    """
    script = """
    const removeSelectors = arguments[0];
    const clone = document.body.cloneNode(true);
    for (const sel of removeSelectors) {
      clone.querySelectorAll(sel).forEach(el => el.remove());
    }
    return clone.innerHTML;
    """
    return driver.execute_script(script, LAYOUT_REMOVE_SELECTORS)

def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()

def safe_truncate(text: str, limit: int) -> str:
    if limit and limit > 0 and len(text) > limit:
        return text[:limit] + "…"
    return text

def is_leaf(element) -> bool:
    # 자식 태그(요소)가 하나도 없으면 리프
    return element.find(True) is None

def build_class_text_map_from_html(html: str) -> Dict[str, str]:
    """
    리프 노드만 대상으로 class별 텍스트 수집 → 중복 제거 → 결합
    (부모/조상 텍스트 중복 문제를 크게 줄임)
    """
    soup = BeautifulSoup(html, "html.parser")
    class_to_texts: Dict[str, List[str]] = {}

    for el in soup.find_all(True):
        classes = el.get("class") or []
        if not classes:
            continue
        if not is_leaf(el):
            continue  # 리프가 아니면 스킵 (중복/잡음 줄이기)

        text_value = normalize_whitespace(el.get_text(" ", strip=True))
        if SKIP_EMPTY_TEXT and not text_value:
            continue

        for cls in classes:
            if not cls:
                continue
            class_to_texts.setdefault(cls, []).append(text_value)

    class_to_joined: Dict[str, str] = {}
    for cls, texts in class_to_texts.items():
        unique_texts = list(dict.fromkeys([t for t in texts if t]))
        joined = JOIN_DELIMITER.join(unique_texts)
        class_to_joined[cls] = safe_truncate(joined, MAX_TEXT_LENGTH_PER_CELL)
    return class_to_joined

# ----------------------------
# 메인
# ----------------------------
def main():
    driver = setup_web_driver()
    try:
        # 1) 목록 페이지: comm_code 뽑기
        driver.get(LIST_PAGE_URL)
        try:
            wait_present(driver, "li.prdc-item")
        except Exception:
            pass
        scroll_until_all_items_loaded(driver)

        prdc_items = driver.find_elements(By.CSS_SELECTOR, "li.prdc-item")
        print(f"[prdc-item 수] {len(prdc_items)}")

        comm_codes: List[str] = []
        for li in prdc_items:
            onclick_raw = li.get_attribute("onclick") or ""
            if not onclick_raw:
                try:
                    inner = li.find_element(By.CSS_SELECTOR, "[onclick]")
                    onclick_raw = inner.get_attribute("onclick") or ""
                except Exception:
                    pass
            code = extract_comm_code_from_onclick(onclick_raw)
            if code:
                comm_codes.append(code)

        # 중복 제거
        seen = set()
        unique_codes: List[str] = []
        for c in comm_codes:
            if c in seen:
                continue
            seen.add(c)
            unique_codes.append(c)

        print(f"[comm_code 고유 수] {len(unique_codes)}")

        # 2) 상세 페이지 이동 → 본문만 추출 → 리프 노드 기준 클래스별 텍스트 맵 생성
        rows: List[Tuple[str, Dict[str, str]]] = []
        all_classes: Set[str] = set()

        for idx, code in enumerate(unique_codes, start=1):
            url = build_detail_url(code)
            print(f"[상세 {idx}/{len(unique_codes)}] {code} → {url}")
            driver.get(url)

            # 페이지 로드 완료 및 간단 대기
            time.sleep(1.0)
            try:
                wait_present(driver, "body")
            except Exception:
                pass

            clean_html = get_clean_body_inner_html(driver)
            class_map = build_class_text_map_from_html(clean_html)

            rows.append((code, class_map))
            all_classes.update(class_map.keys())

            # 서버 부하 완화(옵션)
            time.sleep(0.05)

        # 3) CSV 저장 (URL은 저장하지 않고 comm_code + 클래스 컬럼)
        fieldnames = ["comm_code"] + sorted(all_classes)
        with open(OUTPUT_CSV_FILENAME, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for code, class_map in rows:
                row = {"comm_code": code}
                for cls in all_classes:
                    row[cls] = class_map.get(cls, "")
                writer.writerow(row)

        print(f"[CSV 저장 완료] {OUTPUT_CSV_FILENAME} (총 {len(rows)}행)")

    finally:
        driver.quit()

if __name__ == "__main__":
    main()
