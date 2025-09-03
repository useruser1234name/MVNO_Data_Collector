import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        # 브라우저 실행 (화면 띄움)
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        # URL 기록 함수
        async def log_url():
            print("현재 URL:", page.url)
            with open("visited_urls.txt", "a", encoding="utf-8") as f:
                f.write(page.url + "\n")

        # 사용자가 직접 이동할 때 URL 자동 기록
        page.on("framenavigated", lambda frame: asyncio.create_task(log_url()))

        print("브라우저가 열렸습니다. 직접 탐색하세요.")
        print("탐색한 URL은 visited_urls.txt 파일에 기록됩니다.")

        # 사용자가 직접 쓸 수 있도록 무한 대기
        await asyncio.sleep(3600)  # 1시간 동안 열어두기 (필요시 늘리거나 줄이세요)
        await browser.close()

asyncio.run(main())
