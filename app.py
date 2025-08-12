import os
import requests
import pandas as pd
from datetime import datetime
from bs4 import BeautifulSoup

# 환경변수
DROPBOX_TOKEN = os.environ.get("DROPBOX_ACCESS_TOKEN")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

# 올리브영 랭킹 페이지 URL
BASE_URL = "https://www.oliveyoung.co.kr/store/main/getBestList.do"

# Dropbox 업로드 함수
def upload_to_dropbox(local_path, dropbox_path):
    with open(local_path, "rb") as f:
        data = f.read()
    headers = {
        "Authorization": f"Bearer {DROPBOX_TOKEN}",
        "Dropbox-API-Arg": f'{{"path": "{dropbox_path}", "mode": "overwrite"}}',
        "Content-Type": "application/octet-stream"
    }
    r = requests.post("https://content.dropboxapi.com/2/files/upload", headers=headers, data=data)
    if r.status_code == 200:
        print(f"✅ Dropbox 업로드 성공: {dropbox_path}")
    else:
        print(f"❌ Dropbox 업로드 실패: {r.text}")

# Slack 메시지 전송 함수
def send_slack_message(text):
    payload = {"text": text}
    r = requests.post(SLACK_WEBHOOK_URL, json=payload)
    if r.status_code == 200:
        print("✅ Slack 전송 성공")
    else:
        print(f"❌ Slack 전송 실패: {r.text}")

# 올리브영 랭킹 크롤링
def scrape_oliveyoung():
    print("🔍 올리브영 랭킹 수집 시작")
    resp = requests.get(BASE_URL)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    items = soup.select("p.tx_name")
    prices = soup.select("span.tx_num")

    data = []
    rank = 1
    for name_tag, price_tag in zip(items, prices):
        name = name_tag.get_text(strip=True)
        price = price_tag.get_text(strip=True)
        data.append({
            "순위": rank,
            "제품명": name,
            "가격": price
        })
        rank += 1

    df = pd.DataFrame(data)
    return df

if __name__ == "__main__":
    today = datetime.now().strftime("%Y-%m-%d")
    csv_name = f"oliveyoung_{today}.csv"
    local_path = os.path.join("rankings", csv_name)
    os.makedirs("rankings", exist_ok=True)

    df_today = scrape_oliveyoung()
    df_today.to_csv(local_path, index=False, encoding="utf-8-sig")
    print(f"✅ CSV 저장 완료: {local_path}")

    # Dropbox 업로드
    upload_to_dropbox(local_path, f"/oliveyoung_rankings/{csv_name}")

    # Slack 메시지 (TOP 10)
    top10_text = "\n".join(
        [f"{row.순위}. {row.제품명} — {row.가격}" for _, row in df_today.head(10).iterrows()]
    )
    send_slack_message(f":bar_chart: 올리브영 전체 랭킹 (국내) ({today})\n{top10_text}")
