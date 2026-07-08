"""Collector implementation for A모바일 (amobile).

본 구현은 로컬에 저장된 상세 HTML(`amobile_detail_html/`)을 파싱하여
표준 `PlanRecord` 목록을 생성합니다. 운영 단계에서는 목록/상세 페이지를
직접 요청하는 방식으로 확장할 수 있습니다.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List

from bs4 import BeautifulSoup

from collectors.base import BaseCollector
from collectors.registry import registry
from schemas import units
from schemas.plan_record import PlanRecord


logger = logging.getLogger(__name__)


DEFAULT_HTML_DIR = Path(os.environ.get("AMOBILE_HTML_DIR", "amobile_detail_html"))


@dataclass(slots=True)
class HTMLDetail:
    path: Path
    carrier_label: str | None  # e.g., "KT" or "LGU"


def _extract_table_mapping(soup: BeautifulSoup) -> dict[str, str]:
    """상세 테이블에서 헤더명 -> 값 텍스트 매핑을 추출합니다.

    테이블 구조 예시:
      헤더행(2): 음성 | 문자 | 데이터 | ... | 청구기본료 | 음성(초) | 문자(건) | 데이터(MB)
      데이터행(1): 100분 | 100건 | 500M | ... | 3,300원 | 1.98 | 22 | 22.53
    """
    panel = soup.select_one("#ctl00_ContentPlaceHolder1_GeneralPlanPanel table")
    if not panel:
        return {}
    rows = panel.select("tr")
    if len(rows) < 2:
        return {}
    # 헤더 후보 행들 중 실제 항목명이 있는 마지막 헤더행 가정
    header_cells = rows[1].select("th") if len(rows) >= 2 else []
    data_cells = rows[2].select("td") if len(rows) >= 3 else []
    # 일부 페이지는 헤더가 한 행만 있을 수 있음
    if not header_cells and rows:
        header_cells = rows[0].select("th")
        data_cells = rows[1].select("td") if len(rows) >= 2 else []

    headers = [cell.get_text(strip=True) for cell in header_cells]
    values = [cell.get_text(" ", strip=True) for cell in data_cells]
    mapping: dict[str, str] = {}
    for idx, key in enumerate(headers):
        if idx < len(values):
            mapping[key] = values[idx]
    return mapping


def _extract_title(soup: BeautifulSoup) -> str | None:
    node = soup.select_one(".sub_wrap > h3.sub_tit")
    return node.get_text(strip=True) if node else None


def _extract_plan_id(soup: BeautifulSoup, fallback_name: str | None) -> str:
    # 1) form action 내 숫자
    form = soup.select_one("form#aspnetForm")
    if form and form.has_attr("action"):
        m = re.search(r"(\d+)", form["action"])  # e.g., "./70944"
        if m:
            return m.group(1)
    # 2) 파일명에서 추출
    if fallback_name:
        m = re.search(r"(\d+)", fallback_name)
        if m:
            return m.group(1)
    return "unknown"


def _infer_network_type_from_title(title: str | None) -> str | None:
    if not title:
        return None
    if "LTE" in title.upper():
        return "LTE"
    if "5G" in title.upper():
        return "5G"
    return None


def _detect_carrier_from_filename(path: Path) -> str | None:
    stem = path.stem  # e.g., "KT__70944"
    if stem.upper().startswith("KT__"):
        return "KT"
    if stem.upper().startswith("LGU__"):
        return "LGU"
    return None


def _parse_detail_html(path: Path) -> PlanRecord | None:
    try:
        html = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.warning("Failed to read %s: %s", path, exc)
        return None

    soup = BeautifulSoup(html, "lxml")
    title = _extract_title(soup)
    mapping = _extract_table_mapping(soup)

    # 필드 추출
    voice_text = mapping.get("음성")
    sms_text = mapping.get("문자")
    data_text = mapping.get("데이터") or mapping.get("데이터(MB)")
    fee_text = mapping.get("청구기본료") or mapping.get("기본료")

    # 통합 normalizer로 단위/무제한/실패를 일관 처리(벤더별 재구현 제거).
    data_q = units.parse_data_to_mb(data_text)
    voice_q = units.parse_voice(voice_text)
    sms_q = units.parse_sms(sms_text)
    monthly_fee = units.parse_money(fee_text)

    carrier = _detect_carrier_from_filename(path)
    plan_id = _extract_plan_id(soup, path.name)
    network_type = _infer_network_type_from_title(title)

    if monthly_fee is not None:
        fee_status = units.STATUS_OK
    else:
        # 파싱 실패를 0원 정상 요금제로 둔갑시키지 않도록 사유를 parse_status에 명시한다.
        # PlanRecord.monthly_fee는 float 필수라 0으로 채우되, 하류 품질 게이트에서 격리 가능하게 한다.
        fee_status = units.STATUS_MISSING if not fee_text else units.STATUS_UNPARSED
        logger.warning(
            "amobile fee parse failed (%s): plan_id=%s raw_fee=%r", fee_status, plan_id, fee_text
        )
        monthly_fee = 0

    parse_status = {
        "data": data_q.status,
        "voice": voice_q.status,
        "sms": sms_q.status,
        "fee": fee_status,
    }

    name = title or plan_id

    metadata: dict[str, Any] = {
        "source_path": str(path),
        "carrier_label": carrier,
        "raw_voice": voice_text,
        "raw_sms": sms_text,
        "raw_data": data_text,
        "raw_fee": fee_text,
    }

    record = PlanRecord(
        vendor="amobile",
        plan_id=plan_id,
        name=name,
        monthly_fee=float(monthly_fee),
        data_allowance_mb=data_q.value,
        voice_minutes=voice_q.value,
        sms_count=sms_q.value,
        network_type=network_type,
        promotion=None,
        data_unlimited=data_q.unlimited,
        voice_unlimited=voice_q.unlimited,
        sms_unlimited=sms_q.unlimited,
        parse_status=parse_status,
        metadata=metadata,
    )
    return record


class AMobileCollector(BaseCollector):
    """Collector that parses local A모바일 detail HTML pages into PlanRecords."""

    async def fetch_entries(self) -> Iterable[HTMLDetail]:
        # HTML 디렉터리는 호출 시점에 해석한다(metadata > env > 기본값).
        html_dir = Path(
            self.config.metadata.get("html_dir")
            or os.environ.get("AMOBILE_HTML_DIR", "amobile_detail_html")
        )
        if not html_dir.exists():
            logger.warning("HTML directory not found: %s", html_dir)
            return []
        entries: list[HTMLDetail] = []
        for path in sorted(html_dir.glob("*.html")):
            entries.append(HTMLDetail(path=path, carrier_label=_detect_carrier_from_filename(path)))
        return entries

    async def parse_entries(self, entries: Iterable[HTMLDetail]) -> List[PlanRecord]:
        records: list[PlanRecord] = []
        for entry in entries:
            record = _parse_detail_html(entry.path)
            if record:
                # 파일명으로부터 감지한 carrier를 메타에 병합 (상세에서 값이 없을 수 있음)
                if entry.carrier_label and "carrier_label" not in record.metadata:
                    record.metadata["carrier_label"] = entry.carrier_label
                records.append(record)
        return records


registry.register(
    "amobile",
    AMobileCollector,
    description="A모바일 상세 HTML을 파싱하여 PlanRecord로 반환",
)



