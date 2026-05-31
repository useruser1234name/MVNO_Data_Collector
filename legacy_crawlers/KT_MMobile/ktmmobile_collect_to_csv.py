# -*- coding: utf-8 -*-
"""
KT M모바일 요금제 모달 수집 → CSV 저장 스크립트 (Playwright, 동기 API)

사용법 예시:
    python -m KT_MMobile.ktmmobile_collect_to_csv --headless --slowmo 0 \
        --output ktmm_out/ktmmobile_modal_data.csv

필요 패키지:
    pip install playwright
    playwright install chromium
"""

from __future__ import annotations

import csv
import hashlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.sync_api import Page, expect, sync_playwright


URL = "https://www.ktmmobile.com/rate/rateList.do"
VENDOR = "KT M mobile"


# ----------------------------- 유틸리티 -----------------------------

def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def text_to_int_money(text: str) -> Optional[int]:
    t = text.replace(",", "")
    # 만원 표기
    m = re.search(r"(\d+)\s*만\s*원", t)
    if m:
        try:
            return int(m.group(1)) * 10000
        except Exception:
            return None
    # 원 단위 숫자
    m = re.search(r"(\d{1,3}(?:\d{3})+|\d+)\s*원", t)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    # 숫자만 있을 때 (보수적)
    m = re.search(r"\b(\d{4,6})\b", t)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None


def normalize_data_allowance(text: str) -> Optional[int]:
    t = text.replace(",", "").lower()
    if "무제한" in t:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*gb", t)
    if m:
        gb = float(m.group(1))
        return int(round(gb * 1024))
    m = re.search(r"(\d+(?:\.\d+)?)\s*mb", t)
    if m:
        mb = float(m.group(1))
        return int(round(mb))
    return None


def extract_minutes(text: str) -> Optional[int]:
    t = text.replace(",", "")
    if "무제한" in t:
        return None
    m = re.search(r"(\d+)\s*분", t)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None


def extract_sms_count(text: str) -> Optional[int]:
    t = text.replace(",", "")
    if "무제한" in t:
        return None
    m = re.search(r"(\d+)\s*(건|sms)", t, re.I)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None


def make_plan_id(name: str, monthly_fee: Optional[int], network_type: Optional[str]) -> str:
    base = f"{name}|{monthly_fee or 0}|{network_type or ''}"
    return "ktmm-" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


# ----------------------------- 모달 파싱 -----------------------------

@dataclass
class ParsedPlan:
    name: str
    monthly_fee: Optional[int]
    data_allowance_mb: Optional[int]
    voice_minutes: Optional[int]
    sms_count: Optional[int]
    network_type: Optional[str]
    promotion: Optional[str]
    metadata: Dict[str, Any]


def parse_modal_html_text(full_text: str, *, default_network: Optional[str]) -> ParsedPlan:
    # 한 번의 텍스트 스캔으로 필드를 추정(보수적, 사이트 개편 시에도 비교적 견고)
    text = re.sub(r"\s+", " ", full_text)

    # 이름: 첫 줄 또는 제목 패턴 근사치
    name_match = re.search(r"요금제명\s*[:\-]?\s*([^\n\r]+)", full_text)
    name = name_match.group(1).strip() if name_match else None
    if not name:
        # 대안: 큰 제목 패턴(예: h2/h3 텍스트가 포함되었을 때)
        title_guess = re.search(r"([\w가-힣0-9\+\- ]{3,})\s*요금제", full_text)
        name = title_guess.group(0).strip() if title_guess else "요금제"

    monthly_fee = text_to_int_money(text)
    data_allowance_mb = normalize_data_allowance(text)
    voice_minutes = extract_minutes(text)
    sms_count = extract_sms_count(text)

    # 네트워크
    network_type = default_network
    if " 5g" in text.lower() or "5G" in text:
        network_type = "5G"
    elif " LTE" in text or "lte" in text.lower():
        network_type = network_type or "LTE"

    # 프로모션/혜택 키워드 근사치
    promo = None
    m = re.search(r"(할인|특가|이벤트|프로모션|한정|사은)[: ]?([^\n\r]+)", text)
    if m:
        promo = (m.group(0) or "").strip()

    metadata: Dict[str, Any] = {}
    if "무제한" in text:
        metadata["unlimited"] = True

    return ParsedPlan(
        name=name,
        monthly_fee=monthly_fee,
        data_allowance_mb=data_allowance_mb,
        voice_minutes=voice_minutes,
        sms_count=sms_count,
        network_type=network_type,
        promotion=promo,
        metadata=metadata,
    )


# ----------------------------- 크롤링 로직 -----------------------------

def close_popups(page: Page) -> None:
    for sel in [
        "button:has-text('동의 후 닫기')",
        "button:has-text('오늘 하루 그만보기')",
        "button[aria-label='닫기']",
        "button:has-text('닫기')",
    ]:
        try:
            loc = page.locator(sel).first
            if loc.is_visible():
                loc.click(timeout=500)
        except Exception:
            pass


def collect_records(page: Page) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []

    # 메인 탭
    main_tabs = page.locator("button.c-tabs__button[id^='rateListTab']").all()
    for main in main_tabs:
        try:
            main.scroll_into_view_if_needed()
            main.click()
            expect(main).to_have_attribute("aria-selected", "true")
        except Exception:
            continue

        # 서브 탭(있을 때만)
        sub_tabs = page.locator("[role=tab]").all()
        if not sub_tabs:
            sub_tabs = [None]  # 서브탭이 없으면 단일 패널로 처리

        for sub in sub_tabs:
            default_network: Optional[str] = None
            try:
                if sub is not None:
                    sub.scroll_into_view_if_needed()
                    label = sub.inner_text().strip()
                    if "5G" in label:
                        default_network = "5G"
                    elif "LTE" in label:
                        default_network = "LTE"
                    sub.click()
                    expect(sub).to_have_attribute("aria-selected", "true")
            except Exception:
                pass

            # 아코디언 헤더 확장
            headers = page.locator("button[aria-controls][data-rate-adsvc-ctg-cd]").all()
            for hdr in headers:
                try:
                    expanded = hdr.get_attribute("aria-expanded")
                    if expanded != "true":
                        hdr.scroll_into_view_if_needed()
                        hdr.click()
                        page.wait_for_timeout(200)
                except Exception:
                    continue

            # 카드 상세 버튼
            detail_buttons = page.locator(
                ".c-product button:has-text('상세'), .c-product a:has-text('자세히')"
            ).all()

            for btn in detail_buttons:
                try:
                    btn.scroll_into_view_if_needed()
                    btn.click()
                    modal = page.locator(
                        ".c-modal.is-active, [role=dialog][aria-modal=true]"
                    ).first
                    expect(modal).to_be_visible()
                except Exception:
                    # 모달 등장 실패 → 다음 항목으로
                    continue

                # 모달 텍스트 파싱
                try:
                    full_text = modal.inner_text()
                    parsed = parse_modal_html_text(full_text, default_network=default_network)
                    plan_id = make_plan_id(parsed.name, parsed.monthly_fee, parsed.network_type)
                    record = {
                        "vendor": VENDOR,
                        "plan_id": plan_id,
                        "name": parsed.name,
                        "monthly_fee": parsed.monthly_fee if parsed.monthly_fee is not None else "",
                        "data_allowance_mb": parsed.data_allowance_mb if parsed.data_allowance_mb is not None else "",
                        "voice_minutes": parsed.voice_minutes if parsed.voice_minutes is not None else "",
                        "sms_count": parsed.sms_count if parsed.sms_count is not None else "",
                        "network_type": parsed.network_type or "",
                        "promotion": parsed.promotion or "",
                        "metadata_json": parsed.metadata if parsed.metadata else {},
                        "source_url": URL,
                    }
                    records.append(record)
                except Exception:
                    pass
                finally:
                    # 모달 닫기
                    try:
                        close_btn = page.locator(
                            ".c-modal__close, button:has-text('닫기')"
                        ).first
                        if close_btn.is_visible():
                            close_btn.click()
                        else:
                            page.keyboard.press("Escape")
                    except Exception:
                        try:
                            page.keyboard.press("Escape")
                        except Exception:
                            pass

            # 탭 간 짧은 휴지
            page.wait_for_timeout(150)

    return records


def write_csv(path: Path, records: List[Dict[str, Any]]) -> None:
    ensure_parent_dir(path)
    fieldnames = [
        "vendor",
        "plan_id",
        "name",
        "monthly_fee",
        "data_allowance_mb",
        "voice_minutes",
        "sms_count",
        "network_type",
        "promotion",
        "metadata_json",
        "source_url",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            row = dict(r)
            # metadata는 문자열로 직렬화(간단 직렬화)
            if isinstance(row.get("metadata_json"), dict):
                row["metadata_json"] = str(row["metadata_json"]).replace("\n", " ")
            writer.writerow(row)


def main(argv: List[str]) -> int:
    # 인자 단순 처리: --headless, --slowmo, --output
    headless = "--headless" in argv
    slowmo = 0
    out_path = Path("ktmm_out/ktmmobile_modal_data.csv")
    for i, a in enumerate(argv):
        if a == "--slowmo" and i + 1 < len(argv):
            try:
                slowmo = int(argv[i + 1])
            except Exception:
                slowmo = 0
        if a == "--output" and i + 1 < len(argv):
            out_path = Path(argv[i + 1])

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=slowmo)
        page = browser.new_page()
        page.goto(URL, wait_until="domcontentloaded")

        close_popups(page)
        records = collect_records(page)

        write_csv(out_path, records)
        print(f"✅ 레코드 {len(records)}건 저장: {out_path.resolve()}")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))



