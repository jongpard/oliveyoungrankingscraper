import os
import base64
import json
from datetime import datetime
import pandas as pd
from playwright.sync_api import sync_playwright
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.service_account import Credentials

# =========================
# 구글 드라이브 업로드 준비
# =========================
def get_drive_service():
    creds_json = base64.b64decode(os.environ["GDRIVE_SA_JSON_B64"]).decode()
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=['https://www.googleapis.com/auth/drive.file'])
    return build('drive', 'v3', credentials=creds)

def upload_to_drive(local_path, folder_id):
    service = get_drive_service()
    file_metadata = {
        'name': os.path.basename(local_path),
        'parents': [folder_id]
    }
    media = MediaFileUpload(local_path, resumable=True)
    service.files().create(body=file_metadata, media_body=media, fields='id').execute()

# =========================
# 랭킹 폴더 준비
# =========================
base_dir = "rankings"
if not os.path.exists(base_dir):
    os.makedirs(base_dir)

today_str = datetime.now().strftime("%Y-%m-%d")
today_dir = os.path.join(base_dir, today_str)
if not os.path.exists(today_dir):
    os.makedirs(today_dir)

csv_path = os.path.join(today_dir, f"oliveyoung_{today_str}.csv")

# =========================
# 데이터 수집
# =========================
def scrape_oliveyoung():
    url = "https://www.oliveyoung.co.kr/store/main/main.do"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=60000)
        page.wait_for_timeout(5000)
        html = page.content()
        browser.close()

    # 페이지 파싱
    df = pd.DataFrame(columns=["rank", "brand", "product", "price"])
    # 이 부분은 실제 HTML 구조에 맞게 BeautifulSoup으로 파싱해야 함
    # 여기서는 예시
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    items = soup.select(".main-prod-list li")
    rank_counter = 1
    for item in items:
        brand = item.select_one(".prod-brand").get_text(strip=True) if item.select_one(".prod-brand") else ""
        product = item.select_one(".prod-name").get_text(strip=True) if item.select_one(".prod-name") else ""
        price = item.select_one(".price-amount").get_text(strip=True) if item.select_one(".price-amount") else ""
        if not str(rank_counter).isdigit():
            rank_text = f"[오특]"
        else:
            rank_text = rank_counter
        df.loc[len(df)] = [rank_text, brand, product, price]
        rank_counter += 1

    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    return df

# =========================
# 트렌드 분석
# =========================
def analyze_trends(df_today, df_yesterday):
    trends = []

    # 급상승
    for idx, row in df_today.iterrows():
        product = row["product"]
        today_rank = idx + 1
        yesterday_row = df_yesterday[df_yesterday["product"] == product]
        if not yesterday_row.empty:
            yesterday_rank = yesterday_row.index[0] + 1
            diff = yesterday_rank - today_rank
            if diff >= 10:
                clean_name = remove_prefix(product)
                trends.append(f"🔥 {row['brand']}: {yesterday_rank}위 → {today_rank}위 (+{diff})\n ▶ {clean_name}")
        else:
            if today_rank <= 10:
                clean_name = remove_prefix(product)
                trends.append(f"🔥 {row['brand']}: 첫 등장 {today_rank}위\n ▶ {clean_name}")

    # 급하락
    for idx, row in df_yesterday.iterrows():
        product = row["product"]
        yesterday_rank = idx + 1
        today_row = df_today[df_today["product"] == product]
        if yesterday_rank <= 50 and (today_row.empty or today_row.index[0] + 1 > 50):
            clean_name = remove_prefix(product)
            trends.append(f"📉 {row['brand']}: {yesterday_rank}위 → 랭크아웃\n ▶ {clean_name}")

    return "\n".join(trends)

def remove_prefix(name):
    import re
    return re.sub(r"^\[.*?\]\s*", "", name)

# =========================
# 실행
# =========================
df_today = scrape_oliveyoung()

# 어제 데이터 불러오기
yesterday_str = (datetime.now() - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
yesterday_path = os.path.join(base_dir, yesterday_str, f"oliveyoung_{yesterday_str}.csv")
df_yesterday = pd.read_csv(yesterday_path) if os.path.exists(yesterday_path) else pd.DataFrame(columns=["rank","brand","product","price"])

trend_text = analyze_trends(df_today, df_yesterday)

# 구글 드라이브 업로드
upload_to_drive(csv_path, os.environ["GDRIVE_FOLDER_ID"])

print("✅ Top10")
print(df_today.head(10))
print("\n✅ 트렌드 분석")
print(trend_text)
