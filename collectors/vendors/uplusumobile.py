"""Collector implementation for LG U+ U+모바일 (uplusumobile)."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Iterable, List
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from collectors.base import BaseCollector
from collectors.registry import registry
from schemas.plan_record import PlanRecord

logger = logging.getLogger(__name__)


LIST_URLS = [
    "https://www.uplusumobile.com/product/pric/usim/pricList",
]

DETAIL_BASE = "https://www.uplusumobile.com/product/pric/pricDetail"
REQUEST_INTERVAL_SEC = 0.5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.uplusumobile.com/",
    "Connection": "keep-alive",
}


@dataclass(slots=True)
class DetailCandidate:
    """Metadata required to request a plan detail page."""

    detail_url: str
    kind: str | None = None
    category: str | None = None
    seq: str | None = None
    up_ppn_cd: str | None = None
    dev_kd_cd: str | None = None
    ppn_cd: str | None = None



def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    retries = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def fetch_soup(session: requests.Session, url: str) -> BeautifulSoup:
    response = session.get(url, timeout=25)
    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = "utf-8"
    response.raise_for_status()
    return BeautifulSoup(response.text, "lxml")


def parse_meta_from_list_url(url: str) -> dict[str, str | None]:
    parsed = urlparse(url)
    parts = [segment for segment in parsed.path.split("/") if segment]
    kind = None
    try:
        kind_idx = parts.index("pric") + 1
        kind = parts[kind_idx]
    except ValueError:
        kind = None
    query = parse_qs(parsed.query)
    category = (query.get("fltrTypeCtgr") or [None])[0]
    return {"kind": kind, "category": category}


def _clean(value: str | None) -> str | None:
    return value.strip() if value else None


def _split_combo(data_seq: str | None) -> tuple[str | None, str | None]:
    if not data_seq:
        return None, None
    parts = [part.strip() for part in data_seq.split("||")]
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[0], parts[1]
    return None, None


def extract_detail_candidates(soup: BeautifulSoup) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    buttons = soup.select("button[data-hp-ppn-seq][data-up-ppn-cd][data-dev-kd-cd]")
    for button in buttons:
        seq = _clean(button.get("data-hp-ppn-seq"))
        up = _clean(button.get("data-up-ppn-cd"))
        dev = _clean(button.get("data-dev-kd-cd"))
        ppn = _clean(button.get("data-ppn-cd"))
        if not (seq and dev and up is not None):
            continue
        rows.append({
            "seq": seq,
            "upPpnCd": up or "",
            "devKdCd": dev,
            "ppnCd": ppn,
        })

    anchors = soup.select("a.gtm-tracking")
    for anchor in anchors:
        dev_combo, seq_combo = _split_combo(_clean(anchor.get("data-seq")))
        seq_attr = _clean(anchor.get("seq")) or _clean(anchor.get("data-hp-ppn-seq")) or _clean(anchor.get("data-seq-single"))
        ctgr_attr = (
            _clean(anchor.get("ctgrId"))
            or _clean(anchor.get("ctgrid"))
            or _clean(anchor.get("ctgrID"))
            or _clean(anchor.get("ctgr_id"))
        )
        seq = seq_combo or seq_attr
        dev = dev_combo or ctgr_attr
        if not (seq and dev):
            continue
        rows.append({
            "seq": seq,
            "upPpnCd": "",
            "devKdCd": dev,
            "ppnCd": None,
        })

    return rows


def build_detail_url(seq: str, up_ppn_cd: str, dev_kd_cd: str) -> str:
    query = {"seq": seq, "upPpnCd": up_ppn_cd, "devKdCd": dev_kd_cd}
    return f"{DETAIL_BASE}?{urlencode(query)}"


def parse_money(text: str | None) -> int | None:
    if not text:
        return None
    cleaned = text.replace(",", "")
    digits = re.findall(r"\d+", cleaned)
    if not digits:
        return None
    return int("".join(digits))


def extract_speed_toplist(soup: BeautifulSoup) -> str | None:
    for li in soup.select("div.detail-info ul.notification.free > li"):
        text = "".join(li.find_all(string=True, recursive=False)).strip()
        if re.search(r"(?i)mbps", text):
            return re.sub(r"\s+", " ", text)
    for li in soup.select("div.detail-info li"):
        text = "".join(li.find_all(string=True, recursive=False)).strip()
        if re.search(r"(?i)mbps", text):
            return re.sub(r"\s+", " ", text)
    return None


def extract_speed_from_data_guide(soup: BeautifulSoup) -> str | None:
    header = None
    for node in soup.select("h2"):
        if "데이터 이용 안내" in node.get_text(strip=True):
            header = node
            break
    if not header:
        return None
    container = header.find_next(class_=re.compile(r"(?:plan-detail-conts|acc-conts)"))
    if not container:
        container = header.find_parent("section") or header
    statements: list[str] = []
    for li in container.select("li"):
        text = " ".join(li.stripped_strings)
        if re.search(r"(?i)mbps", text):
            statements.append(re.sub(r"\s+", " ", text))
    if statements:
        deduped = list(dict.fromkeys(statements))
        return " | ".join(deduped)
    return None


def parse_card_header(soup: BeautifulSoup) -> dict[str, Any]:
    def text(selector: str) -> str | None:
        node = soup.select_one(selector)
        return node.get_text(strip=True) if node else None

    feature_supply_bits: list[str] = []
    for span in soup.select(".spc-list span"):
        value = span.get_text(strip=True)
        if value:
            feature_supply_bits.append(value)

    chips: list[str] = []
    for img in soup.select(".badge-box img[alt]"):
        alt = (img.get("alt") or "").strip()
        if alt:
            chips.append(alt)

    tip_paragraph = soup.select_one(".spc-wrp .tip-box p")
    speed_top = None
    if tip_paragraph:
        statement = " ".join(tip_paragraph.stripped_strings)
        if re.search(r"(?i)mbps", statement):
            speed_top = re.sub(r"\s+", " ", statement)

    return {
        "title": text("strong.pln-tit"),
        "feature_vol": text(".spc-wrp .pln-spc"),
        "feature_supply": " ".join(feature_supply_bits) if feature_supply_bits else None,
        "price_origin": parse_money(text(".price-box .cost")),
        "price_discount": parse_money(text(".price-box .dc")),
        "chips": "|".join(dict.fromkeys(chips)) if chips else None,
        "speed_toplist": speed_top,
    }


def parse_detail_page(soup: BeautifulSoup, url: str) -> dict[str, Any]:
    parsed_url = urlparse(url)
    query = parse_qs(parsed_url.query)
    url_params = {
        "seq": (query.get("seq") or [None])[0],
        "upPpnCd": (query.get("upPpnCd") or [None])[0],
        "devKdCd": (query.get("devKdCd") or [None])[0],
    }

    def input_value(selector: str) -> str | None:
        node = soup.select_one(selector)
        if node and node.has_attr("value"):
            return node["value"].strip() or None
        return None

    form = soup.select_one("form#onsaleJoinFrm")
    def form_value(selector: str) -> str | None:
        if not form:
            return None
        node = form.select_one(selector)
        if node and node.has_attr("value"):
            return node["value"].strip() or None
        return None

    card = parse_card_header(soup)

    title = card["title"] or input_value("input#feeName")
    if not title:
        heading = soup.select_one(".detail-header h2.tit")
        title = heading.get_text(strip=True) if heading else None

    feature_vol = card["feature_vol"]
    if not feature_vol:
        vol_node = soup.select_one(".detail-header .feature .vol")
        feature_vol = vol_node.get_text(strip=True) if vol_node else None

    feature_limit = None
    limit_node = soup.select_one(".detail-header .feature .limit")
    if limit_node:
        feature_limit = limit_node.get_text(strip=True)

    feature_supply = card["feature_supply"]
    if not feature_supply:
        supply_node = soup.select_one(".detail-header .feature .supply")
        feature_supply = supply_node.get_text(strip=True) if supply_node else None

    price_origin = card["price_origin"]
    if price_origin is None:
        origin_node = soup.select_one(".detail-footer .pay-amount .origin-pay")
        price_origin = parse_money(origin_node.get_text(strip=True) if origin_node else None)

    price_discount = card["price_discount"]
    if price_discount is None:
        discount_node = soup.select_one(".detail-footer .pay-amount .discount-pay")
        price_discount = parse_money(discount_node.get_text(strip=True) if discount_node else None)

    chips = card["chips"]
    if not chips:
        chip_values: list[str] = []
        wrapper = soup.select_one(".detail-header .chip-wrap")
        if wrapper:
            for node in wrapper.select(".chip"):
                text = node.get_text(strip=True)
                if text:
                    chip_values.append(text)
            for img in wrapper.select("img[alt]"):
                alt = (img.get("alt") or "").strip()
                if alt:
                    chip_values.append(alt)
        if chip_values:
            chips = "|".join(dict.fromkeys([value for value in chip_values if value]))

    speed_toplist = card["speed_toplist"] or extract_speed_toplist(soup)
    speed_data_guide = extract_speed_from_data_guide(soup)

    return {
        "seq": input_value("input#seq") or url_params["seq"],
        "ctgrId": input_value("input#ctgrId"),
        "hpPpnSeq": form_value("#hpPpnSeq"),
        "hpPpnCd": form_value("#hpPpnCd"),
        "upPpnCd": form_value("#upPpnCd") or url_params["upPpnCd"],
        "devKdCd": url_params["devKdCd"],
        "sbscTypCd2": form_value("#sbscTypCd2"),
        "sbscTypCd3": form_value("#sbscTypCd3"),
        "feeName": form_value("#feeName"),
        "feeType": form_value("#feeType"),
        "title": title,
        "feature_vol": feature_vol,
        "feature_limit": feature_limit,
        "feature_supply": feature_supply,
        "price_origin": price_origin,
        "price_discount": price_discount,
        "chips": chips,
        "speed_toplist": speed_toplist,
        "speed_data_guide": speed_data_guide,
        "detail_url": url,
    }


def _parse_data_allowance(text: str | None, limit_text: str | None) -> tuple[int, dict[str, Any]]:
    metadata: dict[str, Any] = {}
    if not text:
        return 0, metadata
    normalized = re.sub(r"\s+", " ", text)
    metadata["feature_vol_raw"] = normalized
    if limit_text:
        metadata["feature_limit_raw"] = re.sub(r"\s+", " ", limit_text)
    if "무제한" in normalized:
        metadata["unlimited_data"] = True
        return 0, metadata
    match = re.search(r"(\d+(?:\.\d+)?)\s*(TB|GB|MB)", normalized, flags=re.IGNORECASE)
    if not match:
        return 0, metadata
    value = float(match.group(1))
    unit = match.group(2).upper()
    multiplier = 1
    if unit == "TB":
        multiplier = 1024 * 1024
    elif unit == "GB":
        multiplier = 1024
    allowance = int(value * multiplier)
    return allowance, metadata


def _parse_voice_minutes(text: str | None) -> tuple[int | None, dict[str, Any]]:
    info: dict[str, Any] = {}
    if not text:
        return None, info
    normalized = re.sub(r"\s+", " ", text)
    info["voice_supply_raw"] = normalized
    if "무제한" in normalized:
        info["voice_unlimited"] = True
        return None, info
    match = re.search(r"(\d+)\s*분", normalized)
    if match:
        return int(match.group(1)), info
    return None, info


def _parse_sms_count(text: str | None) -> tuple[int | None, dict[str, Any]]:
    info: dict[str, Any] = {}
    if not text:
        return None, info
    normalized = re.sub(r"\s+", " ", text)
    info["sms_supply_raw"] = normalized
    if "무제한" in normalized:
        info["sms_unlimited"] = True
        return None, info
    match = re.search(r"(\d+)\s*건", normalized)
    if match:
        return int(match.group(1)), info
    return None, info


def _make_plan_id(candidate: DetailCandidate, detail: dict[str, Any]) -> str:
    seq = candidate.seq or detail.get("seq") or "unknown"
    dev = candidate.dev_kd_cd or detail.get("devKdCd") or "na"
    up_ppn = candidate.up_ppn_cd or detail.get("upPpnCd") or ""
    return "-".join(filter(None, [seq, dev, up_ppn]))


def _detail_to_plan_record(candidate: DetailCandidate, detail: dict[str, Any]) -> PlanRecord:
    monthly_fee_source = detail.get("price_discount") or detail.get("price_origin") or 0
    data_allowance_mb, data_meta = _parse_data_allowance(detail.get("feature_vol"), detail.get("feature_limit"))
    voice_minutes, voice_meta = _parse_voice_minutes(detail.get("feature_supply"))
    sms_count, sms_meta = _parse_sms_count(detail.get("feature_supply"))

    metadata: dict[str, Any] = {
        "detail": detail,
        "candidate": asdict(candidate),
    }
    metadata.update(data_meta)
    metadata.update(voice_meta)
    metadata.update(sms_meta)

    name = detail.get("title") or detail.get("feeName") or _make_plan_id(candidate, detail)
    promotion_parts = [part for part in [detail.get("chips"), detail.get("speed_toplist"), detail.get("speed_data_guide")] if part]
    promotion = " | ".join(promotion_parts) if promotion_parts else None

    return PlanRecord(
        vendor="uplusumobile",
        plan_id=_make_plan_id(candidate, detail),
        name=name,
        monthly_fee=float(monthly_fee_source),
        data_allowance_mb=data_allowance_mb,
        voice_minutes=voice_minutes,
        sms_count=sms_count,
        network_type=candidate.category,
        promotion=promotion,
        metadata=metadata,
    )


class UPlusUMobileCollector(BaseCollector):
    """Collector that scrapes the LG U+ U+모바일 product catalogue."""

    async def fetch_entries(self) -> Iterable[DetailCandidate]:
        return await asyncio.to_thread(self._fetch_entries_sync)

    def _fetch_entries_sync(self) -> list[DetailCandidate]:
        session = build_session()
        candidates: list[DetailCandidate] = []
        seen: set[tuple[str | None, str | None, str | None]] = set()
        try:
            for list_url in LIST_URLS:
                meta = parse_meta_from_list_url(list_url)
                soup = fetch_soup(session, list_url)
                rows = extract_detail_candidates(soup)
                for row in rows:
                    key = (row["seq"], row["upPpnCd"], row["devKdCd"])
                    if key in seen:
                        continue
                    seen.add(key)
                    detail_url = build_detail_url(row["seq"], row["upPpnCd"], row["devKdCd"])
                    candidates.append(
                        DetailCandidate(
                            detail_url=detail_url,
                            kind=meta.get("kind"),
                            category=meta.get("category"),
                            seq=row.get("seq"),
                            up_ppn_cd=row.get("upPpnCd"),
                            dev_kd_cd=row.get("devKdCd"),
                            ppn_cd=row.get("ppnCd"),
                        )
                    )
                time.sleep(REQUEST_INTERVAL_SEC)
        finally:
            session.close()
        logger.info("Collected %s detail URLs", len(candidates))
        return candidates

    async def parse_entries(self, entries: Iterable[DetailCandidate]) -> List[PlanRecord]:
        return await asyncio.to_thread(self._parse_entries_sync, list(entries))

    def _parse_entries_sync(self, entries: list[DetailCandidate]) -> List[PlanRecord]:
        session = build_session()
        records: list[PlanRecord] = []
        try:
            for idx, candidate in enumerate(entries, 1):
                soup: BeautifulSoup | None = None
                try:
                    soup = fetch_soup(session, candidate.detail_url)
                    detail = parse_detail_page(soup, candidate.detail_url)
                    record = _detail_to_plan_record(candidate, detail)
                    records.append(record)
                except Exception as exc:
                    logger.warning("Failed to parse %s: %s", candidate.detail_url, exc, exc_info=True)
                time.sleep(REQUEST_INTERVAL_SEC)
        finally:
            session.close()
        return records


registry.register(
    "uplusumobile",
    UPlusUMobileCollector,
    description="LG U+ U+모바일 요금제 상세 페이지를 수집하여 PlanRecord로 반환",
)
