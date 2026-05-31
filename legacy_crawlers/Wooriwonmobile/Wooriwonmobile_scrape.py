import asyncio
import csv
import json
import re
from pathlib import Path
from collections import defaultdict, Counter
from typing import Dict, List, Tuple, Set

from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

# ---- 기본 설정 ----
base_website_address: str = "https://www.wooriwonmobile.com"
rate_plan_list_page_address: str = f"{base_website_address}/rate-plan/list"

# LTE/5G 매핑 (detail/{network_path_segment}/{plan_identifier} 에서 network_path_segment가 '01/01' 또는 '01/02')
network_type_to_path_segment_mapping: Dict[str, str] = {"LTE": "01/01", "5G": "01/02"}

# 출력 경로
output_html_directory_path: Path = Path("wooriwon_detail_html")
output_html_directory_path.mkdir(parents=True, exist_ok=True)
output_comma_separated_values_file_path: Path = Path("wooriwon_detail_by_class.csv")
output_metadata_json_file_path: Path = Path("wooriwon_detail_meta.json")

# 크롤링 옵션
run_headless_browser: bool = True
navigation_timeout_milliseconds: int = 20000
maximum_list_pages_to_visit: int | None = None  # None 이면 제한 없음
inter_request_pause_seconds: float = 0.3

# CSV 폭 제한을 막기 위해, 너무 드문 클래스는 제외 (예: 2페이지 이상에서 등장한 클래스만 컬럼으로)
minimum_class_support_threshold: int = 2

# 클래스 이름 필터 (포함/제외) — 필요 시 수정
include_class_name_regular_expression = None  # 예: re.compile(r"^(plan-name|plan-volumn|price|saleprice|Badge_.*)$")
exclude_class_name_regular_expression = re.compile(r"^\s*$")  # 공백 클래스 제외


def detect_network_type_path_segment(text_value: str | None) -> str | None:
    """텍스트에서 LTE/5G 식별 → '01/01' 또는 '01/02' 반환"""
    if not text_value:
        return None
    upper_text_value: str = text_value.upper()
    for network_label, path_segment in network_type_to_path_segment_mapping.items():
        if network_label in upper_text_value:
            return path_segment
    return None


async def extract_cards_on_list_page(playwright_page) -> Tuple[List[Dict], str | None]:
    """
    리스트 페이지에서 카드 정보 추출
    반환 레코드 예시:
      {
        "plan_identifier": "PD00006004",
        "network_path_segment": "01/01",
        "detail_page_address": "https://.../detail/01/01/PD00006004",
        "plan_name": "...",
        "plan_price": "..."
      }
    """
    await playwright_page.wait_for_selector(".cardplan--wrap .cardplanitem")
    card_elements = await playwright_page.query_selector_all(".cardplan--wrap .cardplanitem")
    extracted_results: List[Dict] = []

    # 탭/필터에서 망 타입 힌트
    active_tab_text_hint: str | None = None
    try:
        active_tab_element = await playwright_page.query_selector('[aria-selected="true"], [role="tab"][aria-current="page"]')
        if active_tab_element:
            active_tab_text_hint = (await active_tab_element.inner_text()).strip()
    except Exception:
        active_tab_text_hint = None

    for single_card_element in card_elements:
        raw_element_identifier: str | None = await single_card_element.get_attribute("id")  # 예: "cardplanitem-PD00006004"
        if not raw_element_identifier:
            continue
        plan_identifier: str = raw_element_identifier.replace("cardplanitem-", "")

        # 카드 내부에서 LTE/5G 텍스트 힌트
        first_benefit_text: str | None = None
        try:
            first_benefit_element = await single_card_element.query_selector(".plan-benefit li:first-child")
            if first_benefit_element:
                first_benefit_text = (await first_benefit_element.inner_text()).strip()
        except Exception:
            pass

        network_path_segment: str = (
            detect_network_type_path_segment(first_benefit_text)
            or detect_network_type_path_segment(active_tab_text_hint)
            or "01/01"  # 기본값: LTE
        )

        detail_page_address: str = f"{base_website_address}/rate-plan/detail/{network_path_segment}/{plan_identifier}"

        # 메타(선택)
        plan_name_element = await single_card_element.query_selector(".plan-area .plan-name")
        plan_name_text: str = (await plan_name_element.inner_text()).strip() if plan_name_element else ""
        plan_price_element = await single_card_element.query_selector(".price-info .price strong")
        plan_price_text: str = (await plan_price_element.inner_text()).strip() if plan_price_element else ""

        extracted_results.append({
            "plan_identifier": plan_identifier,
            "network_path_segment": network_path_segment,
            "detail_page_address": detail_page_address,
            "plan_name": plan_name_text,
            "plan_price": plan_price_text,
        })

    first_card_plan_identifier: str | None = extracted_results[0]["plan_identifier"] if extracted_results else None
    return extracted_results, first_card_plan_identifier


async def iterate_rate_plan_list_pages(playwright_page) -> List[Dict]:
    """리스트 페이지네이션을 돌며 모든 상세 URL 후보 수집"""
    collected_rows: List[Dict] = []
    seen_plan_identifier_set: Set[str] = set()

    visited_page_count: int = 0
    while True:
        visited_page_count += 1
        extracted_rows, first_plan_identifier_before = await extract_cards_on_list_page(playwright_page)

        for single_row in extracted_rows:
            if single_row["plan_identifier"] not in seen_plan_identifier_set:
                seen_plan_identifier_set.add(single_row["plan_identifier"])
                collected_rows.append(single_row)

        if maximum_list_pages_to_visit and visited_page_count >= maximum_list_pages_to_visit:
            break

        # 다음 버튼
        next_page_button_element = await playwright_page.query_selector('button[class^="Pagination_next__"]')
        if not next_page_button_element:
            break
        next_button_disabled_attribute = await next_page_button_element.get_attribute("disabled")
        if next_button_disabled_attribute is not None:
            break

        if not first_plan_identifier_before:
            break

        await next_page_button_element.click()
        try:
            await playwright_page.wait_for_function(
                """(firstId) => {
                    const element = document.querySelector('.cardplan--wrap .cardplanitem');
                    if (!element) return false;
                    const planId = (element.id || '').replace('cardplanitem-','');
                    return planId && planId !== firstId;
                }""",
                arg=first_plan_identifier_before,
                timeout=10000
            )
        except Exception:
            break

        if inter_request_pause_seconds:
            await playwright_page.wait_for_timeout(int(inter_request_pause_seconds * 1000))

    return collected_rows


def make_safe_filename_slug(raw_text: str) -> str:
    safe_text = re.sub(r"[^a-zA-Z0-9._-]+", "_", raw_text).strip("_")[:120]
    return safe_text or "page"


def extract_text_grouped_by_css_class(html_source_text: str) -> Dict[str, str]:
    """
    상세 페이지 HTML을 파싱해 class별 텍스트를 수집.
    - 동일 CSS 클래스에 속한 모든 요소의 텍스트를 ' | '로 이어 붙임.
    - 클래스 이름은 공백 분리된 개별 클래스 단위로 카운트.
    """
    beautiful_soup_object = BeautifulSoup(html_source_text, "lxml")
    class_name_to_texts_mapping: Dict[str, List[str]] = defaultdict(list)

    for element_node in beautiful_soup_object.find_all(class_=True):
        current_element_class_names: List[str] = []
        for single_class_name in element_node.get("class", []):
            single_class_name = single_class_name.strip()
            if not single_class_name:
                continue
            if exclude_class_name_regular_expression and exclude_class_name_regular_expression.search(single_class_name):
                continue
            if include_class_name_regular_expression and not include_class_name_regular_expression.search(single_class_name):
                # 포함 필터가 지정되면, 해당 패턴에 매칭되는 클래스만 포함
                continue
            current_element_class_names.append(single_class_name)

        if not current_element_class_names:
            continue

        element_text_content: str = element_node.get_text(" ", strip=True)
        if not element_text_content:
            continue

        for single_class_name in current_element_class_names:
            class_name_to_texts_mapping[single_class_name].append(element_text_content)

    # 중복 텍스트 제거 및 조인
    class_name_to_joined_text_mapping: Dict[str, str] = {}
    for class_name, text_items in class_name_to_texts_mapping.items():
        unique_texts: List[str] = []
        seen_text_set: Set[str] = set()
        for single_text in text_items:
            normalized_text = single_text.strip()
            if normalized_text and normalized_text not in seen_text_set:
                seen_text_set.add(normalized_text)
                unique_texts.append(normalized_text)
        class_name_to_joined_text_mapping[class_name] = " | ".join(unique_texts)

    return class_name_to_joined_text_mapping


async def crawl_detail_pages_and_collect_class_texts(playwright_browser_context, collected_list_rows: List[Dict]) -> Tuple[List[Dict], Counter]:
    """
    상세 페이지에 접속해 HTML 저장 + class별 텍스트 맵 생성.
    반환:
      - detail_page_records: 각 페이지별 {plan_identifier, network_path_segment, detail_page_address, ...class-cols}
      - class_name_support_counter: 클래스 등장 페이지 수 카운터
    """
    detail_page_records: List[Dict] = []
    class_name_support_counter: Counter = Counter()

    for single_row in collected_list_rows:
        playwright_page = await playwright_browser_context.new_page()
        playwright_page.set_default_timeout(navigation_timeout_milliseconds)
        detail_page_address: str = single_row["detail_page_address"]

        try:
            await playwright_page.goto(detail_page_address, wait_until="domcontentloaded")
            # 콘텐츠 충분 로드 대기 (필요 시 선택자 조건 추가 가능)
            await playwright_page.wait_for_load_state("networkidle", timeout=8000)
        except Exception as navigation_exception:
            print(f"[경고] 상세 페이지 이동 실패: {detail_page_address} -> {navigation_exception}")
            await playwright_page.close()
            continue

        html_source_text: str = await playwright_page.content()
        await playwright_page.close()

        # 원본 HTML 저장
        output_html_filename: str = f"{make_safe_filename_slug(single_row['network_path_segment'])}__{make_safe_filename_slug(single_row['plan_identifier'])}.html"
        (output_html_directory_path / output_html_filename).write_text(html_source_text, encoding="utf-8")

        # class별 텍스트 추출
        class_name_to_joined_text_mapping: Dict[str, str] = extract_text_grouped_by_css_class(html_source_text)

        # 클래스 등장 페이지 카운터
        for class_name in class_name_to_joined_text_mapping.keys():
            class_name_support_counter[class_name] += 1

        record_for_current_page: Dict[str, str] = {
            "plan_identifier": single_row["plan_identifier"],
            "network_path_segment": single_row["network_path_segment"],
            "detail_page_address": detail_page_address,
        }
        record_for_current_page.update(class_name_to_joined_text_mapping)
        detail_page_records.append(record_for_current_page)

    return detail_page_records, class_name_support_counter


def write_records_to_comma_separated_values_file(detail_page_records: List[Dict], class_name_support_counter: Counter):
    """
    detail_page_records의 모든 class 키를 합쳐 CSV 헤더 구성.
    - 너무 드문 클래스는 제외(minimum_class_support_threshold 기준)
    """
    base_column_names: List[str] = ["plan_identifier", "network_path_segment", "detail_page_address"]

    # 클래스 후보 수집
    all_class_column_candidates: Set[str] = set()
    for single_record in detail_page_records:
        for key_name in single_record.keys():
            if key_name not in base_column_names:
                all_class_column_candidates.add(key_name)

    # 지원 임계치 필터링
    if minimum_class_support_threshold and minimum_class_support_threshold > 1:
        filtered_class_column_names: List[str] = [
            class_name
            for class_name in all_class_column_candidates
            if class_name_support_counter.get(class_name, 0) >= minimum_class_support_threshold
        ]
    else:
        filtered_class_column_names = list(all_class_column_candidates)

    # 정렬: 출현 빈도 → 이름
    filtered_class_column_names.sort(key=lambda class_name: (-class_name_support_counter.get(class_name, 0), class_name))

    final_header_column_names: List[str] = base_column_names + filtered_class_column_names

    with output_comma_separated_values_file_path.open("w", newline="", encoding="utf-8-sig") as file_handle:
        csv_writer = csv.writer(file_handle)
        csv_writer.writerow(final_header_column_names)
        for single_record in detail_page_records:
            row_values: List[str] = [single_record.get(column_name, "") for column_name in final_header_column_names]
            csv_writer.writerow(row_values)

    # 메타 저장 (어떤 클래스가 몇 페이지에서 등장했는지)
    metadata_object = {
        "total_record_count": len(detail_page_records),
        "class_name_support_counts": class_name_support_counter.most_common(),
        "minimum_class_support_threshold": minimum_class_support_threshold,
        "csv_header_columns": final_header_column_names,
    }
    output_metadata_json_file_path.write_text(json.dumps(metadata_object, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[완료] CSV 저장 위치: {output_comma_separated_values_file_path.resolve()}")
    print(f"[완료] 메타데이터 JSON 저장 위치: {output_metadata_json_file_path.resolve()}")
    print(f"[완료] HTML 저장 디렉터리: {output_html_directory_path.resolve()}")


async def main():
    async with async_playwright() as playwright_instance:
        playwright_browser = await playwright_instance.chromium.launch(headless=run_headless_browser)
        playwright_browser_context = await playwright_browser.new_context()
        playwright_page = await playwright_browser_context.new_page()
        playwright_page.set_default_timeout(navigation_timeout_milliseconds)

        # 리스트 페이지 진입
        await playwright_page.goto(rate_plan_list_page_address, wait_until="domcontentloaded")
        await playwright_page.wait_for_load_state("networkidle", timeout=8000)

        # 상세 URL 후보 수집
        collected_list_rows: List[Dict] = await iterate_rate_plan_list_pages(playwright_page)
        print(f"[정보] 상세 페이지 주소 {len(collected_list_rows)}건 수집")

        # 상세 페이지 크롤링 및 class별 텍스트 집계
        detail_page_records, class_name_support_counter = await crawl_detail_pages_and_collect_class_texts(
            playwright_browser_context, collected_list_rows
        )

        await playwright_browser.close()

    # CSV / 메타 저장
    write_records_to_comma_separated_values_file(detail_page_records, class_name_support_counter)


if __name__ == "__main__":
    asyncio.run(main())
