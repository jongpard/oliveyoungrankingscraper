import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime

def scrape_oliveyoung_rankings():
    api_key = os.getenv("SCRAPER_API_KEY")
    if not api_key:
        raise ValueError("SCRAPER_API_KEY is not set in GitHub Secrets.")

    # 이제 데이터 API가 아닌, 사람이 보는 실제 랭킹 페이지 주소를 목표로 합니다.
    target_url = "https://www.oliveyoung.co.kr/store/ranking/getBest.do"

    # '만능 열쇠'(&render=true)를 사용하여, ScraperAPI가 JS를 모두 실행하고 최종 HTML을 가져오도록 합니다.
    scraperapi_url = f'http://api.scraperapi.com?api_key={api_key}&url={target_url}&render=true'

    print("Sending request via ScraperAPI with Browser Rendering enabled...")
    response = requests.get(scraperapi_url, timeout=180) # 렌더링을 위해 타임아웃을 3분으로 넉넉하게 설정

    if response.status_code != 200:
        print(f"❌ ScraperAPI failed with status code: {response.status_code}")
        print(response.text)
        return None

    try:
        # 이제 JSON이 아닌, 최종 결과물인 HTML을 분석합니다.
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 랭킹 리스트의 각 아이템을 선택합니다.
        product_list = soup.select('#rank-best-list .prd_item')
        
        if not product_list:
            raise ValueError("Could not find the product list. The page structure might have changed.")

        top_products = []
        for item in product_list[:100]: # 100위까지만 가져옵니다.
            rank_element = item.select_one('.prd_rank')
            brand_element = item.select_one('.prd_brand')
            name_element = item.select_one('.prd_name')

            if rank_element and brand_element and name_element:
                rank = rank_element.text.strip()
                brand = brand_element.text.strip()
                name = name_element.text.strip()
                top_products.append(f"{rank}. [{brand}] {name}")
            
        return top_products

    except Exception as e:
        print(f"❌ An error occurred during parsing: {e}")
        print("Response from server was (first 500 chars):")
        print(response.text[:500])
        return None

def send_to_slack(message_lines, is_error=False):
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url: return

    text = f"🚨 올리브영 랭킹 수집 실패" if is_error else f"🏆 올리브영 랭킹 Top {len(message_lines[:10])}"
    
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{text}*"}},
        {"type": "divider"},
    ]
    if not is_error and message_lines:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(message_lines[:10])}})
    elif is_error and message_lines:
         blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": message_lines[0]}})

    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}]})

    try:
        requests.post(webhook_url, json={"text": text, "blocks": blocks}, timeout=10).raise_for_status()
        print("✅ Slack message sent successfully")
    except Exception as e:
        print(f"❌ Failed to send Slack message: {e}")

if __name__ == "__main__":
    print("🔍 올리브영 랭킹 수집 시작 (ScraperAPI + HTML Parsing 최종 모드)")
    rankings = scrape_oliveyoung_rankings()

    if rankings:
        print(f"✅ Successfully scraped {len(rankings)} items.")
        send_to_slack(rankings)
    else:
        print("❌ Scraping failed.")
        send_to_slack(["ScraperAPI를 통한 요청 또는 HTML 분석에 실패했습니다."], is_error=True)
