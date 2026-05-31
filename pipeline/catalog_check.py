"""카탈로그 ↔ 레지스트리 정합성 검증 (CI 게이트).

- 카탈로그에서 수집기 등록이 필요한(stub 외) 사업자는 실제 registry에 등록돼야 한다.
- registry에 등록된 수집기는 example을 제외하고 카탈로그에 선언돼야 한다.
불일치 시 비정상 종료(코드 1)하여 PR에서 차단한다.
"""
from __future__ import annotations

import logging
import sys

from collectors.catalog import load_catalog
from collectors.registry import registry
from pipeline.run_collectors import discover_collectors

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# 카탈로그 선언 없이 존재해도 되는 수집기(테스트 스텁 등)
REGISTRY_ONLY_ALLOWED = {"example"}


def check() -> list[str]:
    discover_collectors()
    catalog = load_catalog()
    registered = set(registry.available())
    catalog_keys = {e.key for e in catalog.all()}
    problems: list[str] = []

    # 1) enabled 이고 등록이 필요한 카탈로그 항목이 실제 등록됐는지
    #    (disabled 항목은 향후 구현 예정 스캐폴딩 — 검사 제외)
    for entry in catalog.all():
        if entry.enabled and entry.requires_registered_collector and entry.key not in registered:
            problems.append(
                f"카탈로그 '{entry.key}'({entry.collector_type})에 대응하는 수집기가 등록되지 않음"
            )

    # 2) 등록된 수집기가 카탈로그에 선언됐는지
    for key in registered:
        if key not in catalog_keys and key not in REGISTRY_ONLY_ALLOWED:
            problems.append(f"등록된 수집기 '{key}'가 카탈로그에 선언되지 않음")

    return problems


def main() -> int:
    problems = check()
    if problems:
        for p in problems:
            logger.error("정합성 위반: %s", p)
        return 1
    logger.info("카탈로그 ↔ 레지스트리 정합성 OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
