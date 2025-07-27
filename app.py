import requests
import json
import os
from datetime import datetime

def scrape_oliveyoung_rankings():
    url = "https://www.oliveyoung.co.kr/store/main/getBestList.do"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"
    }
    payload = {
        "dispCatNo": "100000100010001",  # 스킨케어 예시
        "pageIdx": "1",
        "rowsPerPage": "20",
        "sortBy": "BEST"
    }

    print("Sending POST request to Olive Young...")
    response = requests.post(url, headers=headers, data=payload)
    print(f"Received response with status code: {response.status_code}")

    try:
        # JSON 파싱 시도
        data = response.json()
        items = data.get("goodsList", [])

        top_products = []
        for idx, item in enumerate(items, start=1):
            name = item.get("goodsNm", "")
            brand = item.get("brandNm", "")
            top_products.append(f"{idx}. [{brand}] {name}")

        return top_products

    except json.JSONDecodeError:
        # JSON 파싱 실패 시, 원본 응답 내용을 로그에 출력
        print("❌ Failed to decode JSON.")
        print("Server response was:")
        print(response.text[:500])  # 너무 길지 않게 앞부분 500자만 출력
        return None # 실패했음을 알리기 위해 None 반환

def send_to_slack(message_lines, is_error=False):
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("SLACK_WEBHOOK_URL is not set")
        return

    if is_error:
        text = f"🚨 올리브영 랭킹 수집 실패\n{message_lines[0]}"
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
    else:
        text = "*📦 올리브영 랭킹 스크래핑 완료!*"
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(message_lines[:10])}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}]}
        ]

    message = {"text": text, "blocks": blocks}

    try:
        response = requests.post(webhook_url, json=message)
        response.raise_for_status()
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
        send_to_slack(["JSON 파싱에 실패했습니다. GitHub Actions 로그를 확인해주세요."], is_error=True)
