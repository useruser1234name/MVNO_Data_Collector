"""Transformation utilities that standardize raw collector outputs.

quarantine를 단순 null 검사에서 규칙기반(범위·논리·중복·파싱실패)으로 확장한다.
무효 레코드에는 격리 사유(``quarantine_reasons``)를 부착해 추적성을 확보한다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, List

import pandas as pd

# 의심 임계치(사업자별 override는 후속 Phase에서 reference로 외부화 예정)
MAX_MONTHLY_FEE = 500_000
MAX_DATA_ALLOWANCE_MB = 5 * 1024 * 1024  # 5TB
PLACEHOLDER_PLAN_IDS = {"unknown", "unknown-na", "na", ""}
REQUIRED_FIELDS = ["vendor", "plan_id", "name", "monthly_fee"]


@dataclass(slots=True)
class TransformConfig:
    reference_dir: Path
    fail_statuses: tuple[str, ...] = ("unparsed",)
    extra_rules: list = field(default_factory=list)


def load_jsonl(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def normalize_units(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    if "data_allowance_gb" in frame.columns and "data_allowance_mb" not in frame.columns:
        frame["data_allowance_mb"] = frame["data_allowance_gb"] * 1024
    if "monthly_fee" in frame.columns:
        frame["monthly_fee"] = pd.to_numeric(frame["monthly_fee"], errors="coerce")
    return frame


def apply_reference_mappings(frame: pd.DataFrame, config: TransformConfig) -> pd.DataFrame:
    mapping_path = config.reference_dir / "vendor_mapping.csv"
    if mapping_path.exists():
        mapping = pd.read_csv(mapping_path)
        frame = frame.merge(mapping, how="left", left_on="vendor", right_on="source_vendor")
        frame["vendor"] = frame["canonical_vendor"].fillna(frame["vendor"])
        frame.drop(
            columns=[c for c in ["source_vendor", "canonical_vendor"] if c in frame.columns],
            inplace=True,
        )
    return frame


def _parse_status_of(row: pd.Series, field_name: str) -> str | None:
    status = row.get("parse_status")
    if isinstance(status, dict):
        return status.get(field_name)
    return None


def _row_reasons(row: pd.Series, config: TransformConfig) -> List[str]:
    """레코드 한 건에 대한 격리 사유 목록을 반환(빈 목록이면 유효)."""
    reasons: List[str] = []

    # R1: 필수값 결측
    for field_name in REQUIRED_FIELDS:
        value = row.get(field_name)
        if value is None or (isinstance(value, float) and pd.isna(value)):
            reasons.append(f"missing_required:{field_name}")

    # R2: 요금 파싱 실패가 0원으로 둔갑(침묵형 오염 차단)
    if _parse_status_of(row, "fee") in config.fail_statuses:
        reasons.append("fee_parse_failed")

    # R3: 데이터 파싱 실패(무제한/결측이 아닌 진짜 실패)
    if _parse_status_of(row, "data") in config.fail_statuses:
        reasons.append("data_parse_failed")

    # R4: placeholder/약한 자연키
    plan_id = row.get("plan_id")
    if isinstance(plan_id, str) and plan_id.strip().lower() in PLACEHOLDER_PLAN_IDS:
        reasons.append("placeholder_plan_id")
    if plan_id is not None and plan_id == row.get("name"):
        reasons.append("plan_id_equals_name")

    # R5: 요금 범위(0원 이하 의심, 비현실적 고액)
    fee = row.get("monthly_fee")
    if fee is not None and not (isinstance(fee, float) and pd.isna(fee)):
        if fee <= 0:
            reasons.append("fee_non_positive")
        elif fee > MAX_MONTHLY_FEE:
            reasons.append("fee_too_high")

    # R6: 데이터량 범위
    mb = row.get("data_allowance_mb")
    if mb is not None and not (isinstance(mb, float) and pd.isna(mb)):
        if mb < 0:
            reasons.append("data_negative")
        elif mb > MAX_DATA_ALLOWANCE_MB:
            reasons.append("data_too_high")

    # R7: 무제한 논리 모순(무제한인데 수치가 함께 존재)
    if bool(row.get("data_unlimited")) and mb is not None and not (isinstance(mb, float) and pd.isna(mb)):
        reasons.append("unlimited_with_value")

    # 확장 규칙(callable(row)->reason|None)
    for rule in config.extra_rules:
        result = rule(row)
        if result:
            reasons.append(result)

    return reasons


def quarantine_invalid(
    frame: pd.DataFrame, config: TransformConfig | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """규칙기반 품질 검증으로 유효/무효를 분리한다.

    하위호환: config 없이 호출하면 기본 규칙으로 동작한다.
    """
    if config is None:
        config = TransformConfig(reference_dir=Path("."))
    if frame.empty:
        return frame.copy(), frame.copy()

    reasons_series = frame.apply(lambda row: _row_reasons(row, config), axis=1)

    # R8: 중복 자연키 (vendor, plan_id)
    if {"vendor", "plan_id"}.issubset(frame.columns):
        dup_mask = frame.duplicated(subset=["vendor", "plan_id"], keep="first")
        reasons_series = [
            (r + ["duplicate_natural_key"]) if dup else r
            for r, dup in zip(reasons_series, dup_mask)
        ]

    reasons_list = list(reasons_series)
    valid_mask = [len(r) == 0 for r in reasons_list]

    valid = frame[pd.Series(valid_mask, index=frame.index)].copy()
    invalid = frame[~pd.Series(valid_mask, index=frame.index)].copy()
    invalid["quarantine_reasons"] = [
        "|".join(r) for r, ok in zip(reasons_list, valid_mask) if not ok
    ]
    return valid, invalid


def transform(path: Path, config: TransformConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    records = list(load_jsonl(path))
    frame = pd.DataFrame.from_records(records)
    frame = normalize_units(frame)
    frame = apply_reference_mappings(frame, config)
    valid, invalid = quarantine_invalid(frame, config)
    return valid, invalid
