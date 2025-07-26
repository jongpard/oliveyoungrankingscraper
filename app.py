import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime

def scrape_oliveyoung_rankings():
    url = "https://www.oliveyoung.co.kr/store/main/getBestList.do"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "User-Agent": "Mozilla/5.0"
    }
    payload = {
        "dispCatNo": "100000100010001",  # 스킨케어 예시 카테고리
        "pageIdx": "1",
        "rowsPerPage": "20",
        "sortBy": "BEST"
    }

    response = requests.post(url, headers=headers, data=payload)
    data = response.json()

    items = data.get("goodsList", [])

    top_products = []
    for idx, item in enumerate(items, start=1):
        name = item.get("goodsNm", "")
        brand = item.get("brandNm", "")
        top_products.append(f"{idx}. [{brand}] {name}")

    return top_products

def send_to_slack(message_lines):
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("SLACK_WEBHOOK_URL is not set")
        return

    message = {
        "text": "*📦 올리브영 랭킹 스크래핑 완료!*",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*📦 올리브영 랭킹 스크래핑 완료!*"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "\n".join(message_lines[:10])  # 상위 10개만 출력
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    }
                ]
            }
        ]
    }

    try:
        response = requests.post(webhook_url, json=message)
        response.raise_for_status()
        print("✅ 슬랙 메시지 전송 성공")
    except Exception as e:
        print(f"❌ 슬랙 메시지 전송 실패: {e}")

if __name__ == "__main__":
    print("🔍 올리브영 랭킹 수집 시작")
    rankings = scrape_oliveyoung_rankings()
    send_to_slack(rankings)
