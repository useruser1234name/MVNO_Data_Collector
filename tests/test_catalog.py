"""Tests for vendor catalog loading, consistency, and dynamic DAG selection."""
import pytest

from collectors.catalog import VendorEntry, load_catalog
from orchestration.dag_factory import dags_to_build
from pipeline.catalog_check import check


def test_catalog_loads():
    cat = load_catalog()
    assert "amobile" in cat.entries
    assert cat.get("amobile").group == "mvno"


def test_enabled_excludes_disabled_and_mno_stub():
    cat = load_catalog()
    enabled_keys = {e.key for e in cat.enabled()}
    assert "example" not in enabled_keys  # stub disabled
    assert "skt" not in enabled_keys  # mno disabled
    assert "amobile" in enabled_keys


def test_dags_to_build_only_registered_enabled():
    cat = load_catalog()
    keys = {e.key for e in dags_to_build(cat)}
    assert keys == {"amobile", "egmobile", "eyagi", "insmobile", "ktmmobile", "uplusumobile"}


def test_mno_group_present_for_future():
    cat = load_catalog()
    mno = {e.key for e in cat.by_group("mno")}
    assert {"skt", "kt", "lguplus"}.issubset(mno)


def test_invalid_group_rejected():
    with pytest.raises(ValueError):
        VendorEntry.from_mapping("x", {"group": "bogus", "collector_type": "requests"})


def test_catalog_registry_consistency():
    # 카탈로그 ↔ 레지스트리 정합성 위반이 없어야 한다
    assert check() == []
