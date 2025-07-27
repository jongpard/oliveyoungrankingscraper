import requests
import pandas as pd
import os
from datetime import datetime

def fetch_oliveyoung_rankings():
    """
    올리브영의 실시간 랭킹 API를 직접 호출하여 데이터를 가져옵니다.
    """
    # 다른 개발자들의 성공 사례에서 발견한 실제 API 엔드포인트
    url = "https://m.oliveyoung.co.kr/m/mc/main/getRankAll.do"
    
    print("📥 올리브영 랭킹 크롤링 시작")
    response = requests.get(url)
    
    if response.status_code != 200:
        print(f"❌ 요청 실패: 상태 코드 {response.status_code}")
        return None

    try:
        # 이 API는 HTML이 아닌 순수한 JSON 데이터를 반환합니다.
        items = response.json().get("bestList", [])
        if not items:
            print("❌ 응답에서 'bestList'를 찾을 수 없습니다.")
            return None
        
        # 데이터를 DataFrame으로 변환하여 처리
        df = pd.DataFrame(items)
        df['rank'] = df['rnk'].astype(int)
        df['brand'] = df['brnd_nm']
        df['name'] = df['prdt_nm']
        df = df.sort_values('rank').reset_index(drop=True)
        
        return df

    except Exception as e:
        print(f"❌ 데이터 처리 중 에러 발생: {e}")
        print("서버 응답 (첫 500자):", response.text[:500])
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
        print("🔴 최종 실패")
        # 실패 시에는 별도의 알림을 보내지 않거나, 실패 알림을 보낼 수 있습니다.
