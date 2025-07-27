# scraper.py
import asyncio
from playwright.async_api import async_playwright

async def scrape_oliveyoung():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://www.oliveyoung.co.kr/store/main/main.do")

        # BEST 랭킹 탭 클릭
        await page.click("text=랭킹")

        # 데이터 기다리기
        await page.wait_for_selector(".prd_info", timeout=10000)

        elements = await page.query_selector_all(".prd_info")

        data = []
        for el in elements[:10]:  # 상위 10개만
            title_el = await el.query_selector(".tx_name")
            price_el = await el.query_selector(".price")
            title = await title_el.inner_text() if title_el else "상품명 없음"
            price = await price_el.inner_text() if price_el else "가격 없음"
            data.append({"title": title.strip(), "price": price.strip()})

        await browser.close()
        return data

# GitHub Actions용 entry point
def scrape():
    return asyncio.run(scrape_oliveyoung())
