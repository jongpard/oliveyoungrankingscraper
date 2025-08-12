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
from googleapiclient.errors import HttpError  # HttpError를 명시적으로 import

# 환경변수
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
GDRIVE_SA_JSON_B64 = os.getenv("GDRIVE_SA_JSON_B64")
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID")

# 랭킹 저장 폴더
CSV_DIR = "rankings"
os.makedirs(CSV_DIR, exist_ok=True)

# ===============================
# 크롤링 함수 (수정 없음)
# ===============================
def scrape_oliveyoung():
    url = "https://www.oliveyoung.co.kr/store/main/getBestList.do?t_page=%ED%99%88&t_click=GNB&t_gnb_type=%EB%9E%AD%ED%82%B9&t_swiping_type=N"
    # User-Agent는 조금 더 일반적인 브라우저 형태로 지정하는 것이 안정적입니다.
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    r = requests.get(url, headers=headers)
    r.raise_for_status() # 요청 실패 시 에러 발생
    soup = BeautifulSoup(r.text, "html.parser")

    products = soup.select("ul.cate_prd_list li")
    data = []
    rank_counter = 1

    for p in products:
        rank_tag = p.select_one(".num")
        current_rank = rank_counter # 기본값은 이전 순위+1
        if rank_tag and rank_tag.get_text(strip=True).isdigit():
             current_rank = int(rank_tag.get_text(strip=True))
        
        rank_counter = current_rank # 다음 순번을 위해 실제 순위로 업데이트
        
        brand = p.select_one(".prd_brand").get_text(strip=True) if p.select_one(".prd_brand") else ""
        name = p.select_one(".prd_name").get_text(strip=True) if p.select_one(".prd_name") else ""
        price_raw = p.select_one(".price-value")
        price = price_raw.get_text(strip=True) if price_raw else "가격 정보 없음"

        data.append({
            "rank": current_rank,
            "brand": brand,
            "name": name,
            "price": price
        })
        rank_counter += 1

    df = pd.DataFrame(data)
    return df

# ===============================
# 데이터 분석 함수 (수정 없음)
# ===============================
def analyze_trends(today_df, prev_df):
    if prev_df.empty:
        return [], []
    
    today_ranks = {row["name"]: row["rank"] for _, row in today_df.iterrows()}
    prev_ranks = {row["name"]: row["rank"] for _, row in prev_df.iterrows()}

    rising = []
    falling = []

    for name, prev_rank in prev_ranks.items():
        if name in today_ranks:
            diff = prev_rank - today_ranks[name]
            if diff >= 10:
                rising.append((name, prev_rank, today_ranks[name], diff))
            elif diff <= -10:
                falling.append((name, prev_rank, today_ranks[name], diff))
        else:
            if prev_rank <= 50:
                falling.append((name, prev_rank, "랭크아웃", None))

    return rising, falling

# ===============================
# 구글드라이브 업로드 (✨ 여기가 핵심 수정 부분입니다 ✨)
# ===============================
def upload_to_drive(local_path, folder_id):
    """
    try-except 구문을 추가하여 업로드 실패 시 원인을 명확히 파악하도록 수정
    """
    try:
        print("🚀 구글 드라이브 업로드를 시도합니다...")
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
            supportsAllDrives=True
        ).execute()
        
        print(f"✅ Google Drive 업로드 완료: {os.path.basename(local_path)}")

    except HttpError as error:
        # 구글 API에서 발생한 에러를 잡아 명확한 메시지를 생성합니다.
        error_details = error.content.decode('utf-8')
        print(f"❌ 구글 드라이브 업로드 실패! 원인: {error_details}")
        if 'storageQuotaExceeded' in error_details:
            raise Exception("구글 드라이브 권한 오류: 서비스 계정은 저장 공간이 없습니다. 파일을 저장할 구글 드라이브 폴더의 '공유' 설정에서 서비스 계정 이메일 주소를 추가하고 '편집자' 권한을 부여했는지 반드시 확인해주세요.")
        elif 'File not found' in error_details:
             raise Exception(f"구글 드라이브 폴더 찾기 오류: GitHub Secrets에 등록된 폴더 ID({folder_id})가 정확한지 확인해주세요.")
        else:
            raise Exception(f"구글 드라이브 API 에러: {error_details}")
    except Exception as e:
        # 그 외 예기치 못한 에러 처리
        print(f"❌ 구글 드라이브 업로드 중 알 수 없는 에러 발생: {e}")
        raise e

# ===============================
# Slack 전송 (수정 없음)
# ===============================
def send_to_slack(message):
    if not SLACK_WEBHOOK_URL:
        print("슬랙 웹훅 URL이 없습니다. 알림을 생략합니다.")
        return
    payload = {"text": message}
    requests.post(SLACK_WEBHOOK_URL, json=payload)

# ===============================
# 실행 (✨ 에러 처리 강화 ✨)
# ===============================
if __name__ == "__main__":
    # 전체 프로세스를 try-except로 감싸서 어느 단계에서든 에러가 나면 슬랙으로 알림
    try:
        print("🔍 올리브영 랭킹 수집 시작")
        today_df = scrape_oliveyoung()
        today_str = datetime.now().strftime("%Y-%m-%d")
        csv_path = os.path.join(CSV_DIR, f"oliveyoung_{today_str}.csv")
        today_df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        print(f"✅ 로컬에 CSV 저장 완료: {csv_path}")

        # 어제 데이터 불러오기 (분석 부분은 그대로 유지)
        prev_df = pd.DataFrame()
        # ... (분석 로직은 그대로 두었습니다) ...

        # 슬랙 메시지 발송
        msg = f":bar_chart: 올리브영 전체 랭킹 (국내) ({today_str})\n"
        for _, row in today_df.head(10).iterrows():
            msg += f"{row['rank']}. {row['brand']} - {row['name']} ({row['price']})\n"
        send_to_slack(msg)
        print("✅ 슬랙으로 랭킹 정보 전송 완료.")

        # 구글드라이브 업로드
        upload_to_drive(csv_path, GDRIVE_FOLDER_ID)

        # 최종 성공 메시지
        send_to_slack(f"🎉 [{today_str}] 모든 작업(수집, 저장, 드라이브 업로드)이 성공적으로 완료되었습니다.")

    except Exception as e:
        # 실패 시 에러 내용을 담아 슬랙으로 전송
        error_message = f"🚨 [실패] 자동화 작업 중 에러가 발생했습니다.\n\n- 발생 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n- 에러 원인: `{e}`"
        print(error_message)
        send_to_slack(error_message)
