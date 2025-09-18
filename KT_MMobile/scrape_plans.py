# scrape_plans.py
# 사용법:
#   python scrape_plans.py --url https://example.com
# 옵션 예:
#   python scrape_plans.py --url https://example.com --headless --appear 5000 --open 7000 --close 5000
#   python scrape_plans.py --url https://example.com --main-tab "유심/eSIM 요금제" --main-tab "제휴 요금제" --sub-tab-map "유심/eSIM 요금제=LTE 요금제,5G 요금제"

import json
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Any

from playwright.sync_api import sync_playwright, expect, Page


def parse_args():
    p = argparse.ArgumentParser(description="요금제 팝업 수집기 (Playwright Python)")
    p.add_argument("--url", required=True, help="대상 URL")
    p.add_argument("--headless", action="store_true", help="헤드리스 실행")
    p.add_argument("--slowmo", type=int, default=0, help="슬로우 모(ms)")
    p.add_argument("--output", default="plans.json", help="결과 저장 경로(파일명)")
    p.add_argument("--main-tab", action="append", default=[], help="처리할 메인 탭 이름(여러 번 지정 가능)")
    p.add_argument(
        "--sub-tab-map",
        action="append",
        default=[],
        help='메인탭과 서브탭 매핑. 예: "유심/eSIM 요금제=LTE 요금제,5G 요금제" (여러 번 지정 가능)',
    )

    # 타임아웃(ms)
    p.add_argument("--appear", type=int, default=5000, help="등장 대기 타임아웃(ms)")
    p.add_argument("--open", type=int, default=5000, help="팝업 열림 대기 타임아웃(ms)")
    p.add_argument("--close", type=int, default=5000, help="팝업 닫힘 대기 타임아웃(ms)")

    # 선택자 커스텀
    p.add_argument("--tablist", default='[role="tablist"]', help="메인 탭리스트 선택자")
    p.add_argument("--subtab-list", default="#subTabPanel", help="서브탭 컨테이너 선택자")
    p.add_argument("--accordion-scope", default=".c-accordion__panel.expand.expanded", help="아코디언 스코프 선택자")
    p.add_argument("--accordion-btn", default="button.runtime-data-insert.c-accordion__button", help="아코디언 버튼 선택자")
    p.add_argument("--rate-list", default=".rate-content__list", help="요금제 리스트 컨테이너 선택자")
    p.add_argument("--rate-item", default=".rate-content-wrap", help="요금제 아이템 선택자")
    p.add_argument("--modal-title", default="#modalProductTitle", help="팝업 타이틀 선택자")
    p.add_argument("--modal-close", default='button.c-button[data-dialog-close]', help="팝업 닫기 버튼 선택자")

    return p.parse_args()


def parse_sub_tab_map(entries: List[str]) -> Dict[str, List[str]]:
    """
    "메인=서브1,서브2" 형식들을 파싱해서 dict로 반환
    """
    mapping: Dict[str, List[str]] = {}
    for ent in entries:
        if "=" not in ent:
            continue
        main, subs = ent.split("=", 1)
        main = main.strip()
        subs_list = [s.strip() for s in subs.split(",") if s.strip()]
        if main:
            mapping[main] = subs_list
    return mapping


def select_tab_by_name(page: Page, tablist_selector: str, name: str, appear: int):
    tablist = page.locator(tablist_selector).first
    expect(tablist).to_be_visible(timeout=appear)
    tab = tablist.get_by_role("tab", name=name)
    tab.click()
    expect(tab).to_have_attribute("aria-selected", "true", timeout=appear)
    return tab


def pick_sub_tabs(page: Page, subtab_list_selector: str, appear: int, names: Optional[List[str]] = None) -> List[Optional[str]]:
    """
    서브탭이 있을 수도/없을 수도 있으므로:
    - 존재하지 않거나 비어 있으면 [None] 반환 (서브탭 단계 skip)
    - names가 주어지면 그대로 반환
    - 없으면 현재 선택된 서브탭 1개(없으면 첫 번째)만 반환
    """
    sub_list = page.locator(subtab_list_selector).first()
    if sub_list.count() == 0:
        return [None]

    sub_tabs = sub_list.get_by_role("tab")
    count = sub_tabs.count()
    if count == 0:
        return [None]

    if names:
        return names

    selected = sub_tabs.filter(has=page.locator('[aria-selected="true"]'))
    if selected.count() > 0:
        sel_name = selected.nth(0).inner_text().strip()
        return [sel_name]

    first_name = sub_tabs.nth(0).inner_text().strip()
    return [first_name]


def collect_all_plans(
    page: Page,
    *,
    main_tabs: List[str],
    sub_tabs_by_main: Dict[str, List[str]],
    selectors: Dict[str, str],
    timeouts: Dict[str, int],
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    tablist = selectors["tablist"]
    subtab_list = selectors["subtab_list"]
    accordion_scope_sel = selectors["accordion_scope"]
    accordion_btn_sel = selectors["accordion_btn"]
    rate_list_sel = selectors["rate_list"]
    rate_item_sel = selectors["rate_item"]
    modal_title_sel = selectors["modal_title"]
    modal_close_sel = selectors["modal_close"]

    appear = timeouts["appear"]
    open_to = timeouts["open"]
    close_to = timeouts["close"]

    # 메인 탭 후보 결정: 지정 없으면 현재 선택된 탭 또는 첫 번째 탭
    main_tablist = page.locator(tablist).first
    expect(main_tablist).to_be_visible(timeout=appear)

    if not main_tabs:
        selected = main_tablist.get_by_role("tab", selected=True)
        if selected.count() > 0:
            main_tabs = [selected.nth(0).inner_text().strip()]
        else:
            main_tabs = [main_tablist.get_by_role("tab").nth(0).inner_text().strip()]

    for main_name in main_tabs:
        # 메인 탭 선택
        select_tab_by_name(page, tablist, main_name, appear)

        # 서브탭 후보
        sub_candidates = pick_sub_tabs(page, subtab_list, appear, sub_tabs_by_main.get(main_name))

        for sub_name in sub_candidates:
            if sub_name:
                sub_list = page.locator(subtab_list).first()
                sub_tab = sub_list.get_by_role("tab", name=sub_name)
                sub_tab.click()
                expect(sub_tab).to_have_attribute("aria-selected", "true", timeout=appear)

            # 아코디언 스코프 (없으면 전체에서 버튼 검색)
            scope = page.locator(accordion_scope_sel).first()
            acc_buttons = scope.locator(accordion_btn_sel) if scope.count() > 0 else page.locator(accordion_btn_sel)
            acc_count = acc_buttons.count()

            # 아코디언이 없다면 한 번만 리스트를 훑음
            for a_idx in range(max(1, acc_count)):
                acc = acc_buttons.nth(a_idx) if acc_count > 0 else None
                if acc:
                    acc.scroll_into_view_if_needed()
                    was_expanded = acc.get_attribute("aria-expanded") == "true"
                    if not was_expanded:
                        acc.click()
                        expect(acc).to_have_attribute("aria-expanded", "true", timeout=appear)

                # 리스트
                container = page.locator(rate_list_sel).first()
                if container.count() == 0:
                    continue
                expect(container).to_be_visible(timeout=appear)

                total = container.locator(rate_item_sel).count()
                i = 0
                while i < total:
                    items = container.locator(rate_item_sel)  # re-query
                    item = items.nth(i)

                    item.scroll_into_view_if_needed()
                    item.click()

                    # 팝업 열림/수집
                    title_loc = page.locator(modal_title_sel)
                    expect(title_loc).to_be_visible(timeout=open_to)
                    title = title_loc.inner_text().strip()

                    results.append(
                        {
                            "mainTab": main_name,
                            "subTab": sub_name if sub_name else None,
                            "accordionIndex": a_idx if acc else None,
                            "indexInList": i,
                            "title": title,
                        }
                    )

                    # 닫기
                    close_btn = page.locator(modal_close_sel)
                    expect(close_btn).to_be_visible(timeout=appear)
                    close_btn.click()
                    expect(title_loc).to_be_hidden(timeout=close_to)

                    # DOM 갱신 대응
                    total = container.locator(rate_item_sel).count()
                    i += 1

    return results


def main():
    args = parse_args()

    # 서브탭 매핑 파싱
    sub_tabs_by_main = parse_sub_tab_map(args.sub_tab_map)

    # 선택자/타임아웃 dict 준비
    selectors = {
        "tablist": args.tablist,
        "subtab_list": args.subtab_list,
        "accordion_scope": args.accordion_scope,
        "accordion_btn": args.accordion_btn,
        "rate_list": args.rate_list,
        "rate_item": args.rate_item,
        "modal_title": args.modal_title,
        "modal_close": args.modal_close,
    }
    timeouts = {"appear": args.appear, "open": args.open, "close": args.close}

    output_path = Path(args.output)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless, slow_mo=args.slowmo)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(args.url, wait_until="domcontentloaded")

            data = collect_all_plans(
                page,
                main_tabs=args.main_tab,
                sub_tabs_by_main=sub_tabs_by_main,
                selectors=selectors,
                timeouts=timeouts,
            )

            output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"✅ 수집 완료: {len(data)}건")
            print(f"📄 저장: {output_path.resolve()}")
        except Exception as e:
            print("❌ 에러:", e)
            raise
        finally:
            browser.close()


if __name__ == "__main__":
    main()
