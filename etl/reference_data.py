"""마스터데이터(reference) 로더 및 거버넌스 검증.

reference 디렉터리가 비어 apply_reference_mappings가 조용히 no-op 되던 문제를 막고,
카탈로그 사업자가 모두 dim_operator에 등재돼 있는지 검증한다.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

DEFAULT_REFERENCE_DIR = Path(__file__).resolve().parent / "reference"


@dataclass(slots=True)
class Operator:
    operator_key: str
    display_name: str
    group: str
    network: str
    is_mvno: bool


def load_operators(reference_dir: Path | None = None) -> Dict[str, Operator]:
    reference_dir = reference_dir or DEFAULT_REFERENCE_DIR
    path = reference_dir / "dim_operator.csv"
    operators: Dict[str, Operator] = {}
    with path.open("r", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            operators[row["operator_key"]] = Operator(
                operator_key=row["operator_key"],
                display_name=row["display_name"],
                group=row["group"],
                network=row.get("network", ""),
                is_mvno=str(row.get("is_mvno", "")).strip().lower() == "true",
            )
    return operators


def missing_operators(vendor_keys: List[str], reference_dir: Path | None = None) -> List[str]:
    """주어진 벤더 키 중 dim_operator에 없는 것을 반환(거버넌스 검증용)."""
    operators = load_operators(reference_dir)
    return [k for k in vendor_keys if k not in operators]
