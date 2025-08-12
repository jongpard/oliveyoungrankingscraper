import os
import re
import json
import base64
import datetime
import pandas as pd
from playwright.sync_api import sync_playwright
from google.oauth2 import service_account
from googleapiclient.discovery import build
import requests

# 환경변수
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
GDRIVE_SA_JSON_B64 = os.getenv("GDRIVE_SA_JSON_B64")
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID")

TODAY = datetime.date.today().strftime("%Y-%m-%d")
RANKINGS_DIR = "rankings"
os.makedirs(RANKINGS_DIR, exist_ok=True)

# Google Drive 업로드 함수
def upload_to_gdrive(file_path, file_name):
    creds_json = base64.b64decode(GDRIVE_SA_JSON_B64).decode("utf-8")
    creds_dict = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=["https://www.googleapis.com/auth/drive.file"]
    )
    service = build("drive", "v3", credentials=creds)

    file_metadata = {
        "name": file_name,
        "parents": [GDRIVE_FOLDER_ID]
    }
    media = MediaFileUpload(file_path, mimetype="text/csv")
    uploaded = service.files().create(
        body=file_metadata, media_body=media, fields="id"
    ).execute()
    print(f"✅ Google Drive 업로드 완료: {uploaded.get('id')}")

# 제품명 정리 (앞의 불필요 태그 제거)
def clean_product_name(name):
    return re.sub(r"^\[.*?\]\s*", "", name).strip()

# 올리브영 랭킹 크롤링
def scrape_rankings():
    print("🔍 올리브영 랭킹 수집 시작")
    data = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.oliveyoung.co.kr/store/main/getBestList.do", timeout=60000)
        page.wait_for_selector(".prd_info")
        products = page.query_selector_all(".prd_info")

        rank_counter = 1
        for prod in products:
            rank_text = prod.query_selector(".num").inner_text().strip()
            # '오특' 무시하고 순서대로 랭킹 번호 부여
            if "오특" in rank_text:
                rank_text = str(rank_counter)
            name = prod.query_selector(".tx_name").inner_text().strip()
            brand = prod.query_selector(".tx_brand").inner_text().strip()
            price = prod.query_selector(".tx_cur").inner_text().strip()
            data.append({
                "순위": int(rank_text),
                "브랜드": brand,
                "제품명": name,
                "가격": price
            })
            rank_counter += 1
        browser.close()

    df = pd.DataFrame(data)
    file_path = os.path.join(RANKINGS_DIR, f"{TODAY}_oliveyoung.csv")
    df.to_csv(file_path, index=False, encoding="utf-8-sig")
    print(f"✅ CSV 저장 완료: {file_path}")
    return df, file_path

# 랭킹 변동 분석
def analyze_trends(df_today):
    try:
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        yesterday_file = os.path.join(RANKINGS_DIR, f"{yesterday}_oliveyoung.csv")
        if not os.path.exists(yesterday_file):
            print("⚠ 어제 데이터 없음, 트렌드 분석 불가")
            return ""
        df_yesterday = pd.read_csv(yesterday_file)

        merged = pd.merge(
            df_today, df_yesterday, on="제품명", suffixes=("_today", "_yesterday"), how="left"
        )
        merged["변동"] = merged["순위_yesterday"] - merged["순위_today"]
        merged = merged.sort_values("변동", ascending=False).head(5)

        analysis = "🔥 급상승 브랜드\n"
        for _, row in merged.iterrows():
            change_str = f"(+{row['변동']})" if row["변동"] > 0 else f"({row['변동']})"
            brand = row["브랜드_today"]
            prod_name = clean_product_name(row["제품명"])
            if pd.isna(row["순위_yesterday"]):
                rank_change = f"첫 등장 {row['순위_today']}위"
            else:
                rank_change = f"{int(row['순위_yesterday'])}위 → {int(row['순위_today'])}위 {change_str}"
            analysis += f"- {brand}: {rank_change}\n ▶ {brand} {prod_name}\n"
        return analysis
    except Exception as e:
        print(f"트렌드 분석 오류: {e}")
        return ""

# Slack 전송
def send_to_slack(message):
    payload = {"text": message}
    res = requests.post(SLACK_WEBHOOK_URL, json=payload)
    if res.status_code == 200:
        print("✅ Slack 전송 완료")
    else:
        print(f"❌ Slack 전송 실패: {res.status_code}")

if __name__ == "__main__":
    df_today, file_path = scrape_rankings()
    upload_to_gdrive(file_path, os.path.basename(file_path))

    top10_msg = "🏆 오늘의 랭킹 TOP 10\n"
    for _, row in df_today.head(10).iterrows():
        top10_msg += f"{row['순위']}위: {row['브랜드']} {row['제품명']} - {row['가격']}\n"

    trend_msg = analyze_trends(df_today)

    final_msg = f"{top10_msg}\n\n{trend_msg}"
    send_to_slack(final_msg)
