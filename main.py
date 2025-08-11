from playwright.sync_api import sync_playwright
import json
import datetime

def scrape_oliveyoung():
    url = "https://www.oliveyoung.co.kr/store/main/getBestList.do"
    data = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Cloudflare 우회를 위해 브라우저처럼 접근
        page.goto(url, timeout=60000)

        # 랭킹 아이템 추출
        items = page.locator("ul.cate_prd_list li").all()

        for idx, item in enumerate(items, start=1):
            title = item.locator(".tx_name").inner_text()
            price = item.locator(".tx_cur").inner_text()
            link = item.locator("a").get_attribute("href")
            data.append({
                "rank": idx,
                "title": title.strip(),
                "price": price.strip(),
                "link": f"https://www.oliveyoung.co.kr{link}"
            })

        browser.close()

    # 결과 저장
    today = datetime.date.today().isoformat()
    with open(f"ranking_{today}.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return data

if __name__ == "__main__":
    results = scrape_oliveyoung()
    print(json.dumps(results, ensure_ascii=False, indent=2))
