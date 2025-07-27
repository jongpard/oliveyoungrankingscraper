import requests
import json
import os
from datetime import datetime

def scrape_oliveyoung_rankings():
    # 세션 객체 생성 (쿠키 유지를 위함)
    session = requests.Session()

    # 헤더 정보: 최신 크롬 브라우저처럼 위장
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    # 1. 메인 페이지를 먼저 방문하여 쿠키(입장권)를 받음
    print(" Warming up session by visiting the main page to get cookies...")
    main_page_url = "https://www.oliveyoung.co.kr/store/main/main.do"
    session.get(main_page_url, headers=headers)
    print(" Cookies received:", session.cookies.get_dict())


    # 2. 실제 랭킹 데이터(API) 요청
    api_url = "https://www.oliveyoung.co.kr/store/main/getBestList.do"
    api_headers = {
        **headers, # 기본 헤더 포함
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": "https://www.oliveyoung.co.kr/store/main/main.do", # 메인 페이지에서 온 것처럼
        "X-Requested-With": "XMLHttpRequest"
    }

    payload = {
        "dispCatNo": "100000100010001",  # 스킨케어
        "pageIdx": "1",
        "rowsPerPage": "100",
        "sortBy": "BEST"
    }

    print(" Sending POST request to Olive Young API...")
    # 반드시 쿠키를 받은 'session' 객체로 요청해야 함
    response = session.post(api_url, headers=api_headers, data=payload)
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
    if not webhook_url:
        print("SLACK_WEBHOOK_URL is not set")
        return

    if is_error:
        text = f"🚨 올리브영 랭킹 수집 실패\n{message_lines[0]}"
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
    else:
        text = f"🏆 올리브영 랭킹 Top {len(message_lines[:10])}"
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(message_lines[:10])}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}]}
        ]

    message = {"text": text, "blocks": blocks}

    try:
        requests.post(webhook_url, json=message, timeout=10).raise_for_status()
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
        send_to_slack(["올리브영 서버에서 접근을 차단했습니다. GitHub Actions 로그를 확인해주세요."], is_error=True)
