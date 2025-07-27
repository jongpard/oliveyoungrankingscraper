import requests
import json
import os
from datetime import datetime

def scrape_oliveyoung_rankings():
    # '전문 해결사' ScraperAPI의 API 키와 목표 URL을 가져옵니다.
    api_key = os.getenv("SCRAPER_API_KEY")
    target_url = "https://www.oliveyoung.co.kr/store/main/getBestList.do"

    # ScraperAPI에 보낼 올바른 주소 형식입니다.
    # API 키와 목표 URL을 주소에 직접 포함시킵니다.
    scraperapi_url = f'http://api.scraperapi.com?api_key={api_key}&url={target_url}'

    # 올리브영에 보낼 데이터 (이것이 패키지의 내용물입니다)
    target_payload = {
        "dispCatNo": "100000100010001",
        "pageIdx": "1",
        "rowsPerPage": "100",
        "sortBy": "BEST"
    }

    print("Sending request via ScraperAPI (Correct Method)...")
    # '해결사'의 올바른 주소로, '패키지 내용물'을 보내달라고 POST 요청합니다.
    response = requests.post(scraperapi_url, data=target_payload, timeout=120)

    if response.status_code != 200:
        print(f"❌ ScraperAPI failed with status code: {response.status_code}")
        print(response.text)
        return None

    try:
        data = response.json()
        items = data.get("goodsList", [])
        
        top_products = [f"{idx+1}. [{item.get('brandNm', '').strip()}] {item.get('goodsNm', '').strip()}" for idx, item in enumerate(items)]
        return top_products

    except json.JSONDecodeError:
        print(f"❌ An error occurred: Could not decode JSON.")
        print("Response from server was:")
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
    print("🔍 올리브영 랭킹 수집 시작 (ScraperAPI 최종 모드)")
    rankings = scrape_oliveyoung_rankings()

    if rankings:
        print(f"✅ Successfully scraped {len(rankings)} items.")
        send_to_slack(rankings)
    else:
        print("❌ Scraping failed.")
        send_to_slack(["ScraperAPI를 통한 요청에 실패했습니다. 로그를 확인해주세요."], is_error=True)
