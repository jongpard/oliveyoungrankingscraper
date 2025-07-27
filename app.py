import requests
import json
import os
from datetime import datetime

def scrape_oliveyoung_rankings():
    api_key = os.getenv("SCRAPER_API_KEY")
    
    # 이것이 바로 '작전 지시서'입니다.
    # ScraperAPI의 브라우저가 올리브영 페이지 안에서 실행할 JavaScript 코드입니다.
    js_script = """
        async function solve() {
            const response = await fetch('/store/main/getBestList.do', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8' },
                body: new URLSearchParams({
                    'dispCatNo': '100000100010001',
                    'pageIdx': '1',
                    'rowsPerPage': '100',
                    'sortBy': 'BEST'
                })
            });
            return await response.json();
        }
        solve();
    """

    # '해결사'에게 보낼 최종 요청
    scraperapi_payload = {
        'api_key': api_key,
        'url': 'https://www.oliveyoung.co.kr/store/main/main.do', # 먼저 이 페이지를 열어서 보안을 통과
        'render': 'true', # 브라우저 사용 지시
        'js_scenario': {'instructions': [{'execute': js_script}]} # 위 '작전 지시서' 실행
    }
    
    # JavaScript 시나리오를 실행하는 전용 주소
    scraperapi_url = 'https://api.scraperapi.com/session/sync/js'

    print("Sending JS Scenario request via ScraperAPI...")
    response = requests.post(scraperapi_url, json=scraperapi_payload, timeout=180)

    if response.status_code != 200:
        print(f"❌ ScraperAPI failed with status code: {response.status_code}")
        print(f"Response text: {response.text}")
        return None

    try:
        data = response.json()
        items = data.get("goodsList", [])
        
        if not items:
            print("❌ 'goodsList' not found. It's likely the JS scenario failed.")
            print(f"Full response: {data}")
            return None

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
    print("🔍 올리브영 랭킹 수집 시작 (ScraperAPI + JS Scenario 최종 모드)")
    rankings = scrape_oliveyoung_rankings()

    if rankings:
        print(f"✅ Successfully scraped {len(rankings)} items.")
        send_to_slack(rankings)
    else:
        print("❌ Scraping failed.")
        send_to_slack(["ScraperAPI를 통한 요청에 실패했습니다. 로그를 확인해주세요."], is_error=True)
