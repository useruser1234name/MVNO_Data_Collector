# -*- coding: utf-8 -*-
"""
KT M모바일 동적 수집기 — 순차 파이프라인 안정화 버전
- 단계별 진행: 메인탭 -> 서브탭 -> 아코디언(스캔) -> 아이템 수(스캔) -> 모달 파싱(실행)
- 메인탭 스코프 명확화(id^="rateListTab"), 서브탭은 메인탭 패널 내부에서만 탐색
- 탭/아코디언 전환 대기 강화 + 스크롤 펄스 + UI 차단요소 pointer-events:none
- 행 단위(JSONL/CSV) 즉시 적재 + 재실행 내구성(중복 키 스킵)
"""

import argparse
import csv
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Optional, Tuple

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout, Page, Locator

DEFAULT_URL = "https://www.ktmmobile.com/rate/rateList.do"

# ---- 튜닝 파라미터 ----
REQ_DELAY_SEC = 0.5              # 클릭/닫기 매너타임
PANEL_TIMEOUT_MS = 12000         # 탭/아코디언 준비 대기
MODAL_TIMEOUT_MS = 12000         # 모달 열림 대기
SCROLL_PULSES = 3                # 전환 후 스크롤 펄스 횟수
SCROLL_DELTA = 1200              # 한 번에 스크롤 양
RETRY_CLICK = 2                  # 클릭 재시도
RETRY_MODAL = 2                  # 모달 열기 재시도

# ---- 유틸 ----
def ts() -> str:
    return time.strftime("[%H:%M:%S]")

def norm(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    return re.sub(r"\s+", " ", s).strip()

def direct_text(el) -> str:
    if not el:
        return ""
    return "".join(el.find_all(string=True, recursive=False)).strip()

def money(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    m = re.findall(r"\d+", s.replace(",", ""))
    return int("".join(m)) if m else None

def safe_filename(name: str, maxlen: int = 90) -> str:
    name = re.sub(r"[\\/:*?\"<>|\s]+", "_", name).strip("_")
    return name[:maxlen] or "item"

def ensure_dirs(base: Path):
    (base / "html").mkdir(parents=True, exist_ok=True)
    (base / "logs").mkdir(parents=True, exist_ok=True)

def mk_key(*parts: str) -> str:
    raw = "||".join([p or "" for p in parts])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()

# ---- 파싱(Modal) ----
def extract_mbps_lines_from_modal(soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str]]:
    toplist_hits = []
    for ul in soup.select(
        "ul.product-summary, ul.notification.free, "
        ".product-detail .product-summary, .detail-info ul.notification.free"
    ):
        for li in ul.select("li"):
            txt = norm(direct_text(li) or " ".join(li.stripped_strings))
            if txt and re.search(r"(?i)\bmbps\b", txt):
                toplist_hits.append(txt)
    if not toplist_hits:
        for li in soup.select(".c-modal__body li, .c-modal__content li"):
            txt = norm(direct_text(li) or " ".join(li.stripped_strings))
            if txt and re.search(r"(?i)\bmbps\b", txt):
                toplist_hits.append(txt)
    toplist_out = " | ".join(list(dict.fromkeys(toplist_hits))) if toplist_hits else None

    guide_out = None
    h = None
    for x in soup.select("h1,h2,h3,h4"):
        if "데이터 이용 안내" in x.get_text(strip=True):
            h = x
            break
    if h:
        cont = h.find_next(
            class_=re.compile(r"(?:plan-detail-conts|acc-conts|product-detail|c-product--box|plan-sect)")
        ) or h
        hits = []
        for li in cont.select("li"):
            txt = norm(" ".join(li.stripped_strings))
            if txt and re.search(r"(?i)\bmbps\b", txt):
                hits.append(txt)
        if hits:
            guide_out = " | ".join(list(dict.fromkeys(hits)))
    return toplist_out, guide_out

def parse_modal_fields(modal_html: str) -> dict:
    soup = BeautifulSoup(modal_html, "lxml")
    # 제목 후보
    title = None
    for sel in ["#modalProductTitle", ".c-modal__title", ".product-detail__title", ".c-modal .title", "h1,h2"]:
        el = soup.select_one(sel)
        if el:
            title = norm(el.get_text(" ", strip=True))
            if title:
                break
    # 가격 후보
    price_text = None
    for sel in [".product-detail__price", ".product-detail__price-wrap", ".u-co-red", ".u-co-black", ".price"]:
        el = soup.select_one(sel)
        if el:
            price_text = norm(el.get_text(" ", strip=True))
            if price_text:
                break
    price_num = money(price_text)
    speed_top, speed_guide = extract_mbps_lines_from_modal(soup)
    return {
        "modal_title": title or "",
        "modal_price_text": price_text or "",
        "modal_price": price_num if price_num is not None else "",
        "speed_toplist_modal": speed_top or "",
        "speed_dataguide_modal": speed_guide or "",
    }

# ---- 브라우저 보조 ----
def disable_blocking_ui(page: Page):
    js = """
    for (const sel of [
      '#pullProductCompare', '.rate-compare__floating', '.floating-compare',
      'button:has-text("요금제 비교함")', '.btn-compare', '.compare',
      '.ly-page--title', 'header', '#header'
    ]) {
      try {
        const el = document.querySelector(sel);
        if (el) el.style.pointerEvents = 'none';
      } catch (e) {}
    }
    """
    try:
        page.evaluate(js)
    except Exception:
        pass

def scroll_pulse(page: Page, pulses: int = SCROLL_PULSES, delta: int = SCROLL_DELTA):
    for _ in range(pulses):
        try:
            page.mouse.wheel(0, delta)
            page.wait_for_timeout(120)
            page.mouse.wheel(0, -delta)
            page.wait_for_timeout(120)
        except Exception:
            break

def click_safely(btn: Locator):
    # 가려짐 방지 + 재시도 + JS 클릭 폴백
    for attempt in range(1, RETRY_CLICK + 2):
        try:
            try:
                btn.scroll_into_view_if_needed()
            except Exception:
                pass
            btn.click(timeout=3000)
            return True
        except Exception:
            # JS click fallback
            try:
                btn.evaluate("el => el.click()")
                return True
            except Exception:
                if attempt <= RETRY_CLICK:
                    time.sleep(0.25)
                    continue
                return False

# ---- 탭/패널 탐색 ----
def main_tabs(page: Page) -> list[dict]:
    # 메인탭만: id^="rateListTab"
    tabs = page.locator('button.c-tabs__button[id^="rateListTab"]')
    out = []
    n = tabs.count()
    for i in range(n):
        b = tabs.nth(i)
        try:
            text = b.inner_text().strip()
            # 숨김 텍스트 제거
            text = text.replace("현재 선택됨", "").strip()
            aria_controls = b.get_attribute("aria-controls") or ""
            out.append({"name": text, "locator": b, "panel_id": aria_controls})
        except Exception:
            continue
    return out

def subtabs_in_main_panel(page: Page, panel_id: str) -> list[dict]:
    if not panel_id:
        return []
    panel = page.locator(f'#{panel_id}')
    # 해당 패널 내부의 서브탭만
    subs = panel.locator('button.c-tabs__button[role="tab"]')
    out = []
    n = subs.count()
    for i in range(n):
        b = subs.nth(i)
        try:
            text = b.inner_text().strip().replace("현재 선택됨", "").strip()
            aria_controls = b.get_attribute("aria-controls") or ""
            out.append({"name": text, "locator": b, "panel_id": aria_controls})
        except Exception:
            pass
    # 중복 제거(텍스트 기준)
    uniq = []
    seen = set()
    for x in out:
        if x["name"] and x["name"] not in seen:
            uniq.append(x); seen.add(x["name"])
    return uniq

def wait_panel_ready(scope: Locator) -> bool:
    # 리스트 컨테이너 또는 아코디언/카드 중 하나라도 준비되면 OK
    try:
        scope.locator("ul.rate-content__list").first.wait_for(state="visible", timeout=PANEL_TIMEOUT_MS)
        return True
    except Exception:
        pass
    try:
        scope.locator(".runtime-data-insert.c-accordion__button").first.wait_for(state="visible", timeout=PANEL_TIMEOUT_MS)
        return True
    except Exception:
        return False

def open_main_tab(page: Page, tab: dict) -> bool:
    disable_blocking_ui(page)
    ok = click_safely(tab["locator"])
    page.wait_for_timeout(int(REQ_DELAY_SEC * 1000))
    if not ok:
        return False
    # 활성 패널 준비 대기
    panel = page.locator(f'#{tab["panel_id"]}') if tab["panel_id"] else page.locator("[role=tabpanel]").first
    scroll_pulse(page)
    ready = wait_panel_ready(panel)
    return ready

def open_subtab(page: Page, main_panel_id: str, subtab: dict) -> Tuple[bool, Locator]:
    disable_blocking_ui(page)
    ok = click_safely(subtab["locator"])
    page.wait_for_timeout(int(REQ_DELAY_SEC * 1000))
    panel = page.locator(f'#{subtab["panel_id"]}') if subtab["panel_id"] else page.locator(f'#{main_panel_id}')
    scroll_pulse(page)
    ready = wait_panel_ready(panel)
    return ready and ok, panel

# ---- 아코디언/아이템/모달 ----
def accordion_headers(panel: Locator) -> list[dict]:
    headers = panel.locator(".runtime-data-insert.c-accordion__button")
    out = []
    n = headers.count()
    for i in range(n):
        h = headers.nth(i)
        try:
            h_text = ""
            hidden = h.locator(".c-hidden")
            if hidden.count():
                h_text = hidden.first.inner_text().strip()
            if not h_text:
                h_text = h.inner_text().strip()
            h_text = h_text.replace("현재 선택됨", "").strip()
            acc_id = h.get_attribute("aria-controls") or ""
            out.append({"name": h_text, "locator": h, "content_id": acc_id})
        except Exception:
            pass
    return out

def open_accordion(panel: Locator, header: dict) -> Optional[Locator]:
    # 항상 차단 UI 먼저 끄기
    try:
        disable_blocking_ui(panel.page)
    except Exception:
        pass

    h = header["locator"]
    cid = header.get("content_id") or ""

    # 컨텐트 패널 우선 식별 (aria-controls 우선, 없으면 형제 패널로 보강)
    cont = panel.locator(f"#{cid}") if cid else None
    if not cont or cont.count() == 0:
        # header가 속한 아코디언 아이템의 패널을 직접 찾기
        cont = h.locator(
            "xpath=ancestor::li[contains(@class,'c-accordion__item')]"
            "//div[contains(@class,'c-accordion__panel')]"
        ).first

    # 뷰포트 중앙으로 가져와 클릭 준비
    try:
        h.evaluate("el => el.scrollIntoView({block:'center'})")
    except Exception:
        try: h.scroll_into_view_if_needed()
        except Exception: pass

    # 이미 열려 있나?
    def is_expanded() -> bool:
        try:
            ae = (h.get_attribute("aria-expanded") or "").lower() == "true"
        except Exception:
            ae = False
        if cont and cont.count() > 0:
            try:
                return ae or cont.evaluate(
                    """el => el.classList?.contains('expanded') || (
                           getComputedStyle(el).display !== 'none' && el.offsetHeight > 0
                       )"""
                )
            except Exception:
                return ae
        return ae

    # 최대 3회 시도: 클릭 -> 확장 대기 -> 아이템 대기 폴백
    for attempt in range(3):
        if not is_expanded():
            if not click_safely(h):
                time.sleep(0.25)
                continue
            time.sleep(REQ_DELAY_SEC)

        # 확장 상태 우선 대기
        ok = False
        try:
            if cont and cont.count() > 0:
                panel.page.wait_for_function(
                    """el => el && (
                           el.classList?.contains('expanded') ||
                           (getComputedStyle(el).display !== 'none' && el.offsetHeight > 0)
                       )""",
                    arg=cont.element_handle(),
                    timeout=PANEL_TIMEOUT_MS
                )
                ok = True
        except Exception:
            ok = False

        # 아이템 등장 대기(폴백)
        if not ok:
            try:
                (cont if cont and cont.count() > 0 else panel) \
                    .locator("li.rate-content__item").first \
                    .wait_for(state="visible", timeout=4000)
                ok = True
            except Exception:
                ok = False

        if ok:
            return cont if cont and cont.count() > 0 else panel

        # 마지막 폴백: 스크롤 펄스 후 다시 시도
        try:
            panel.page.mouse.wheel(0, 600)
            panel.page.wait_for_timeout(120)
            panel.page.mouse.wheel(0, -400)
            panel.page.wait_for_timeout(120)
        except Exception:
            pass

    return None

def items_in_accordion(content: Locator) -> list[Locator]:
    li = content.locator("li.rate-content__item")
    c = li.count()
    return [li.nth(i) for i in range(c)]

def open_modal_from_item(page: Page, item: Locator) -> Tuple[Optional[Locator], Optional[str]]:
    # 트리거 후보
    triggers = [
        "a[data-dialog-target*='modal'], a[data-dialog-trigger*='modal']",
        "button[data-dialog-target*='modal'], button[data-dialog-trigger*='modal']",
        "a[href*='modal'], button:has(i.c-icon--information)"
    ]
    trigger = None
    for sel in triggers:
        loc = item.locator(sel)
        if loc.count() > 0:
            trigger = loc.first
            break
    if not trigger:
        return None, None

    # 클릭 + 모달 대기
    for attempt in range(1, RETRY_MODAL + 2):
        disable_blocking_ui(page)
        if not click_safely(trigger):
            if attempt <= RETRY_MODAL:
                time.sleep(0.25); continue
            return None, None
        # 모달 대기
        try:
            modal = page.locator(".c-modal.is-active").first
            modal.wait_for(state="visible", timeout=MODAL_TIMEOUT_MS)
            # 모달 id
            mid = ""
            try:
                mid = modal.get_attribute("id") or ""
            except Exception:
                pass
            return modal, mid
        except PWTimeout:
            if attempt <= RETRY_MODAL:
                time.sleep(0.3)
                continue
            return None, None

def modal_html(modal: Locator) -> str:
    try:
        content = modal.locator(".c-modal__content")
        if content.count() > 0:
            return content.inner_html()
        return modal.inner_html()
    except Exception:
        try:
            return modal.inner_html()
        except Exception:
            return ""

def close_modal(page: Page):
    # 닫기 버튼 우선
    for sel in ["[data-dialog-close]", ".c-modal__close", "button:has-text('닫기')"]:
        btn = page.locator(f".c-modal.is-active {sel}").first
        if btn.count() > 0:
            try:
                btn.click()
                break
            except Exception:
                pass
    # ESC 폴백
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    # 사라질 때까지 잠깐 대기
    try:
        page.locator(".c-modal.is-active").first.wait_for(state="hidden", timeout=3000)
    except Exception:
        pass
    time.sleep(REQ_DELAY_SEC)

# ---- 적재기(JSONL/CSV) ----
class RowStore:
    def __init__(self, outdir: Path):
        self.outdir = outdir
        ensure_dirs(outdir)
        self.jsonl = outdir / "ktmmodal_rows.jsonl"
        self.csvf = outdir / "ktmmodal_rows.csv"
        self.seen = set()
        # 기존 로드
        if self.jsonl.exists():
            try:
                with self.jsonl.open("r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            obj = json.loads(line)
                            if "key" in obj:
                                self.seen.add(obj["key"])
                        except Exception:
                            continue
                print(f"{ts()} [INFO] 기존 JSONL 로드: {len(self.seen)} keys")
            except Exception:
                print(f"{ts()} [WARN] JSONL 로드 실패")
        # CSV 헤더
        if not self.csvf.exists():
            with self.csvf.open("w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow([
                    "site","main_tab","sub_tab","accordion","card_index","list_title",
                    "modal_id","modal_title","modal_price_text","modal_price",
                    "speed_toplist_modal","speed_dataguide_modal",
                    "modal_html_path","ts","key"
                ])

    def write_row(self, row: dict):
        key = row["key"]
        if key in self.seen:
            return
        # JSONL
        with self.jsonl.open("a", encoding="utf-8") as jf:
            jf.write(json.dumps(row, ensure_ascii=False) + "\n")
        # CSV
        with self.csvf.open("a", encoding="utf-8", newline="") as cf:
            w = csv.writer(cf)
            w.writerow([
                row.get("site",""), row.get("main_tab",""), row.get("sub_tab",""),
                row.get("accordion",""), row.get("card_index",""), row.get("list_title",""),
                row.get("modal_id",""), row.get("modal_title",""),
                row.get("modal_price_text",""), row.get("modal_price",""),
                row.get("speed_toplist_modal",""), row.get("speed_dataguide_modal",""),
                row.get("modal_html_path",""), row.get("ts",""), row.get("key","")
            ])
        self.seen.add(key)

# ---- 스캔(인덱스) & 파싱(실행) ----
def scan_accordion_index(page: Page, main_name: str, sub_name: str, panel: Locator) -> list[dict]:
    """
    현재 메인/서브탭 패널 안에서 아코디언 헤더를 순회하며
    [header_id, content_id, name, item_count]만 수집해서 리턴.
    """
    accs = accordion_headers(panel)
    print(f"{ts()}   [SCAN] {main_name} > {sub_name} : 아코디언 {len(accs)}개")

    index: list[dict] = []
    for acc in accs:
        acc_name = acc["name"]
        cont = open_accordion(panel, acc)
        if not cont:
            print(f"{ts()}     [SCAN-SKIP] 아코디언 열기 실패: {acc_name}")
            continue

        items = items_in_accordion(cont)
        n_items = len(items)
        print(f"{ts()}     [SCAN] [{acc_name}] 카드 {n_items}개")

        # 식별자(헤더 id, 컨텐트 id) 저장 → 2페이즈에서 재탐색에 사용
        header_id = ""
        try:
            header_id = acc["locator"].get_attribute("id") or ""
        except Exception:
            pass
        index.append({
            "main": main_name,
            "sub": sub_name,
            "accordion": acc_name,
            "header_id": header_id,
            "content_id": acc.get("content_id") or "",
            "count": n_items,
        })

    return index

def parse_from_index(page: Page, panel: Locator, index: list[dict],
                     store: "RowStore", max_per_tab: Optional[int]):
    """
    scan_accordion_index()에서 받은 구조를 바탕으로
    각 아코디언을 재탐색 → 아이템 모달 파싱.
    """
    for entry in index:
        main_name = entry["main"]
        sub_name  = entry["sub"]
        acc_name  = entry["accordion"]
        header_id = entry.get("header_id") or ""
        content_id = entry.get("content_id") or ""
        target_count = entry.get("count", 0)

        # 헤더 재탐색(우선 id → 없으면 텍스트 매칭)
        if header_id:
            h = panel.locator(f"#{header_id}")
            if h.count() == 0:
                h = panel.locator(".runtime-data-insert.c-accordion__button").filter(has_text=acc_name).first
        else:
            h = panel.locator(".runtime-data-insert.c-accordion__button").filter(has_text=acc_name).first

        if h.count() == 0:
            print(f"{ts()}     [SKIP] 헤더 재탐색 실패: {acc_name}")
            continue

        acc = {"name": acc_name, "locator": h, "content_id": content_id}
        cont = open_accordion(panel, acc)
        if not cont:
            print(f"{ts()}     [SKIP] 아코디언 열기 실패(2페이즈): {acc_name}")
            continue

        items = items_in_accordion(cont)
        n_items = len(items)
        if n_items == 0:
            print(f"{ts()}     - [{acc_name}] 카드 0개 (2페이즈)")
            continue

        # 스캔 결과와 다르면 로그만 — DOM 변동에 대응
        if target_count and target_count != n_items:
            print(f"{ts()}       [WARN] 스캔:{target_count} ↔ 재계산:{n_items} (변동 감지)")

        take_n = n_items if not max_per_tab else min(n_items, max_per_tab)
        print(f"{ts()}     - [{acc_name}] 모달 파싱 대상 {take_n}/{n_items}개")

        for idx in range(take_n):
            item = items[idx]
            list_title = ""
            try:
                ttl = item.locator(".rate-info__title, .rate-content__title, .title").first
                if ttl.count() > 0:
                    list_title = ttl.inner_text().strip()
            except Exception:
                pass

            modal, mid = open_modal_from_item(page, item)
            if not modal:
                print(f"{ts()}         [SKIP] 모달 실패: {main_name} > {sub_name} > {acc_name} #{idx+1}")
                continue

            html = modal_html(modal)
            fields = parse_modal_fields(html)

            # HTML 저장
            fname = f"{safe_filename(main_name)}__{safe_filename(sub_name)}__{safe_filename(acc_name)}__{idx+1:03d}.html"
            fpath = Path(store.outdir) / "html" / fname
            try:
                fpath.write_text(html, encoding="utf-8")
            except Exception:
                fpath = Path(store.outdir) / "html" / (safe_filename(fname) + f"_{int(time.time())}.html")
                fpath.write_text(html, encoding="utf-8")

            # 행 구성 + 즉시 적재
            row = {
                "site": "ktmmobile",
                "main_tab": main_name,
                "sub_tab": sub_name,
                "accordion": acc_name,
                "card_index": idx + 1,
                "list_title": list_title,
                "modal_id": mid or "",
                "modal_title": fields["modal_title"],
                "modal_price_text": fields["modal_price_text"],
                "modal_price": fields["modal_price"],
                "speed_toplist_modal": fields["speed_toplist_modal"],
                "speed_dataguide_modal": fields["speed_dataguide_modal"],
                "modal_html_path": str(fpath),
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            row["key"] = mk_key(
                row["site"], row["main_tab"], row["sub_tab"],
                row["accordion"], str(row["card_index"]),
                row["modal_title"], str(row["modal_price"])
            )
            store.write_row(row)
            print(f"{ts()}         [OK] 저장: {main_name} > {sub_name} > {acc_name} #{idx+1}")

            close_modal(page)  # 매너타임 포함

# ---- 파이프라인 ----
def run(url: str, headless: bool, slowmo: int, outdir: Path, max_per_tab: Optional[int], trace: bool):
    store = RowStore(outdir)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=slowmo)
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0.0.0 Safari/537.36"),
            accept_downloads=False,
        )
        if trace:
            ctx.tracing.start(screenshots=False, snapshots=True, sources=True)

        page = ctx.new_page()
        page.on("pageerror", lambda e: print(f"{ts()} [pageerror] {e}"))

        print(f"{ts()} [INFO] 이동: {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=70000)
        page.wait_for_timeout(800)

        # 메인탭 수집
        tabs = main_tabs(page)
        names = [t["name"] for t in tabs]
        print(f"{ts()} [TABS] 메인탭: {names if names else '없음'}")

        for mt in tabs:
            main_name = mt["name"]
            print(f"\n{ts()} [STEP] 메인탭: {main_name}")
            disable_blocking_ui(page)
            if not open_main_tab(page, mt):
                # 패널 준비 실패 -> 한번 새로고침 후 재시도
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(600)
                disable_blocking_ui(page)
                if not open_main_tab(page, mt):
                    print(f"{ts()} [WARN] 메인탭 준비 실패: {main_name}")
                    continue

            # 서브탭 수집(메인패널 스코프)
            subs = subtabs_in_main_panel(page, mt["panel_id"])
            if not subs:
                # 서브탭이 없으면 현재 패널 하나만 처리(- 로 명시)
                subs = [{"name": "-", "locator": page.locator("body"), "panel_id": mt["panel_id"]}]

            for st in subs:
                sub_name = st["name"]
                if sub_name != "-":
                    ok, panel = open_subtab(page, mt["panel_id"], st)
                    if not ok:
                        # 환기 + 재시도
                        page.reload(wait_until="domcontentloaded")
                        page.wait_for_timeout(600)
                        disable_blocking_ui(page)
                        ok, panel = open_subtab(page, mt["panel_id"], st)
                        if not ok:
                            print(f"{ts()} [WARN] 패널 준비 미확인: {main_name} > {sub_name}")
                            continue
                else:
                    # 서브탭 없음: 메인 패널을 그대로 사용
                    panel = page.locator(f'#{mt["panel_id"]}') if mt["panel_id"] else page.locator("[role=tabpanel]").first
                    if not wait_panel_ready(panel):
                        print(f"{ts()} [WARN] 패널 준비 미확인: {main_name} > {sub_name}")
                        continue

                # ---- 2-페이즈: 스캔 → 파싱 ----
                acc_index = scan_accordion_index(page, main_name, sub_name, panel)
                parse_from_index(page, panel, acc_index, store, max_per_tab)

        if trace:
            tr = outdir / "trace.zip"
            try:
                ctx.tracing.stop(path=str(tr))
                print(f"{ts()} [TRACE] {tr} 저장됨")
            except Exception:
                pass

        ctx.close()
        browser.close()
        print(f"{ts()} [DONE] 수집 완료")
        print(f"- JSONL: {store.jsonl}")
        print(f"- CSV  : {store.csvf}")
        print(f"- HTML : {outdir/'html'}")

# ---- 엔트리 ----
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--slowmo", type=int, default=0)
    ap.add_argument("--outdir", default="ktmm_out_seq")
    ap.add_argument("--max-per-tab", type=int, default=None)
    ap.add_argument("--trace", action="store_true")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    run(
        url=args.url,
        headless=args.headless,
        slowmo=args.slowmo,
        outdir=outdir,
        max_per_tab=args.max_per_tab,
        trace=args.trace,
    )
