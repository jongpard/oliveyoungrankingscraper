import os
import re
import json
import base64
import requests
import pandas as pd
from datetime import datetime
from bs4 import BeautifulSoup
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.service_account import Credentials

# 환경변수
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
GDRIVE_SA_JSON_B64 = os.getenv("GDRIVE_SA_JSON_B64")
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID")

# 랭킹 저장 폴더
CSV_DIR = "rankings"
os.makedirs(CSV_DIR, exist_ok=True)

# ===============================
# 크롤링 함수
# ===============================
def scrape_oliveyoung():
    url = "https://www.oliveyoung.co.kr/store/main/getBestList.do"
    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    r = requests.get(url, headers=headers)
    soup = BeautifulSoup(r.text, "html.parser")

    products = soup.select("ul.cate_prd_list li")
    data = []
    rank_counter = 1

    for p in products:
        # 순위 처리 (오특 → 실제 순번)
        rank_tag = p.select_one(".num")
        if rank_tag:
            try:
                rank = int(rank_tag.get_text(strip=True))
                rank_counter = rank
            except:
                # 오특이면 rank_counter 그대로
                pass
        else:
            pass

        brand = p.select_one(".prd_brand").get_text(strip=True) if p.select_one(".prd_brand") else ""
        name = p.select_one(".prd_name").get_text(strip=True) if p.select_one(".prd_name") else ""
        price = p.select_one(".price").get_text(strip=True) if p.select_one(".price") else ""

        data.append({
            "rank": rank_counter,
            "brand": brand,
            "name": name,
            "price": price
        })

        rank_counter += 1

    df = pd.DataFrame(data)
    return df

# ===============================
# 데이터 분석
# ===============================
def analyze_trends(today_df, prev_df):
    today_ranks = {row["brand"]: row["rank"] for _, row in today_df.iterrows()}
    prev_ranks = {row["brand"]: row["rank"] for _, row in prev_df.iterrows()}

    rising = []
    falling = []

    for brand, prev_rank in prev_ranks.items():
        if brand in today_ranks:
            diff = prev_rank - today_ranks[brand]
            if diff >= 10:
                rising.append((brand, prev_rank, today_ranks[brand], diff))
            elif diff <= -10:
                falling.append((brand, prev_rank, today_ranks[brand], diff))
        else:
            # 오늘 랭크아웃
            if prev_rank <= 50:
                falling.append((brand, prev_rank, None, None))

    return rising, falling

# ===============================
# 구글드라이브 업로드
# ===============================
def upload_to_drive(local_path, folder_id):
    creds_json = base64.b64decode(GDRIVE_SA_JSON_B64).decode()
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(
        creds_dict, scopes=['https://www.googleapis.com/auth/drive']
    )
    service = build('drive', 'v3', credentials=creds)

    file_metadata = {
        "name": os.path.basename(local_path),
        "parents": [folder_id]
    }
    media = MediaFileUpload(local_path, mimetype="text/csv")
    service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id",
        supportsAllDrives=True  # 공유드라이브 지원
    ).execute()
    print(f"✅ Google Drive 업로드 완료: {os.path.basename(local_path)}")

# ===============================
# Slack 전송
# ===============================
def send_to_slack(message):
    payload = {"text": message}
    requests.post(SLACK_WEBHOOK_URL, json=payload)

# ===============================
# 실행
# ===============================
if __name__ == "__main__":
    print("🔍 올리브영 랭킹 수집 시작")

    today_df = scrape_oliveyoung()
    today_str = datetime.now().strftime("%Y-%m-%d")
    csv_path = os.path.join(CSV_DIR, f"oliveyoung_{today_str}.csv")
    today_df.to_csv(csv_path, index=False)
    print(f"✅ CSV 저장 완료: {csv_path}")

    # 어제 데이터 불러오기
    prev_csv = None
    prev_df = pd.DataFrame()
    try:
        prev_date = (datetime.now() - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        prev_csv = os.path.join(CSV_DIR, f"oliveyoung_{prev_date}.csv")
        if os.path.exists(prev_csv):
            prev_df = pd.read_csv(prev_csv)
    except:
        pass

    rising, falling = analyze_trends(today_df, prev_df)

    # 메시지 작성
    msg = f":bar_chart: 올리브영 전체 랭킹 (국내) ({today_str})\n"
    for _, row in today_df.head(10).iterrows():
        rank_display = f"[오특]" if row["rank"] is None else row["rank"]
        msg += f"{rank_display}. {row['brand']} {row['name']} — {row['price']}\n"

    if rising:
        msg += "\n🔥 급상승 브랜드\n"
        for brand, prev_rank, curr_rank, diff in rising:
            msg += f"- {brand}: {prev_rank}위 → {curr_rank}위 (+{diff})\n"

    if falling:
        msg += "\n📉 급하락 브랜드\n"
        for brand, prev_rank, curr_rank, diff in falling:
            if curr_rank:
                msg += f"- {brand}: {prev_rank}위 → {curr_rank}위 ({diff})\n"
            else:
                msg += f"- {brand}: {prev_rank}위 → 랭크아웃\n"

    send_to_slack(msg)

    # 구글드라이브 업로드
    upload_to_drive(csv_path, GDRIVE_FOLDER_ID)
