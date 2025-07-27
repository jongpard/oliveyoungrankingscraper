# scraper.py
import asyncio
from playwright.async_api import async_playwright

async def scrape_oliveyoung():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://www.oliveyoung.co.kr/store/main/main.do")

        # '랭킹' 탭 클릭 (동적 로딩 대응)
        await page.click("text=랭킹")
        await page.wait_for_timeout(3000)  # 충분한 로딩 대기

        await page.wait_for_selector(".prd_info", timeout=10000)
        items = await page.query_selector_all(".prd_info")

        data = []
        for item in items[:10]:
            name = await item.query_selector(".tx_name")
            price = await item.query_selector(".price")

            name_text = await name.inner_text() if name else "이름 없음"
            price_text = await price.inner_text() if price else "가격 없음"

            data.append({
                "title": name_text.strip(),
                "price": price_text.strip()
            })

        await browser.close()
        return data

def scrape():
    return asyncio.run(scrape_oliveyoung())
