"""Field selection policies that map vendor HTML structures to standard columns."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List


@dataclass(slots=True)
class SelectorOption:
    """Represents a single DOM selector/attribute pair for a column."""

    selector: str
    attribute: str | None = None
    label: str | None = None
    reason: str | None = None

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> "SelectorOption":
        if "selector" not in mapping:
            raise ValueError("Selector mapping requires a 'selector' field")
        return cls(
            selector=str(mapping["selector"]),
            attribute=mapping.get("attribute"),
            label=mapping.get("label"),
            reason=mapping.get("reason"),
        )


@dataclass(slots=True)
class FieldPolicy:
    """Policies for transforming vendor specific selectors into a column."""

    column: str
    selectors: list[SelectorOption] = field(default_factory=list)

    def iter_selectors(self) -> Iterator[SelectorOption]:
        """Yield selectors ordered as declared in the policy."""
        return iter(self.selectors)

    @classmethod
    def from_mapping(cls, column: str, mappings: Iterable[dict[str, Any]]) -> "FieldPolicy":
        selectors: List[SelectorOption] = []
        for mapping in mappings:
            if not isinstance(mapping, dict):
                raise ValueError(
                    f"Selector entry for column '{column}' must be an object with selector details"
                )
            selectors.append(SelectorOption.from_mapping(mapping))
        if not selectors:
            raise ValueError(f"Field policy for column '{column}' must define at least one selector")
        return cls(column=column, selectors=selectors)


@dataclass(slots=True)
class FieldPolicySet:
    """Collection of field policies for a single collector/vendor."""

    vendor: str
    fields: dict[str, FieldPolicy]

    def selectors_for(self, column: str) -> list[SelectorOption]:
        """Return the selector options for a target column."""
        policy = self.fields.get(column)
        if not policy:
            return []
        return list(policy.iter_selectors())

    def describe(self) -> list[dict[str, str | None]]:
        """Provide a tabular view of column-selector relationships for reporting."""
        rows: list[dict[str, str | None]] = []
        for column, policy in sorted(self.fields.items()):
            for option in policy.iter_selectors():
                rows.append(
                    {
                        "vendor": self.vendor,
                        "column": column,
                        "selector": option.selector,
                        "attribute": option.attribute,
                        "label": option.label,
                        "reason": option.reason,
                    }
                )
        return rows

    @classmethod
    def from_mapping(cls, vendor: str, mapping: dict[str, Any]) -> "FieldPolicySet":
        fields: dict[str, FieldPolicy] = {}
        for column, selectors in mapping.items():
            if not isinstance(selectors, Iterable) or isinstance(selectors, (str, bytes)):
                raise ValueError(
                    f"Policy definition for column '{column}' in vendor '{vendor}' must be a list of selector objects"
                )
            fields[column] = FieldPolicy.from_mapping(column, selectors)
        return cls(vendor=vendor, fields=fields)


def load_policy_file(path: Path) -> dict[str, FieldPolicySet]:
    """Load field policies from a JSON file."""
    try:
        data: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in policy file '{path}': {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Policy file must contain a JSON object mapping vendors to policies")
    policies: dict[str, FieldPolicySet] = {}
    for vendor, mapping in data.items():
        if not isinstance(mapping, dict):
            raise ValueError(
                f"Policy for vendor '{vendor}' must be an object mapping columns to selector lists"
            )
        policies[vendor] = FieldPolicySet.from_mapping(vendor, mapping)
    return policies
