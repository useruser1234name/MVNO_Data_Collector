# -*- coding: utf-8 -*-
"""
KT M모바일 동적 수집기 v2.2 (상단 탭 + 서브탭 + 아코디언 + 모달 전체 저장)
- 대상: https://www.ktmmobile.com/rate/rateList.do

개정 포인트
* 상세 모달(#modalProduct)만 수집 (ARS/비교함 등 다른 모달은 즉시 닫기)
* 플로팅 '요금제 비교함' 등 가리는 UI는 pointer-events 비활성화
* 현재 보이는 탭패널 안에서만 LTE/5G 서브탭 순회
* wait_for_function 제거, selector 기반 대기만 사용
"""

import argparse
import csv
import json
import re
import time
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout, Page

DEFAULT_URL = "https://www.ktmmobile.com/rate/rateList.do"
REQUEST_INTERVAL_SEC = 0.35
VER = "v2.2"

# -------------------- 유틸 --------------------
def ts() -> str:
    return time.strftime("[%H:%M:%S]")

def norm(s: str | None) -> str | None:
    if not s:
        return None
    return re.sub(r"\s+", " ", s).strip()

def money(s: str | None) -> int | None:
    if not s:
        return None
    m = re.findall(r"\d+", s.replace(",", ""))
    return int("".join(m)) if m else None

def direct_text(el) -> str:
    if not el:
        return ""
    return "".join(el.find_all(string=True, recursive=False)).strip()

def safe_filename(name: str, maxlen: int = 90) -> str:
    name = re.sub(r"[\\/:*?\"<>|\s]+", "_", name).strip("_")
    return name[:maxlen] or "item"

def ensure_dirs(base: Path):
    (base / "screens").mkdir(parents=True, exist_ok=True)
    (base / "modals").mkdir(parents=True, exist_ok=True)
    (base / "html").mkdir(parents=True, exist_ok=True)
    (base / "logs").mkdir(parents=True, exist_ok=True)

# -------------------- Mbps 추출 --------------------
def extract_mbps_lines_from_modal(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """(상단요약의 Mbps 라인들 | '데이터 이용 안내' 섹션의 Mbps 라인들)"""
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
    title = None
    t = soup.select_one("#modalProductTitle, .c-modal__title")
    if t:
        title = norm(t.get_text(strip=True))

    price_text = None
    p = soup.select_one(".product-detail__price, .product-detail__price-wrap, .u-co-red, .u-co-black")
    if p:
        price_text = norm(p.get_text(" ", strip=True))
    price_num = money(price_text)
    speed_top, speed_guide = extract_mbps_lines_from_modal(soup)

    return {
        "modal_title": title,
        "modal_price_text": price_text,
        "modal_price": price_num,
        "speed_toplist_modal": speed_top,
        "speed_dataguide_modal": speed_guide,
    }

def parse_modal_all(modal_html: str) -> dict:
    """모달의 광범위한 정보를 JSON 문자열 컬럼들로 구성."""
    soup = BeautifulSoup(modal_html, "lxml")
    root = soup.select_one(".c-modal__content, .c-modal__body, .c-modal__dialog") or soup

    def jdump(obj) -> str:
        try:
            return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return ""

    def t(el) -> str:
        try:
            return norm(" ".join(el.stripped_strings)) or ""
        except Exception:
            return ""

    # 1) 전체 텍스트
    modal_text_all = t(root)

    # 2) 섹션(헤딩별 블록) 추출
    sections = []
    try:
        headings = root.select("h1, h2, h3, h4, h5, h6")
        for h in headings:
            title = h.get_text(strip=True)
            body_parts = []
            for sib in h.next_siblings:
                # 다음 헤딩 만나면 종료
                if getattr(sib, "name", None) in {"h1","h2","h3","h4","h5","h6"}:
                    break
                if getattr(sib, "name", None) in {"script", "style"}:
                    continue
                body_parts.append(t(sib) if hasattr(sib, "stripped_strings") else norm(str(sib)))
            body = norm(" ".join([x for x in body_parts if x])) or ""
            if title or body:
                sections.append({"title": title, "body": body})
    except Exception:
        pass

    # 3) DL 목록들
    dl_blocks = []
    try:
        for dl in root.select("dl"):
            pairs = []
            dts = dl.find_all("dt")
            dds = dl.find_all("dd")
            # dt/dd 페어링(개수가 다르면 가능한 범위만)
            m = min(len(dts), len(dds))
            for i in range(m):
                k = t(dts[i])
                v = t(dds[i])
                if k or v:
                    pairs.append({"key": k, "value": v})
            if pairs:
                dl_blocks.append(pairs)
    except Exception:
        pass

    # 4) 표
    tables = []
    try:
        for tbl in root.select("table"):
            headers = []
            head = tbl.find("thead")
            if head:
                ths = head.find_all(["th", "td"]) or []
                headers = [t(c) for c in ths]
            if not headers:
                first_tr = tbl.find("tr")
                if first_tr:
                    headers = [t(c) for c in first_tr.find_all(["th", "td"]) or []]
            rows = []
            for tr in tbl.find_all("tr"):
                cells = tr.find_all(["th", "td"]) or []
                row = [t(c) for c in cells]
                if any(row):
                    rows.append(row)
            if rows:
                tables.append({"headers": headers, "rows": rows})
    except Exception:
        pass

    # 5) 링크
    links = []
    try:
        for a in root.select("a[href]"):
            href = a.get("href")
            txt = t(a)
            if href or txt:
                links.append({"text": txt, "href": href})
    except Exception:
        pass

    # 6) 불릿/번호 목록
    bullets = []
    try:
        for ul in root.select("ul, ol"):
            items = []
            for li in ul.find_all("li"):
                items.append(t(li))
            if any(items):
                bullets.append(items)
    except Exception:
        pass

    return {
        "modal_text_all": modal_text_all,
        "modal_sections_json": jdump(sections),
        "modal_dl_json": jdump(dl_blocks),
        "modal_tables_json": jdump(tables),
        "modal_links_json": jdump(links),
        "modal_bullets_json": jdump(bullets),
    }

# -------------------- 공용 액션 --------------------
def log_requestfailed(r, log_path: Path | None = None):
    try:
        # playwright 1.45+ : r.failure()가 문자열일 수 있음
        fail = r.failure
        msg = getattr(fail, "error_text", "") if hasattr(fail, "error_text") else (fail or "")
        line = f"{ts()} [requestfailed] {r.method} {r.url} -> {msg}"
        print(line)
        if log_path:
            try:
                log_path.write_text((log_path.read_text(encoding="utf-8") if log_path.exists() else "") + line + "\n", encoding="utf-8")
            except Exception:
                pass
    except Exception:
        line = f"{ts()} [requestfailed] {getattr(r,'method','?')} {getattr(r,'url','?')}"
        print(line)
        if log_path:
            try:
                log_path.write_text((log_path.read_text(encoding="utf-8") if log_path.exists() else "") + line + "\n", encoding="utf-8")
            except Exception:
                pass

def append_log(log_path: Path, message: str):
    try:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(message + "\n")
    except Exception:
        pass

def make_console_logger(log_path: Path):
    def _logger(m):
        line = f"{ts()} [console:{m.type}] {m.text}"
        print(line)
        append_log(log_path, line)
    return _logger

def make_pageerror_logger(log_path: Path):
    def _logger(e):
        line = f"{ts()} [pageerror] {e}"
        print(line)
        append_log(log_path, line)
    return _logger

def make_requestfailed_logger(log_path: Path):
    return lambda r: log_requestfailed(r, log_path)

def make_response_logger(log_path: Path):
    def _logger(resp):
        try:
            status = resp.status
            if status >= 400:
                line = f"{ts()} [response:{status}] {resp.request.method} {resp.url}"
                print(line)
                append_log(log_path, line)
        except Exception:
            pass
    return _logger

def close_all_modals(page: Page, timeout_ms: int = 2500):
    """열려있는 모달(ARIA dialog 및 .c-modal)을 닫는다."""
    for _ in range(3):
        active_any = page.locator("dialog, [role='dialog'], .c-modal.is-active")
        # 모두 숨겨졌으면 종료
        try:
            visible_count = 0
            for i in range(min(8, active_any.count())):
                try:
                    if active_any.nth(i).is_visible():
                        visible_count += 1
                except Exception:
                    pass
            if visible_count == 0:
                break
        except Exception:
            pass

        # 닫기 버튼 먼저 (dialog와 .c-modal 모두 대상)
        for sel in [
            "dialog [data-dialog-close]",
            "dialog .c-modal__close",
            "dialog button:has-text('닫기')",
            "dialog button:has-text('팝업닫기')",
            ".c-modal.is-active [data-dialog-close]",
            ".c-modal.is-active .c-modal__close",
            ".c-modal.is-active button:has-text('닫기')",
            ".c-modal.is-active button:has-text('팝업닫기')",
        ]:
            btn = page.locator(sel)
            if btn.count() > 0:
                try:
                    btn.first.click()
                    page.wait_for_timeout(120)
                except Exception:
                    pass
        # ESC 키
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        # 사라질 때까지 조금 기다림
        try:
            page.locator("dialog, [role='dialog'], .c-modal.is-active").first.wait_for(state="hidden", timeout=timeout_ms)
        except Exception:
            pass

def disable_blocking_ui(page: Page):
    """클릭을 가리는 비교함/플로팅 UI를 일시적으로 무력화"""
    js = """
    for (const sel of [
      '#pullProductCompare', '.rate-compare__floating', '.floating-compare',
      'button:has-text("요금제 비교함")', '.btn-compare', '.compare'
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

def click_and_wait_modal(page: Page, link_locator, target: str, open_timeout: int = 14000):
    """카드의 상세 트리거를 클릭하고 실제 떠 있는 모달(dialog/.c-modal)을 대기."""
    disable_blocking_ui(page)
    # 겹침 방지: 살짝 위로
    try:
        link_locator.scroll_into_view_if_needed()
    except Exception:
        pass
    page.mouse.wheel(0, -200)
    page.wait_for_timeout(100)
    link_locator.click(force=True)

    # 1차: 명시적 target(.is-active) 시도
    try:
        page.locator(f"{target}.is-active").wait_for(state="visible", timeout=int(open_timeout * 0.5))
        return page.locator(target)
    except Exception:
        pass

    # 2차: target 내부 컨텐츠 시도
    try:
        page.locator(f"{target} .c-modal__dialog, {target} .c-modal__content, {target} [role='document']").first.wait_for(
            state="visible", timeout=int(open_timeout * 0.6)
        )
        return page.locator(target)
    except Exception:
        pass

    # 3차: 실제로 보이는 dialog/.c-modal 감지
    for sel in [
        "dialog[open]",
        "[role='dialog']:not([aria-hidden='true'])",
        ".c-modal.is-active",
        "dialog",
        "[role='dialog']",
    ]:
        try:
            loc = page.locator(sel)
            # 가시성 판단
            for i in range(min(6, loc.count())):
                el = loc.nth(i)
                try:
                    el.wait_for(state="visible", timeout=int(open_timeout * 0.6))
                    return el
                except Exception:
                    continue
        except Exception:
            continue
    # 실패 시 target 반환(후속 로직에서 inner_html 시도)
    return page.locator(target)

def expand_modal_content(page: Page, modal_el):
    # 아코디언 등 펼칠 수 있는 컨트롤 시도
    try:
        for _ in range(2):
            acc = modal_el.locator(".c-accordion__button")
            for i in range(acc.count()):
                try:
                    btn = acc.nth(i)
                    aria = (btn.get_attribute("aria-expanded") or "").lower()
                    if aria != "true":
                        btn.click()
                        page.wait_for_timeout(100)
                except Exception:
                    pass
    except Exception:
        pass
    # 스크롤로 지연 로드 유도
    try:
        content = modal_el.locator(".c-modal__content, .c-modal__body, .c-modal__dialog").first
        if content.count() > 0:
            try:
                content.evaluate("el => { el.scrollTop = 0; el.scrollTo(0, el.scrollHeight); }")
            except Exception:
                for _ in range(6):
                    page.mouse.wheel(0, 600)
                    page.wait_for_timeout(60)
    except Exception:
        pass

# -------------------- 크롤링 본체 --------------------
def run(url: str, headless: bool, slowmo: int, outdir: Path, max_per_tab: int | None, trace: bool):
    ensure_dirs(outdir)
    out_csv = outdir / "ktmmobile_modal_data.csv"
    log_file = outdir / "logs" / "playwright_activity.log"
    if not out_csv.exists():
        with out_csv.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "site","tab_name","subtab_name","card_index","list_title",
                "modal_title","modal_price_text","modal_price",
                "speed_toplist_modal","speed_dataguide_modal",
                "modal_html_path","modal_png_path",
                "modal_text_all","modal_sections_json","modal_dl_json","modal_tables_json","modal_links_json","modal_bullets_json"
            ])

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
            ctx.tracing.start(screenshots=True, snapshots=True, sources=True)

        page = ctx.new_page()
        page.on("console", make_console_logger(log_file))
        page.on("pageerror", make_pageerror_logger(log_file))
        page.on("requestfailed", make_requestfailed_logger(log_file))
        page.on("response", make_response_logger(log_file))

        print(f"{ts()} [VER] ktmmobile_modal_scrape {VER}")
        print(f"{ts()} [INFO] 이동: {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=70000)
        # 초기 로딩 후 약간의 유예 + 스샷
        try:
            page.wait_for_selector("li.rate-content__item", timeout=15000)
        except Exception:
            pass
        page.screenshot(path=str(outdir / "screens" / "00_loaded.png"))

        # 상단(큰) 탭 후보를 텍스트로 확정
        top_targets = ["유심/eSIM 요금제", "제휴 요금제", "휴대폰 요금제"]
        found_top = []
        for t in top_targets:
            if page.locator("button.c-tabs__button", has_text=t).count() > 0:
                found_top.append(t)
        if not found_top:
            # 혹시 줄바꿈/공백 등으로 매칭 실패할 경우 모든 버튼에서 유사 텍스트 추출
            btns = page.locator("button.c-tabs__button")
            for i in range(btns.count()):
                try:
                    txt = btns.nth(i).inner_text().strip()
                    if any(key in txt for key in ["유심/eSIM", "제휴 요금제", "휴대폰 요금제"]):
                        if txt not in found_top:
                            found_top.append(txt)
                except Exception:
                    pass
        if not found_top:
            found_top = top_targets

        print(f"{ts()} [INFO] 탐색 탭: {found_top}")

        def iterate_cards(tab_name: str, subtab_name: str | None):
            # 아코디언 전부 펼치기
            for _ in range(2):  # 2회 패스(첫 클릭으로 DOM이 추가되는 경우)
                acc = page.locator(".c-accordion__button")
                for i in range(acc.count()):
                    try:
                        btn = acc.nth(i)
                        aria = (btn.get_attribute("aria-expanded") or "").lower()
                        if aria != "true":
                            btn.click()
                            page.wait_for_timeout(120)
                    except Exception:
                        pass

            # 더보기/무한로딩 시도
            for _ in range(24):
                clicked = False
                for sel in [".c-pagination__more", ".btn-more", "button:has-text('더보기')"]:
                    btn = page.locator(sel).first
                    if btn.count() > 0 and btn.is_enabled():
                        try:
                            btn.scroll_into_view_if_needed()
                            btn.click()
                            page.wait_for_timeout(450)
                            clicked = True
                        except Exception:
                            pass
                if not clicked:
                    break

            # 늦게 로드되는 카드까지 노출
            for _ in range(12):
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(120)

            cards = page.locator("li.rate-content__item")
            n = cards.count()
            print(f"{ts()} [INFO] 카드 개수: {n}")
            take_n = n if not max_per_tab else min(n, max_per_tab)

            for i in range(take_n):
                print(f"{ts()}   - 카드 #{i+1}/{take_n}")
                card = cards.nth(i)

                # 리스트 타이틀
                list_title = None
                try:
                    list_title = norm(card.locator(".rate-info__title, .rate-content__title, .title").first.inner_text())
                except Exception:
                    pass

                # 상세 모달 트리거(오직 modalProduct)
                triggers = []
                for sel in [
                    "a[data-dialog-target*='modalProduct']",
                    "a[data-dialog-trigger*='modalProduct']",
                    "button[data-dialog-target*='modalProduct']",
                    "button[data-dialog-trigger*='modalProduct']",
                ]:
                    loc = card.locator(sel)
                    if loc.count() > 0:
                        triggers.append(loc.first)

                if not triggers:
                    print(f"{ts()}     [SKIP] 상세 모달 트리거 없음(modalProduct)")
                    continue

                close_all_modals(page)
                disable_blocking_ui(page)

                ok = False
                for link in triggers:
                    target = link.get_attribute("data-dialog-target") or link.get_attribute("data-dialog-trigger") or "#modalProduct"
                    target = ("#" + target) if target and not target.startswith("#") else (target or "#modalProduct")
                    print(f"{ts()}     - 모달 트리거 클릭: target='{target}'")

                    try:
                        modal_el = click_and_wait_modal(page, link, target, open_timeout=10000)
                    except Exception as e:
                        print(f"{ts()}     [WARN] 모달 오픈 실패: {e}")
                        close_all_modals(page)
                        continue

                    # 만약 다른 모달(id != modalProduct)이면 닫고 다음 트리거 시도
                    try:
                        root_id = modal_el.first.get_attribute("id") or ""
                        if root_id and root_id != "modalProduct":
                            print(f"{ts()}     [INFO] 대상외 모달('{root_id}') -> 닫고 다음 트리거 시도")
                            close_all_modals(page)
                            continue
                    except Exception:
                        pass

                    # HTML 추출 전 모달 내부 확장/로드 유도
                    try:
                        expand_modal_content(page, modal_el)
                    except Exception:
                        pass

                    # HTML 추출
                    try:
                        content = modal_el.locator(".c-modal__content, .c-modal__body, [role='document'], .c-modal__dialog")
                        html = content.inner_html() if content.count() > 0 else modal_el.inner_html()
                    except Exception:
                        html = modal_el.inner_html()

                    # 스크린샷/저장
                    base_name = list_title or f"{tab_name}_{subtab_name or 'default'}_{i+1:03d}"
                    modal_png = outdir / "modals" / f"{safe_filename(base_name)}.png"
                    try:
                        modal_el.screenshot(path=str(modal_png))
                    except Exception:
                        page.screenshot(path=str(outdir / "screens" / f"{safe_filename(base_name)}_page.png"))

                    modal_html_path = outdir / "html" / f"{safe_filename(base_name)}.html"
                    try:
                        modal_html_path.write_text(html, encoding="utf-8")
                    except Exception:
                        alt = outdir / "html" / f"{safe_filename(base_name)}_{int(time.time())}.html"
                        alt.write_text(html, encoding="utf-8")
                        modal_html_path = alt

                    # 파싱 & CSV
                    fields = parse_modal_fields(html)
                    ext = parse_modal_all(html)
                    with out_csv.open("a", encoding="utf-8", newline="") as f:
                        w = csv.writer(f)
                        w.writerow([
                            "ktmmobile",
                            tab_name,
                            subtab_name or "",
                            i + 1,
                            list_title or "",
                            fields.get("modal_title") or "",
                            fields.get("modal_price_text") or "",
                            fields.get("modal_price") or "",
                            fields.get("speed_toplist_modal") or "",
                            fields.get("speed_dataguide_modal") or "",
                            str(modal_html_path),
                            str(modal_png),
                            ext.get("modal_text_all") or "",
                            ext.get("modal_sections_json") or "",
                            ext.get("modal_dl_json") or "",
                            ext.get("modal_tables_json") or "",
                            ext.get("modal_links_json") or "",
                            ext.get("modal_bullets_json") or "",
                        ])

                    ok = True
                    close_all_modals(page)
                    time.sleep(REQUEST_INTERVAL_SEC)
                    break  # 해당 카드 수집 완료

                if not ok:
                    print(f"{ts()}     [SKIP] 카드 #{i+1}: modalProduct 수집 실패")

        # 상단 탭 순회
        for tab_name in found_top:
            print(f"\n{ts()} [STEP] 탭 선택: {tab_name}")
            try:
                close_all_modals(page)
                page.locator("button.c-tabs__button", has_text=tab_name).first.click()
                page.wait_for_timeout(250)
            except Exception as e:
                print(f"{ts()} [WARN] 탭 클릭 오류({tab_name}): {e}")

            # 현재 표시중인 탭패널에서 서브탭(LTE/5G)만 추출
            sub_candidates = []
            try:
                visible_panel = page.locator("[role='tabpanel']").filter(has_not_text="aria-hidden=\"true\"")
                # 보이는 패널이 명확하지 않으면 전체에서 'LTE','5G' 텍스트 버튼을 추림
                btns = visible_panel.locator("button.c-tabs__button")
                if btns.count() == 0:
                    btns = page.locator("button.c-tabs__button")
                for i in range(btns.count()):
                    try:
                        t = btns.nth(i).inner_text().strip()
                        if any(key in t for key in ["LTE", "5G"]):
                            if t not in sub_candidates:
                                sub_candidates.append(t)
                    except Exception:
                        pass
            except Exception:
                pass

            if not sub_candidates:
                # 서브탭 없음
                iterate_cards(tab_name, None)
            else:
                for sub_t in sub_candidates:
                    try:
                        close_all_modals(page)
                        page.locator("button.c-tabs__button", has_text=sub_t).first.click()
                        page.wait_for_timeout(250)
                    except Exception:
                        pass
                    iterate_cards(tab_name, sub_t)

        if trace:
            trace_path = outdir / "trace.zip"
            ctx.tracing.stop(path=str(trace_path))
            print(f"{ts()} [TRACE] {trace_path} 저장됨 (playwright show-trace '{trace_path}')")

        ctx.close()
        browser.close()
        print(f"\n{ts()} [완료] CSV: {out_csv}\n- 모달 HTML: {outdir/'html'}\n- 스샷: {outdir/'modals'} / {outdir/'screens'}")

# -------------------- 엔트리 --------------------
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL, help="시작 URL")
    ap.add_argument("--headless", action="store_true", help="헤드리스 모드(창 안 띄움)")
    ap.add_argument("--slowmo", type=int, default=0, help="동작을 느리게(ms)")
    ap.add_argument("--outdir", default=None, help="출력 폴더(기본: 스크립트 폴더 'KT_MMobile')")
    ap.add_argument("--max-per-tab", type=int, default=None, help="탭당 최대 카드 수 (디버그용 제한)")
    ap.add_argument("--trace", action="store_true", help="Playwright trace 저장")
    args = ap.parse_args()

    outdir = Path(args.outdir) if args.outdir else Path(__file__).resolve().parent
    outdir.mkdir(parents=True, exist_ok=True)

    run(
        url=args.url,
        headless=args.headless,
        slowmo=args.slowmo,
        outdir=outdir,
        max_per_tab=args.max_per_tab,
        trace=args.trace,
    )
