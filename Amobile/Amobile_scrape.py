import asyncio
import csv
import json
import re
from pathlib import Path
from collections import defaultdict, Counter
from typing import Dict, List, Tuple, Set
from urllib.parse import urljoin

from playwright.async_api import async_playwright
from bs4 import BeautifulSoup


# -------------------------------
# 기본 설정
# -------------------------------
base_website_uniform_resource_locator: str = "https://www.amobile.co.kr"
plan_list_page_uniform_resource_locator: str = f"{base_website_uniform_resource_locator}/plan#24"

output_html_directory_path: Path = Path("amobile_detail_html")
output_html_directory_path.mkdir(parents=True, exist_ok=True)

output_comma_separated_values_file_path: Path = Path("amobile_detail_by_class.csv")
output_metadata_json_file_path: Path = Path("amobile_detail_meta.json")

run_headless_browser: bool = True
navigation_timeout_milliseconds: int = 20000
inter_request_pause_seconds: float = 0.8  # 서버 부담 줄이기

# CSV 컬럼 폭 제한을 막기 위해 너무 드문 클래스는 제외
minimum_class_support_threshold: int = 2

# 클래스 포함/제외 정규식 (필요 시 조정)
include_class_name_regular_expression = None
exclude_class_name_regular_expression = re.compile(r"^\s*$")  # 공백 클래스 제외

plan_identifier_regular_expression = re.compile(r"/plan/(\d+)")


# -------------------------------
# 유틸리티
# -------------------------------
def make_safe_filename_slug(raw_text: str) -> str:
    safe_text = re.sub(r"[^a-zA-Z0-9._-]+", "_", raw_text).strip("_")[:120]
    return safe_text or "page"


def extract_text_grouped_by_css_class(html_source_text: str) -> Dict[str, str]:
    """
    상세 페이지 HTML을 파싱하여 CSS 클래스별 텍스트를 수집합니다.
    - 동일 클래스의 모든 요소 텍스트를 ' | '로 이어 붙입니다.
    - 다중 클래스 요소는 각 클래스 이름에 동일 텍스트를 누적합니다.
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
                continue
            current_element_class_names.append(single_class_name)

        if not current_element_class_names:
            continue

        element_text_content: str = element_node.get_text(" ", strip=True)
        if not element_text_content:
            continue

        for single_class_name in current_element_class_names:
            class_name_to_texts_mapping[single_class_name].append(element_text_content)

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


# -------------------------------
# 서브탭 전환 및 링크 수집
# -------------------------------
async def compute_current_plan_hypertext_references(playwright_page) -> List[str]:
    """
    현재 DOM에서 .plan_list_box 내부의 모든 /plan/ 링크 hypertext reference(href)를 수집하여
    정렬된 리스트로 반환합니다(센티널 비교용).
    """
    hypertext_reference_list = await playwright_page.eval_on_selector_all(
        ".plan_list_box a[href^='/plan/']",
        "nodes => nodes.map(n => n.getAttribute('href'))"
    )
    cleaned_hypertext_reference_list: List[str] = []
    for hypertext_reference in hypertext_reference_list:
        if not hypertext_reference:
            continue
        cleaned_value = hypertext_reference.split("?", 1)[0]
        cleaned_hypertext_reference_list.append(cleaned_value)
    unique_sorted_hypertext_references = sorted(set(cleaned_hypertext_reference_list))
    return unique_sorted_hypertext_references


async def wait_for_postback_dom_change(playwright_page, hypertext_references_before: List[str], timeout_milliseconds: int = 15000):
    """
    ASP.NET 포스트백 이후 목록이 실제로 바뀌었는지
    .plan_list_box 내 /plan/ 링크 집합 비교로 확인합니다.
    """
    await playwright_page.wait_for_function(
        """(beforeList) => {
            const nodes = Array.from(document.querySelectorAll(".plan_list_box a[href^='/plan/']"));
            const after = nodes.map(n => (n.getAttribute('href') || '').split('?')[0]).filter(Boolean);
            const uniq = Array.from(new Set(after)).sort();
            const before = Array.from(new Set(beforeList || [])).sort();
            return JSON.stringify(uniq) !== JSON.stringify(before);
        }""",
        arg=hypertext_references_before,
        timeout=timeout_milliseconds
    )


async def ensure_carrier_tab_and_collect_links(playwright_page, carrier_label_text: str, input_element_identifier: str) -> List[Dict]:
    """
    특정 통신사 서브탭(라디오)을 선택한 상태에서
    모든 .plan_list_box 내 /plan/ 링크를 절대 경로로 수집합니다.
    """
    hypertext_references_before = await compute_current_plan_hypertext_references(playwright_page)

    is_checked_now: bool = await playwright_page.eval_on_selector(
        f"#{input_element_identifier}",
        "el => !!el && el.checked"
    )

    if not is_checked_now:
        await playwright_page.click(f"label[for='{input_element_identifier}']")
        try:
            await wait_for_postback_dom_change(playwright_page, hypertext_references_before, timeout_milliseconds=15000)
        except Exception:
            # 변경 감지가 실패하면 네트워크 대기 후 진행
            await playwright_page.wait_for_load_state("load", timeout=8000)

    if inter_request_pause_seconds:
        await playwright_page.wait_for_timeout(int(inter_request_pause_seconds * 1000))

    container_elements = await playwright_page.query_selector_all(".plan_list_box")
    collected_link_rows: List[Dict] = []

    for container_index, container_element in enumerate(container_elements):
        anchor_elements = await container_element.query_selector_all("a[href^='/plan/']")
        for anchor_element in anchor_elements:
            relative_hypertext_reference_value: str | None = await anchor_element.get_attribute("href")
            if not relative_hypertext_reference_value:
                continue
            relative_hypertext_reference_value = relative_hypertext_reference_value.split("?", 1)[0]
            absolute_uniform_resource_locator_value: str = urljoin(
                base_website_uniform_resource_locator,
                relative_hypertext_reference_value
            )

            plan_identifier_match = plan_identifier_regular_expression.search(relative_hypertext_reference_value)
            plan_identifier_value: str = plan_identifier_match.group(1) if plan_identifier_match else ""

            collected_link_rows.append({
                "carrier_label": carrier_label_text,
                "container_index": container_index,
                "relative_hypertext_reference": relative_hypertext_reference_value,
                "absolute_uniform_resource_locator": absolute_uniform_resource_locator_value,
                "plan_identifier": plan_identifier_value,
            })

    return collected_link_rows


async def collect_all_plan_links_from_both_carriers(playwright_page) -> List[Dict]:
    """
    KT / LGU+ 서브탭을 각각 선택하여 링크를 모두 수집합니다.
    """
    all_rows: List[Dict] = []

    # KT
    all_rows.extend(
        await ensure_carrier_tab_and_collect_links(
            playwright_page=playwright_page,
            carrier_label_text="KT",
            input_element_identifier="ctl00_ContentPlaceHolder1_rbl통신사_0",
        )
    )

    # LGU+
    all_rows.extend(
        await ensure_carrier_tab_and_collect_links(
            playwright_page=playwright_page,
            carrier_label_text="LGU+",
            input_element_identifier="ctl00_ContentPlaceHolder1_rbl통신사_1",
        )
    )

    # 중복 제거: (carrier_label, plan_identifier or absolute_uniform_resource_locator) 기준
    deduplicated_rows: Dict[Tuple[str, str], Dict] = {}
    for row in all_rows:
        deduplication_key = (row["carrier_label"], row["plan_identifier"] or row["absolute_uniform_resource_locator"])
        if deduplication_key not in deduplicated_rows:
            deduplicated_rows[deduplication_key] = row

    return list(deduplicated_rows.values())


# -------------------------------
# 상세 페이지 접근 및 클래스별 텍스트 추출
# -------------------------------
async def crawl_detail_pages_and_collect_class_texts(playwright_browser_context, collected_link_rows: List[Dict]) -> Tuple[List[Dict], Counter]:
    """
    각 상세 URL에 접속하여 HTML 저장 + 클래스별 텍스트 집계.
    - networkidle 대기를 쓰지 않고, domcontentloaded + body 센티널로 수집합니다.
    - 실패 시 1회 재시도합니다.
    """
    detail_page_records: List[Dict] = []
    class_name_support_counter: Counter = Counter()

    async def fetch_detail_html_with_fallback(uniform_resource_locator: str) -> str | None:
        page = await playwright_browser_context.new_page()
        try:
            # 1차 시도: domcontentloaded + body 존재 확인
            await page.goto(
                uniform_resource_locator,
                wait_until="domcontentloaded",
                referer=plan_list_page_uniform_resource_locator
            )
            await page.wait_for_selector("body", timeout=5000)
            await page.wait_for_timeout(600)
            html_text = await page.content()
            return html_text
        except Exception:
            # 2차 시도: load까지 대기
            try:
                await page.goto(
                    uniform_resource_locator,
                    wait_until="load",
                    referer=plan_list_page_uniform_resource_locator,
                    timeout=15000
                )
                await page.wait_for_selector("body", timeout=5000)
                await page.wait_for_timeout(600)
                html_text = await page.content()
                return html_text
            except Exception:
                return None
        finally:
            await page.close()

    for index_value, link_row in enumerate(collected_link_rows, start=1):
        detail_page_uniform_resource_locator: str = link_row["absolute_uniform_resource_locator"]
        carrier_label_text: str = link_row["carrier_label"]
        plan_identifier_value: str = link_row["plan_identifier"] or str(index_value)

        html_source_text: str | None = await fetch_detail_html_with_fallback(detail_page_uniform_resource_locator)
        if not html_source_text:
            print(f"[경고] 상세 페이지 이동 실패(최종): {detail_page_uniform_resource_locator}")
            await asyncio.sleep(inter_request_pause_seconds)
            continue

        # HTML 원본 저장
        html_filename = f"{make_safe_filename_slug(carrier_label_text)}__{make_safe_filename_slug(plan_identifier_value)}.html"
        (output_html_directory_path / html_filename).write_text(html_source_text, encoding="utf-8")

        # 클래스별 텍스트 추출
        class_name_to_joined_text_mapping: Dict[str, str] = extract_text_grouped_by_css_class(html_source_text)
        for class_name in class_name_to_joined_text_mapping.keys():
            class_name_support_counter[class_name] += 1

        record_for_current_page: Dict[str, str] = {
            "carrier_label": carrier_label_text,
            "plan_identifier": plan_identifier_value,
            "detail_page_uniform_resource_locator": detail_page_uniform_resource_locator,
        }
        record_for_current_page.update(class_name_to_joined_text_mapping)
        detail_page_records.append(record_for_current_page)

        await asyncio.sleep(inter_request_pause_seconds)

    return detail_page_records, class_name_support_counter


def write_records_to_comma_separated_values_file(detail_page_records: List[Dict], class_name_support_counter: Counter):
    """
    클래스명을 CSV 컬럼으로 확장하여 저장합니다.
    너무 드문 클래스는 minimum_class_support_threshold 기준으로 제외합니다.
    """
    base_column_names: List[str] = ["carrier_label", "plan_identifier", "detail_page_uniform_resource_locator"]

    # 전체 클래스 후보 수집
    all_class_column_candidates: Set[str] = set()
    for single_record in detail_page_records:
        for key_name in single_record.keys():
            if key_name not in base_column_names:
                all_class_column_candidates.add(key_name)

    # 임계치 필터링
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

    # 메타 저장
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


# -------------------------------
# 메인 실행
# -------------------------------
async def main():
    async with async_playwright() as playwright_instance:
        playwright_browser = await playwright_instance.chromium.launch(headless=run_headless_browser)
        playwright_browser_context = await playwright_browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            extra_http_headers={
                "Referer": plan_list_page_uniform_resource_locator.split("#", 1)[0],
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            },
        )

        # 무거운 리소스는 차단(텍스트만 필요)
        await playwright_browser_context.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in {"image", "font", "media"}
            else route.continue_()
        )

        playwright_page = await playwright_browser_context.new_page()
        playwright_page.set_default_timeout(navigation_timeout_milliseconds)

        # 리스트 페이지 진입
        await playwright_page.goto(plan_list_page_uniform_resource_locator, wait_until="domcontentloaded")
        await playwright_page.wait_for_selector(".plan_list_box", timeout=15000)

        # 서브탭별 모든 링크 수집
        collected_link_rows: List[Dict] = await collect_all_plan_links_from_both_carriers(playwright_page)
        print(f"[정보] 상세 페이지 링크 {len(collected_link_rows)}건 수집")

        # 상세 페이지 크롤링 + 클래스별 텍스트 컬럼화
        detail_page_records, class_name_support_counter = await crawl_detail_pages_and_collect_class_texts(
            playwright_browser_context, collected_link_rows
        )

        await playwright_browser.close()

    # CSV / 메타 저장
    write_records_to_comma_separated_values_file(detail_page_records, class_name_support_counter)


if __name__ == "__main__":
    asyncio.run(main())
