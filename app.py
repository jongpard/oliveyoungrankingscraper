import os
import re
import base64
import json
from datetime import datetime, timedelta
import pandas as pd
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.service_account import Credentials
import requests

# =========================
# 환경 변수
# =========================
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
GDRIVE_SA_JSON_B64 = os.getenv("GDRIVE_SA_JSON_B64")
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID")

# =========================
# 폴더 생성
# =========================
BASE_DIR = "rankings"
TODAY = datetime.now().strftime("%Y-%m-%d")
os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, TODAY), exist_ok=True)
CSV_PATH = os.path.join(BASE_DIR, TODAY, f"oliveyoung_{TODAY}.csv")

# =========================
# 구글 드라이브 업로드
# =========================
def upload_to_drive(local_path, folder_id):
    creds_json = base64.b64decode(GDRIVE_SA_JSON_B64).decode()
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(
        creds_dict, scopes=['https://www.googleapis.com/auth/drive.file']
    )
    service = build('drive', 'v3', credentials=creds)
    file_metadata = {"name": os.path.basename(local_path), "parents": [folder_id]}
    media = MediaFileUpload(local_path, mimetype="text/csv")
    service.files().create(body=file_metadata, media_body=media, fields="id").execute()
    print(f"✅ Google Drive 업로드 완료: {os.path.basename(local_path)}")

# =========================
# 제품명 전처리
# =========================
def clean_product_name(name):
    return re.sub(r"^\[.*?\]\s*", "", name).strip()

# =========================
# 올리브영 랭킹 크롤링
# =========================
def scrape_oliveyoung():
    url = "https://www.oliveyoung.co.kr/store/main/getBestList.do"
    print("🔍 올리브영 랭킹 수집 시작")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=60000)
        page.wait_for_timeout(5000)
        html = page.content()
        browser.close()

    soup = BeautifulSoup(html, "html.parser")
    items = soup.select(".prd_info")

    data = []
    rank_counter = 1
    for item in items:
        rank_tag = item.select_one(".num")
        rank_text = rank_tag.get_text(strip=True) if rank_tag else ""
        if "오특" in rank_text or not rank_text.isdigit():
            rank_text = "[오특]"
        else:
            rank_text = str(rank_counter)

        brand = item.select_one(".tx_brand").get_text(strip=True) if item.select_one(".tx_brand") else ""
        product = item.select_one(".tx_name").get_text(strip=True) if item.select_one(".tx_name") else ""
        price = item.select_one(".tx_cur").get_text(strip=True) if item.select_one(".tx_cur") else ""

        data.append({"순위": rank_text, "브랜드": brand, "제품명": product, "가격": price})
        rank_counter += 1

    df = pd.DataFrame(data)
    df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
    print(f"✅ CSV 저장 완료: {CSV_PATH}")
    return df

# =========================
# 랭킹 분석
# =========================
def analyze_trends(df_today):
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday_path = os.path.join(BASE_DIR, yesterday_str, f"oliveyoung_{yesterday_str}.csv")
    if not os.path.exists(yesterday_path):
        print("⚠ 어제 데이터 없음, 트렌드 분석 불가")
        return ""

    df_yesterday = pd.read_csv(yesterday_path)
    trends = "🔥 급상승 브랜드\n"

    # 급상승
    for _, row in df_today.iterrows():
        today_rank = row["순위"]
        if today_rank == "[오특]":
            continue
        today_rank = int(today_rank)

        match = df_yesterday[df_yesterday["제품명"] == row["제품명"]]
        if not match.empty:
            y_rank = match.iloc[0]["순위"]
            if y_rank != "[오특]" and str(y_rank).isdigit():
                y_rank = int(y_rank)
                diff = y_rank - today_rank
                if diff >= 10:
                    trends += f"- {row['브랜드']}: {y_rank}위 → {today_rank}위 (+{diff})\n ▶ {clean_product_name(row['제품명'])}\n"
        else:
            if today_rank <= 10:
                trends += f"- {row['브랜드']}: 첫 등장 {today_rank}위\n ▶ {clean_product_name(row['제품명'])}\n"

    # 급하락
    trends += "\n📉 급하락 브랜드\n"
    for _, row in df_yesterday.iterrows():
        y_rank = row["순위"]
        if y_rank == "[오특]" or not str(y_rank).isdigit():
            continue
        y_rank = int(y_rank)
        match = df_today[df_today["제품명"] == row["제품명"]]
        if y_rank <= 50 and (match.empty or (match.iloc[0]["순위"] != "[오특]" and int(match.iloc[0]["순위"]) > 50)):
            trends += f"- {row['브랜드']}: {y_rank}위 → 랭크아웃\n ▶ {clean_product_name(row['제품명'])}\n"

    return trends

# =========================
# Slack 전송
# =========================
def send_to_slack(message):
    if not SLACK_WEBHOOK_URL:
        print("⚠ SLACK_WEBHOOK_URL 미설정")
        return
    res = requests.post(SLACK_WEBHOOK_URL, json={"text": message})
    print("✅ Slack 전송 완료" if res.status_code == 200 else f"❌ Slack 전송 실패: {res.status_code}")

# =========================
# 메인 실행
# =========================
df_today = scrape_oliveyoung()
upload_to_drive(CSV_PATH, GDRIVE_FOLDER_ID)

# Top 10 출력
top10_msg = f":bar_chart: 올리브영 전체 랭킹 (국내) ({TODAY})\n"
for _, row in df_today.head(10).iterrows():
    top10_msg += f"{row['순위']}. {row['브랜드']} {row['제품명']} — {row['가격']}\n"

trend_msg = analyze_trends(df_today)
final_msg = f"{top10_msg}\n\n{trend_msg}"

send_to_slack(final_msg)
