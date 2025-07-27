import cloudscraper # requests 대신 cloudscraper를 사용합니다
import json
import os
from datetime import datetime

def scrape_oliveyoung_rankings():
    # Cloudflare를 우회하는 전문가용 스크레이퍼 생성
    scraper = cloudscraper.create_scraper(delay=10, browser='chrome')

    # 헤더 정보: 여전히 실제 브라우저처럼 위장
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    # 실제 랭킹 데이터(API) 요청
    api_url = "https://www.oliveyoung.co.kr/store/main/getBestList.do"
    payload = {
        "dispCatNo": "100000100010001",  # 스킨케어
        "pageIdx": "1",
        "rowsPerPage": "100",
        "sortBy": "BEST"
    }

    print(" Sending POST request to Olive Young API using cloudscraper...")
    # cloudscraper 객체로 요청
    response = scraper.post(api_url, headers=headers, data=payload)
    print(f" Received response with status code: {response.status_code}")

    try:
        data = response.json()
        items = data.get("goodsList", [])
        
        top_products = []
        for idx, item in enumerate(items, start=1):
            name = item.get("goodsNm", "").strip()
            brand = item.get("brandNm", "").strip()
            top_products.append(f"{idx}. [{brand}] {name}")

        return top_products

    except json.JSONDecodeError:
        print("❌ Failed to decode JSON.")
        print("Server response was:")
        print(response.text[:500])
        return None

def send_to_slack(message_lines, is_error=False):
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url: return

    if is_error:
        text = f"🚨 올리브영 랭킹 수집 실패\n{message_lines[0]}"
    else:
        text = f"🏆 올리브영 랭킹 Top {len(message_lines[:10])}"

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{text}*"}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(message_lines[:10]) if not is_error else ""}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}]}
    ]

    try:
        requests.post(webhook_url, json={"text": text, "blocks": blocks}, timeout=10).raise_for_status()
        print("✅ Slack message sent successfully")
    except Exception as e:
        print(f"❌ Failed to send Slack message: {e}")

if __name__ == "__main__":
    print("🔍 올리브영 랭킹 수집 시작")
    rankings = scrape_oliveyoung_rankings()

    if rankings:
        print(f"✅ Successfully scraped {len(rankings)} items.")
        send_to_slack(rankings)
    else:
        print("❌ Scraping failed.")
        send_to_slack(["Cloudflare 보안에 막혔거나 서버 응답이 올바르지 않습니다."], is_error=True)
