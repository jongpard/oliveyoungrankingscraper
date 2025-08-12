import os
import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime
import json
import base64

# --- Google Drive API 관련 라이브러리 ---
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# --- 환경 변수에서 GitHub Secrets 가져오기 ---
GDRIVE_SA_JSON_B64 = os.getenv("GDRIVE_SA_JSON_B64")
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

# --- 크롤링할 카테고리 설정 ---
# 올리브영 전체 랭킹 카테고리 번호
CATEGORY_NO = "10000010010" 

def send_slack_notification(message, is_successful=True):
    """슬랙으로 알림 메시지를 보냅니다."""
    if not SLACK_WEBHOOK_URL:
        print("슬랙 웹훅 URL이 설정되지 않았습니다.")
        return

    color = "#36a64f" if is_successful else "#ff0000"
    payload = {
        "attachments": [
            {
                "color": color,
                "text": message,
                "fallback": message,
                "ts": datetime.now().timestamp()
            }
        ]
    }
    try:
        requests.post(SLACK_WEBHOOK_URL, json=payload)
    except Exception as e:
        print(f"슬랙 알림 전송 중 에러 발생: {e}")

def scrape_oliveyoung_ranking(category_no):
    """올리브영 지정 카테고리의 랭킹을 스크랩하여 DataFrame으로 반환합니다."""
    url = f"https://www.oliveyoung.co.kr/store/main/getBestList.do?dispCatNo={category_no}"
    print(f"🔍 다음 URL에서 랭킹 수집을 시작합니다: {url}")
    
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception(f"올리브영 서버 응답 에러: Status Code {response.status_code}")

    soup = BeautifulSoup(response.text, "html.parser")
    products = soup.select("ul.cate_prd_list > li")
    
    if not products:
        raise Exception("랭킹 정보를 담고 있는 HTML 요소를 찾지 못했습니다. (ul.cate_prd_list)")

    ranking_data = []
    for rank, item in enumerate(products[:100], 1):
        brand = item.select_one("span.tx_brand").text.strip()
        name = item.select_one("p.tx_name").text.strip()
        price_element = item.select_one("span.tx_cur > span.tx_num")
        price = price_element.text.strip().replace(",", "") if price_element else "가격 정보 없음"
        
        rating_element = item.select_one("span.tx_point > em")
        rating = rating_element.text.strip() if rating_element else "0"
        
        review_element = item.select_one("span.tx_rev > em")
        review_count = review_element.text.strip().replace(",", "")[1:-1] if review_element else "0"

        ranking_data.append({
            "순위": rank,
            "브랜드": brand,
            "제품명": name,
            "가격": price,
            "평점": rating,
            "리뷰 수": review_count
        })

    return pd.DataFrame(ranking_data)

def upload_to_drive(file_path, folder_id):
    """지정된 파일을 구글 드라이브의 특정 폴더에 업로드합니다."""
    if not GDRIVE_SA_JSON_B64:
        raise ValueError("구글 드라이브 인증 정보(GDRIVE_SA_JSON_B64)가 없습니다.")
    if not folder_id:
        raise ValueError("구글 드라이브 폴더 ID(GDRIVE_FOLDER_ID)가 없습니다.")

    try:
        # Base64로 인코딩된 JSON 키를 디코딩하여 사용
        creds_json = json.loads(base64.b64decode(GDRIVE_SA_JSON_B64).decode('utf-8'))
        creds = Credentials.from_service_account_info(
            creds_json,
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        service = build("drive", "v3", credentials=creds)
        
        file_metadata = {
            "name": os.path.basename(file_path),
            "parents": [folder_id]
        }
        
        media = MediaFileUpload(file_path, mimetype="text/csv")
        
        print(f"🚀 '{os.path.basename(file_path)}' 파일을 구글 드라이브에 업로드합니다...")
        
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id",
            supportsAllDrives=True  # 공유 드라이브 지원 옵션
        ).execute()
        
        print(f"✅ 파일 업로드 성공! 파일 ID: {file.get('id')}")
        return True
        
    except HttpError as error:
        print(f"❌ 구글 드라이브 업로드 중 HTTP 에러 발생: {error}")
        # 에러 메시지를 재발생시켜 main 블록에서 처리하도록 함
        raise error
    except Exception as e:
        print(f"❌ 구글 드라이브 업로드 중 예기치 않은 에러 발생: {e}")
        raise e


if __name__ == "__main__":
    today_str = datetime.now().strftime("%Y-%m-%d")
    csv_dir = "rankings"
    os.makedirs(csv_dir, exist_ok=True)
    csv_path = os.path.join(csv_dir, f"oliveyoung_{today_str}.csv")

    try:
        # 1. 랭킹 데이터 스크랩
        df = scrape_oliveyoung_ranking(CATEGORY_NO)
        
        # 2. CSV 파일로 저장
        df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        print(f"✅ CSV 저장 완료: {csv_path}")

        # 3. 구글 드라이브에 업로드
        upload_to_drive(csv_path, GDRIVE_FOLDER_ID)
        
        # 4. 성공 알림 슬랙으로 전송
        top_3_items = "\n".join([f"  {row['순위']}위: {row['브랜드']} - {row['제품명']}" for _, row in df.head(3).iterrows()])
        success_message = (
            f"🎉 [성공] 올리브영 랭킹({today_str}) 수집 및 구글 드라이브 업로드 완료!\n\n"
            f"📁 파일명: {os.path.basename(csv_path)}\n"
            f"📊 총 {len(df)}개 제품 수집\n\n"
            f"✨ **TOP 3**\n{top_3_items}"
        )
        send_slack_notification(success_message, is_successful=True)

    except Exception as e:
        # 에러 발생 시 실패 알림 전송
        error_message = f"🚨 [실패] 올리브영 랭킹 수집 자동화 중 에러가 발생했습니다.\n\n- 날짜: {today_str}\n- 에러 내용: `{str(e)}`"
        print(error_message)
        send_slack_notification(error_message, is_successful=False)
