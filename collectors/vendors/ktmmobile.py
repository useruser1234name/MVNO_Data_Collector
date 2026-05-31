"""Collector implementation for KT M모바일 (ktmmobile) 요금제 페이지.

탭(메인/서브) → 카테고리(아코디언) → 카드 → 모달 순서로 탐색하여
모달에서 요금제 필드를 파싱해 PlanRecord로 표준화합니다.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional

from collectors.base import BaseCollector
from collectors.registry import registry
from collectors.utils.playwright import browser_context
from schemas.plan_record import PlanRecord


TARGET_URL = "https://www.ktmmobile.com/rate/rateList.do"


@dataclass(slots=True)
class ModalRaw:
    name: str
    monthly_fee: Optional[int]
    data_allowance_mb: int
    voice_minutes: Optional[int]
    sms_count: Optional[int]
    network_type: Optional[str]
    promotion: Optional[str]
    metadata: dict[str, Any]


def _parse_money_first(text: str | None) -> Optional[int]:
    if not text:
        return None
    m = re.search(r"(?:^|[^0-9])(\d[\d,]*)\s*원", text)
    if not m:
        # 숫자만 존재하는 경우(보수적)
        m2 = re.search(r"\b(\d{4,6})\b", text.replace(",", ""))
        return int(m2.group(1)) if m2 else None
    return int(m.group(1).replace(",", ""))


def _parse_data_allowance_mb(text: str | None) -> int:
    if not text:
        return 0
    t = text.replace(",", " ")
    # 명시적 제공량 우선
    m = re.search(r"(\d+(?:\.\d+)?)\s*(TB|GB|MB)", t, re.IGNORECASE)
    if m:
        val = float(m.group(1))
        unit = m.group(2).upper()
        if unit == "TB":
            return int(val * 1024 * 1024)
        if unit == "GB":
            return int(val * 1024)
        return int(val)
    # "무제한"은 0으로 두고 metadata.unlimited로 표현(호출부에서 병합)
    return 0


def _parse_minutes(text: str | None) -> Optional[int]:
    if not text:
        return None
    if "무제한" in text or "기본제공" in text:
        return None
    m = re.search(r"(\d+)\s*분", text.replace(",", ""))
    return int(m.group(1)) if m else None


def _parse_sms_count(text: str | None) -> Optional[int]:
    if not text:
        return None
    if "무제한" in text or "기본제공" in text:
        return None
    m = re.search(r"(\d+)\s*(건|SMS)", text, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _make_plan_id(name: str, monthly_fee: Optional[int], network_type: Optional[str]) -> str:
    base = f"{name}|{monthly_fee or 0}|{network_type or ''}"
    return "ktmm-" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


async def _close_popups(page) -> None:
    selectors = [
        "button:has-text('동의 후 닫기')",
        "button:has-text('오늘 하루 그만보기')",
        "button[aria-label='닫기']",
        "button:has-text('닫기')",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible():
                await loc.click(timeout=500)
        except Exception:
            pass


async def _click_tab_by_text(page, text: str) -> bool:
    try:
        tab = page.get_by_role("tab", name=re.compile(re.escape(text)))
        await tab.click(timeout=3000)
        await asyncio.sleep(0.15)
        return True
    except Exception:
        return False


async def _enumerate_sub_tabs(page) -> list[str | None]:
    # 서브탭이 없으면 [None]
    try:
        sub_list = page.locator("#subTabPanel").first
        count = await sub_list.get_by_role("tab").count()
        if count == 0:
            return [None]
        names: list[str] = []
        for i in range(count):
            t = (await sub_list.get_by_role("tab").nth(i).inner_text()).strip()
            if t:
                names.append(t)
        return names or [None]
    except Exception:
        return [None]


async def _expand_all_categories(page) -> list[tuple[str, Any]]:
    # 반환: [(카테고리라벨, 카테고리버튼)]
    pairs: list[tuple[str, Any]] = []
    loc = page.locator("button.c-accordion__button")
    count = await loc.count()
    for i in range(count):
        btn = loc.nth(i)
        try:
            label = (await btn.inner_text()).strip()
            await btn.scroll_into_view_if_needed()
            await btn.click()
            # 컨텐츠 등장 대기
            await page.wait_for_selector(".rate-content__list, .rate-content-wrap", timeout=6000)
            pairs.append((label, btn))
            await asyncio.sleep(0.2)
        except Exception:
            continue
    return pairs


async def _iter_cards_in_scope(page) -> list[Any]:
    # 카드 컨테이너 안의 아이템을 되도록 많이 포괄
    loc = page.locator(".rate-content__list .rate-content__item, .rate-content-wrap .rate-content__item, .rate-content-wrap")
    count = await loc.count()
    items: list[Any] = []
    if count == 0:
        return items
    for i in range(count):
        items.append(loc.nth(i))
    return items


async def _open_modal_from_card(card) -> bool:
    try:
        # 우선 '상세/자세히' 버튼/링크
        btn = card.locator("button:has-text('상세'), a:has-text('자세히')").first
        if await btn.count() == 0:
            # 폴백: 첫 클릭 가능 요소
            btn = card.locator("button, a").first
        await btn.scroll_into_view_if_needed()
        await btn.click()
        return True
    except Exception:
        return False


async def _wait_modal(page) -> Optional[Any]:
    try:
        await page.wait_for_selector(".c-modal.is-active, [role='dialog'][aria-modal='true']", timeout=6000)
        return await page.locator(".c-modal.is-active, [role='dialog'][aria-modal='true']").first
    except Exception:
        return None


async def _close_modal(page) -> None:
    try:
        close_btn = page.locator(".c-modal__close, button:has-text('닫기')").first
        if await close_btn.is_visible():
            await close_btn.click()
        else:
            await page.keyboard.press("Escape")
    except Exception:
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
    await asyncio.sleep(0.1)


async def _parse_modal(page, modal, *, network_hint: Optional[str], category_hint: Optional[str]) -> ModalRaw:
    text = await modal.inner_text()
    # 제목
    name = ""
    try:
        name = (await modal.locator("h2").first.inner_text()).strip()
    except Exception:
        # fall back: first strong/heading style
        try:
            name = (await modal.locator("h1, h3, strong").first.inner_text()).strip()
        except Exception:
            name = "요금제"

    monthly_fee = _parse_money_first(text)
    data_allowance_mb = _parse_data_allowance_mb(text)
    voice_minutes = _parse_minutes(text)
    sms_count = _parse_sms_count(text)

    network_type = network_hint
    if "5G" in text:
        network_type = "5G"
    elif "LTE" in (text or ""):
        network_type = network_type or "LTE"

    # 프로모션/혜택 후보 텍스트
    promotions: list[str] = []
    try:
        # 금액 라벨/혜택 구간 추출(있으면 이어붙임)
        money_box = modal.locator("text=프로모션 요금").first
        if await money_box.count() > 0:
            line = (await money_box.inner_text()).strip()
            if line:
                promotions.append(line)
    except Exception:
        pass
    # 혜택/유의사항 일부 헤더 근처 문장
    for sel in [
        "text=요금제 혜택",
        "text=요금제 이용 시 추가 이용가능 서비스",
        "text=유의사항",
    ]:
        try:
            box = modal.locator(sel).first
            if await box.count() > 0:
                container = box.locator("xpath=..").first
                snippet = (await container.inner_text()).strip()
                if snippet:
                    promotions.append(re.sub(r"\s+", " ", snippet))
        except Exception:
            continue

    metadata: dict[str, Any] = {
        "category": category_hint,
        "raw_modal_text": re.sub(r"\s+", " ", text),
    }
    if "무제한" in text:
        metadata["unlimited"] = True

    return ModalRaw(
        name=name,
        monthly_fee=monthly_fee,
        data_allowance_mb=data_allowance_mb,
        voice_minutes=voice_minutes,
        sms_count=sms_count,
        network_type=network_type,
        promotion=" | ".join(dict.fromkeys([p for p in promotions if p])) if promotions else None,
        metadata=metadata,
    )


class KTMMobileCollector(BaseCollector):
    """Collector that scrapes KT M모바일 요금제 모달들에서 정보를 수집."""

    async def fetch_entries(self) -> Iterable[ModalRaw]:
        entries: list[ModalRaw] = []
        async with browser_context() as context:
            page = await context.new_page()
            page.set_default_timeout(10000)
            await page.goto(TARGET_URL, wait_until="domcontentloaded")
            await _close_popups(page)
            # 디버그: 초기 DOM 저장
            try:
                html = await page.content()
                await self.save_raw_payload(html, "initial.html")
            except Exception:
                pass

            # 메인 탭들(없으면 현재 탭만)
            main_tabs = ["유심/eSIM 요금제", "제휴 요금제", "휴대폰 요금제"]
            seen_main: set[str] = set()
            for main in main_tabs:
                clicked = await _click_tab_by_text(page, main)
                if not clicked:
                    continue
                if main in seen_main:
                    continue
                seen_main.add(main)
                # 서브탭 순회(없으면 [None])
                sub_names = await _enumerate_sub_tabs(page)
                for sub in sub_names:
                    network_hint = None
                    if sub:
                        await _click_tab_by_text(page, sub)
                        if "5G" in sub:
                            network_hint = "5G"
                        elif "LTE" in sub:
                            network_hint = "LTE"
                    # 아코디언 전개
                    cats = await _expand_all_categories(page)
                    for cat_label, _btn in cats:
                        # 카드 열거
                        cards = await _iter_cards_in_scope(page)
                        for card in cards:
                            opened = await _open_modal_from_card(card)
                            if not opened:
                                continue
                            modal = await _wait_modal(page)
                            if not modal:
                                continue
                            try:
                                raw = await _parse_modal(page, modal, network_hint=network_hint, category_hint=cat_label)
                                entries.append(raw)
                            finally:
                                await _close_modal(page)
                            await asyncio.sleep(0.2)
                    await asyncio.sleep(0.2)
        return entries

    async def parse_entries(self, entries: Iterable[ModalRaw]) -> List[PlanRecord]:
        records: list[PlanRecord] = []
        for raw in entries:
            plan_id = _make_plan_id(raw.name, raw.monthly_fee, raw.network_type)
            metadata = dict(raw.metadata)
            record = PlanRecord(
                vendor="ktmmobile",
                plan_id=plan_id,
                name=raw.name,
                monthly_fee=float(raw.monthly_fee or 0),
                data_allowance_mb=raw.data_allowance_mb,
                voice_minutes=raw.voice_minutes,
                sms_count=raw.sms_count,
                network_type=raw.network_type,
                promotion=raw.promotion,
                metadata=metadata,
            )
            records.append(record)
        return records


registry.register(
    "ktmmobile",
    KTMMobileCollector,
    description="KT M모바일 요금제 탭/카테고리/모달 수집 후 PlanRecord로 반환",
)


