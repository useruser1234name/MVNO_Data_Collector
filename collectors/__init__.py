"""Collector framework package."""

from .base import BaseCollector, CollectorConfig
from .policy import FieldPolicySet, FieldPolicy, SelectorOption, load_policy_file
from .registry import registry

__all__ = [
    "BaseCollector",
    "CollectorConfig",
    "FieldPolicySet",
    "FieldPolicy",
    "SelectorOption",
    "load_policy_file",
    "registry",
]
