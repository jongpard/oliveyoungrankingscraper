import requests
import json
import os
from datetime import datetime

def scrape_oliveyoung_rankings():
    api_key = os.getenv("SCRAPER_API_KEY")
    if not api_key:
        raise ValueError("SCRAPER_API_KEY is not set in GitHub Secrets.")

    # 올리브영의 진짜 데이터 API 주소
    target_url = "https://www.oliveyoung.co.kr/store/main/getBestList.do"

    # 올리브영 서버가 요구하는 '주문서' (POST 데이터)
    target_payload = {
        "dispCatNo": "100000100010001",
        "pageIdx": "1",
        "rowsPerPage": "100",
        "sortBy": "BEST"
    }

    # '전문 해결사' ScraperAPI에게 내릴 최종 작전 지시
    scraperapi_payload = {
        'api_key': api_key,
        'url': target_url,          # 이 주소로
        'method': 'POST',           # POST 요청을 보내고
        'form_data': target_payload, # 이 '주문서'를 제출해줘
        'render': 'true',           # 만약 막히면, 브라우저('만능 열쇠')를 사용해서라도
        'country_code': 'kr'        # 한국에서 접속한 것처럼 해줘
    }
    
    # ScraperAPI의 표준 요청 주소
    scraperapi_url = 'https://api.scraperapi.com/'

    print("Sending POST request via ScraperAPI with Browser Rendering...")
    response = requests.post(scraperapi_url, json=scraperapi_payload, timeout=180)

    if response.status_code != 200:
        print(f"❌ ScraperAPI failed with status code: {response.status_code}")
        print(response.text)
        return None

    try:
        data = response.json()
        items = data.get("goodsList", [])
        
        if not items:
            raise ValueError("'goodsList' not found in the response.")

        top_products = [f"{idx+1}. [{item.get('brandNm', '').strip()}] {item.get('goodsNm', '').strip()}" for idx, item in enumerate(items)]
        return top_products

    except (json.JSONDecodeError, ValueError) as e:
        print(f"❌ An error occurred during parsing: {e}")
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
    print("🔍 올리브영 랭킹 수집 시작 (ScraperAPI + POST + Browser Rendering 최종 모드)")
    rankings = scrape_oliveyoung_rankings()

    if rankings:
        print(f"✅ Successfully scraped {len(rankings)} items.")
        send_to_slack(rankings)
    else:
        print("❌ Scraping failed.")
        send_to_slack(["ScraperAPI를 통한 최종 요청에 실패했습니다. GitHub Actions 로그를 확인해주세요."], is_error=True)
