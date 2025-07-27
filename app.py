import requests
import pandas as pd
import os
import glob
from datetime import datetime

DATA_DIR = "data"

def fetch_oliveyoung_rankings():
    """올리브영 모바일 API를 통해 실시간 랭킹 데이터를 가져옵니다."""
    url = "https://m.oliveyoung.co.kr/m/mc/main/getRankAll.do"
    headers = {'User-Agent': 'OliveYoungApp/7.2.1 (iOS; 15.4.1; iPhone)', 'Content-Type': 'application/json;charset=UTF-8'}
    payload = {"dispCatNo": "90000010001", "pageIdx": "1", "rowsPerPage": "100"}
    
    print("📥 올리브영 랭킹 크롤링 시작...")
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        items = response.json().get("bestList", [])
        if not items:
            raise ValueError("응답에서 'bestList'를 찾을 수 없습니다.")
        
        df = pd.DataFrame(items)
        df['rank'] = df['rnk'].astype(int)
        df['brand'] = df['brnd_nm']
        df['name'] = df['prdt_nm']
        return df[['rank', 'brand', 'name']].sort_values('rank').reset_index(drop=True)
    except Exception as e:
        print(f"❌ 크롤링 실패: {e}")
        return None

def save_rankings(df):
    """수집한 랭킹을 날짜별 CSV 파일로 저장합니다."""
    os.makedirs(DATA_DIR, exist_ok=True)
    today_str = datetime.now().strftime('%Y-%m-%d')
    filename = os.path.join(DATA_DIR, f"ranking_{today_str}.csv")
    df.to_csv(filename, index=False, encoding='utf-8-sig')
    print(f"💾 데이터 저장 완료: {filename}")
    return filename

def analyze_trends():
    """저장된 데이터를 바탕으로 랭킹 트렌드를 분석합니다."""
    print("📈 트렌드 분석 시작...")
    csv_files = sorted(glob.glob(os.path.join(DATA_DIR, "ranking_*.csv")), reverse=True)
    
    if len(csv_files) < 2:
        print("⚠️ 비교할 과거 데이터가 부족합니다.")
        return None, None

    today_df = pd.read_csv(csv_files[0])
    yesterday_df = pd.read_csv(csv_files[1])

    # 1. 급상승 브랜드 분석
    merged_df = pd.merge(today_df, yesterday_df, on='name', suffixes=('_today', '_yday'), how='left')
    merged_df['rank_change'] = merged_df['rank_yday'] - merged_df['rank_today']
    
    # 순위가 20 이상 급상승한 브랜드
    rising_brands = merged_df[merged_df['rank_change'] >= 20].sort_values('rank_change', ascending=False).head(3)
    # 새로 순위권에 진입한 브랜드 중 가장 순위가 높은 브랜드
    new_entries = merged_df[merged_df['rank_yday'].isna()].sort_values('rank_today').head(3)

    # 2. 인기 유지 브랜드 분석 (최근 7일 데이터 활용)
    recent_files = csv_files[:7]
    all_df = pd.concat([pd.read_csv(f) for f in recent_files])
    top_30_df = all_df[all_df['rank'] <= 30]
    
    # Top 30에 가장 많이 등장한 브랜드
    stable_brands = top_30_df['brand'].value_counts().head(3).index.tolist()

    analysis = {
        'rising': rising_brands,
        'new': new_entries,
        'stable': stable_brands,
        'today_df': today_df # 인기 유지 브랜드의 현재 순위 확인용
    }
    return analysis

def format_slack_message(analysis):
    """분석 결과를 슬랙 메시지 포맷으로 만듭니다."""
    if not analysis:
        return None
    
    # 급상승 브랜드 메시지 생성
    rising_texts = []
    for _, row in analysis['rising'].iterrows():
        rising_texts.append(f"• {row['brand_today']}: {int(row['rank_yday'])}위 → {row['rank_today']}위 (+{int(row['rank_change'])})")
    for _, row in analysis['new'].iterrows():
        rising_texts.append(f"• {row['brand_today']}: 첫 등장 {row['rank_today']}위")

    # 인기 유지 브랜드 메시지 생성
    stable_texts = []
    for brand_name in analysis['stable']:
        current_rank = analysis['today_df'][analysis['today_df']['brand'] == brand_name]['rank'].min()
        stable_texts.append(f"• {brand_name}: 인기 브랜드, 현재 {current_rank}위")

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "📈 오늘의 올리브영 랭킹 분석", "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "어떤 제품이 떠오르고 있는지 확인해보세요!"}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*🔥 급상승 브랜드*\n" + "\n".join(rising_texts)}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*⭐ 인기 유지 브랜드*\n" + "\n".join(stable_texts)}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}]}
    ]
    return {"text": "오늘의 올리브영 랭킹 분석 보고서", "blocks": blocks}

def send_to_slack(payload):
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url: return
    try:
        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        print("✅ 슬랙 메시지 전송 성공")
    except Exception as e:
        print(f"❌ 슬랙 메시지 전송 실패: {e}")

if __name__ == "__main__":
    df = fetch_oliveyoung_rankings()
    if df is not None and not df.empty:
        print(f"✅ {len(df)}개 상품 크롤링 성공")
        save_rankings(df)
        analysis_result = analyze_trends()
        slack_payload = format_slack_message(analysis_result)
        if slack_payload:
            send_to_slack(slack_payload)
    else:
        print("🔴 최종 실패.")
