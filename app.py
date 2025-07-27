import requests
import pandas as pd
import os
from datetime import datetime

def fetch_oliveyoung_rankings():
    """
    올리브영의 모바일 실시간 랭킹 API를 직접 호출하여 데이터를 가져옵니다.
    이것이 현재 다른 개발자들이 성공적으로 사용하는 방식입니다.
    """
    # 다른 개발자들의 성공 사례에서 발견한 '숨겨진' 모바일 API 엔드포인트
    url = "https://m.oliveyoung.co.kr/m/mc/main/getRankAll.do"
    
    # 모바일 앱인 것처럼 위장하기 위한 헤더
    headers = {
        'User-Agent': 'OliveYoungApp/7.2.1 (iOS; 15.4.1; iPhone)',
        'Content-Type': 'application/json;charset=UTF-8'
    }

    # API가 요구하는 '주문서' (카테고리 번호가 핵심)
    payload = {
        "dispCatNo": "90000010001", # 실시간 랭킹 전체 카테고리
        "pageIdx": "1",
        "rowsPerPage": "100"
    }

    print("📥 올리브영 랭킹 크롤링 시작 (모바일 API 직접 호출 방식)")
    
    try:
        # GET이 아닌 POST 방식으로, '주문서(payload)'를 JSON 형태로 전송
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status() # 요청이 실패하면 여기서 에러 발생

        items = response.json().get("bestList", [])
        if not items:
            print("❌ 응답에서 'bestList'를 찾을 수 없습니다.")
            return None
        
        # 데이터를 DataFrame으로 변환하여 처리
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
    """
    결과를 Slack으로 전송합니다.
    """
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("⚠️ SLACK_WEBHOOK_URL이 설정되지 않았습니다.")
        return

    # 슬랙 메시지로 보낼 텍스트 생성 (상위 10개)
    top_10_list = []
    for index, row in df.head(10).iterrows():
        top_10_list.append(f"{row['rank']}. [{row['brand']}] {row['name']}")
    
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
        print("🔴 최종 실패. Slack으로 실패 알림을 보내지 않습니다.")
