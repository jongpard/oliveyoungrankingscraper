import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
import os
import json

# Slack Webhook 주소 (GitHub Secrets에서 불러옴)
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

def fetch_oliveyoung_rankings():
    all_data = []

    for page in range(1, 11):  # 1~10 페이지 = 100위까지
        url = f"https://www.oliveyoung.co.kr/store/main/getBestList.do?dispCatNo=90000010001&pageIdx={page}&rowsPerPage=10&sortType=01"
        headers = {
            "User-Agent": "Mozilla/5.0"
        }

        response = requests.get(url, headers=headers)
        items = response.json().get("bestList", [])

        for item in items:
            all_data.append({
                "순위": item.get("rank"),
                "상품명": item.get("prdName"),
                "브랜드": item.get("brandName"),
                "가격": item.get("priceOnline"),
                "할인율": item.get("saleRate"),
                "카테고리": item.get("dispCatNo")
            })

    return pd.DataFrame(all_data)

def analyze_rankings(df):
    top10 = df.head(10)
    brand_counts = df['브랜드'].value_counts().head(5)
    
    summary = f"""
📊 올리브영 랭킹 요약 ({datetime.now().strftime('%Y-%m-%d')} 기준)

✅ Top 10 상품
{top10[['순위', '브랜드', '상품명']].to_string(index=False)}

🏆 브랜드별 상위권 진입 수 (Top 100 기준)
{brand_counts.to_string()}
"""
    return summary

def send_to_slack(message):
    if not SLACK_WEBHOOK_URL:
        print("⚠️ SLACK_WEBHOOK_URL이 설정되지 않았습니다.")
        return

    payload = {
        "text": message
    }
    headers = {"Content-Type": "application/json"}

    response = requests.post(SLACK_WEBHOOK_URL, data=json.dumps(payload), headers=headers)

    if response.status_code == 200:
        print("✅ Slack 전송 성공")
    else:
        print(f"❌ Slack 전송 실패: {response.status_code} {response.text}")

if __name__ == "__main__":
    print("📥 올리브영 랭킹 크롤링 시작")
    df = fetch_oliveyoung_rankings()

    print("🔍 분석 시작")
    summary = analyze_rankings(df)

    print("📤 슬랙 전송")
    send_to_slack(summary)
