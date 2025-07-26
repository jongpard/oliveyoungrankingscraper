import requests
from bs4 import BeautifulSoup
import json, os
from datetime import datetime

# Olive Young 랭킹 페이지 URL을 카테고리별로 설정합니다.
categories = {
    "전체": "https://www.oliveyoung.co.kr/store/main/getBestCollection?topCategoryNo=100000&categoryDetailNo=200000",  # 예시 URL
    # 다른 카테고리도 필요시 추가하세요
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    )
}

# 크롤링할 순위 개수
TOP_N = 100

def scrape_category(name: str, url: str, top_n: int = TOP_N) -> list:
    """
    주어진 카테고리 URL에서 top_n 상품을 추출합니다.
    반환 형식: [{"rank":1, "title":..., "price":..., "link":...}, ...]
    """
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    items = soup.select(".prd_list .prd_item")[:top_n]
    products = []

    for idx, item in enumerate(items, start=1):
        title_el = item.select_one(".info_area .name")
        price_el = item.select_one(".info_area .price")
        link_el  = item.select_one("a")

        title = title_el.get_text(strip=True) if title_el else ""
        price = price_el.get_text(strip=True) if price_el else ""
        href  = link_el["href"] if link_el and link_el.has_attr("href") else ""
        link  = f"https://www.oliveyoung.co.kr{href}" if href.startswith("/") else href

        products.append({
            "rank": idx,
            "title": title,
            "price": price,
            "link": link
        })

    return products


def main():
    # 오늘 날짜 데이터 구조
    data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "categories": {}
    }

    # 카테고리별 크롤링
    for name, url in categories.items():
        data["categories"][name] = scrape_category(name, url)

    # 결과 저장
    os.makedirs("data", exist_ok=True)
    filename = f"data/ranking_{data['date']}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✔️ Ranking data saved to {filename}")


if __name__ == "__main__":
    main()
