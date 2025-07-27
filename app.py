import requests
import pandas as pd
import os
import json
from datetime import datetime

def fetch_oliveyoung_rankings():
    """
    올리브영의 모바일 실시간 랭킹 API를 직접 호출하되,
    서버 응답에 HTML이 섞여 들어오는 경우를 처리하여 안정성을 높입니다.
    """
    url = "https://m.oliveyoung.co.kr/m/mc/main/getRankAll.do"
    headers = {
        'User-Agent': 'OliveYoungApp/7.2.1 (iOS; 15.4.1; iPhone)',
        'Content-Type': 'application/json;charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest' # 모바일 앱 요청처럼 보이게 하는 추가 헤더
    }
    payload = {
        "dispCatNo": "90000010001",
        "pageIdx": "1",
        "rowsPerPage": "100"
    }

    print("📥 올리브영 랭킹 크롤링 시작 (모바일 API + 데이터 정제 최종 방식)")
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()

        # --- 데이터 정제 로직 시작 ---
        # 서버가 보낸 텍스트 전체를 가져옵니다.
        response_text = response.text
        
        # 진짜 JSON 데이터는 '{' 로 시작합니다. 그 부분을 찾습니다.
        json_start_index = response_text.find('{')
        
        if json_start_index == -1:
            raise ValueError("응답에서 JSON 시작 부분('{')을 찾을 수 없습니다.")

        # '{' 부터 끝까지가 우리가 필요한 진짜 데이터입니다.
        json_data_string = response_text[json_start_index:]
        # --- 데이터 정제 로직 끝 ---

        # 정제된 텍스트를 JSON으로 변환합니다.
        data = json.loads(json_data_string)
        items = data.get("bestList", [])
        
        if not items:
            raise ValueError("정제된 데이터에서 'bestList'를 찾을 수 없습니다.")
        
        df = pd.DataFrame(items)
        df['rank'] = df['rnk'].astype(int)
        df['brand'] = df['brnd_nm']
        df['name'] = df['prdt_nm']
        df = df[['rank', 'brand', 'name']].sort_values('rank').reset_index(drop=True)
        
        return df

    except requests.exceptions.HTTPError as e:
        print(f"❌ HTTP 요청 실패: {e.response.status_code}")
        print("서버 응답:", e.response.text)
        return None
    except Exception as e:
        print(f"❌ 데이터 처리 중 에러 발생: {e}")
        return None

def send_to_slack(df):
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url: return

    top_10_list = [f"{row['rank']}. [{row['brand']}] {row['name']}" for index, row in df.head(10).iterrows()]
    message_text = "\n".join(top_10_list)
    title = f"🏆 올리브영 실시간 랭킹 Top {len(top_10_list)}"
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*"}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": message_text}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}]}
    ]

    try:
        response = requests.post(webhook_url, json={"text": title, "blocks": blocks}, timeout=10)
        response.raise_for_status()
        print("✅ 슬랙 메시지 전송 성공")
    except Exception as e:
        print(f"❌ 슬랙 메시지 전송 실패: {e}")

if __name__ == "__main__":
    df = fetch_oliveyoung_rankings()
    if df is not None and not df.empty:
        print(f"✅ {len(df)}개 상품 크롤링 성공")
        send_to_slack(df)
    else:
        print("🔴 최종 실패.")
