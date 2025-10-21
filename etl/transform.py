"""Transformation utilities that standardize raw collector outputs."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List

import pandas as pd


@dataclass(slots=True)
class TransformConfig:
    reference_dir: Path


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
        frame["monthly_fee"] = frame["monthly_fee"].astype(float)
    return frame


def apply_reference_mappings(frame: pd.DataFrame, config: TransformConfig) -> pd.DataFrame:
    mapping_path = config.reference_dir / "vendor_mapping.csv"
    if mapping_path.exists():
        mapping = pd.read_csv(mapping_path)
        frame = frame.merge(mapping, how="left", left_on="vendor", right_on="source_vendor")
        frame["vendor"] = frame["canonical_vendor"].fillna(frame["vendor"])
        frame.drop(columns=[col for col in ["source_vendor", "canonical_vendor"] if col in frame.columns], inplace=True)
    return frame


def quarantine_invalid(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    required = ["vendor", "plan_id", "name", "monthly_fee", "data_allowance_mb"]
    valid_mask = frame[required].notnull().all(axis=1)
    valid = frame[valid_mask].copy()
    invalid = frame[~valid_mask].copy()
    return valid, invalid


def transform(path: Path, config: TransformConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    records = list(load_jsonl(path))
    frame = pd.DataFrame.from_records(records)
    frame = normalize_units(frame)
    frame = apply_reference_mappings(frame, config)
    valid, invalid = quarantine_invalid(frame)
    return valid, invalid
