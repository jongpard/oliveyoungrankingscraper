import os
import requests
import pandas as pd
from datetime import datetime
from bs4 import BeautifulSoup

# 환경변수
DROPBOX_TOKEN = os.environ.get("DROPBOX_ACCESS_TOKEN")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

# 올리브영 랭킹 페이지 URL
BASE_URL = "https://www.oliveyoung.co.kr/store/main/getBestList.do"

# Dropbox 업로드 함수
def upload_to_dropbox(local_path, dropbox_path):
    with open(local_path, "rb") as f:
        data = f.read()
    headers = {
        "Authorization": f"Bearer {DROPBOX_TOKEN}",
        "Dropbox-API-Arg": f'{{"path": "{dropbox_path}", "mode": "overwrite"}}',
        "Content-Type": "application/octet-stream"
    }
    r = requests.post("https://content.dropboxapi.com/2/files/upload", headers=headers, data=data)
    if r.status_code == 200:
        print(f"✅ Dropbox 업로드 성공: {dropbox_path}")
    else:
        print(f"❌ Dropbox 업로드 실패: {r.text}")

# Slack 메시지 전송 함수
def send_slack_message(text):
    payload = {"text": text}
    r = requests.post(SLACK_WEBHOOK_URL, json=payload)
    if r.status_code == 200:
        print("✅ Slack 전송 성공")
    else:
        print(f"❌ Slack 전송 실패: {r.text}")

# 올리브영 랭킹 크롤링
def scrape_oliveyoung():
    print("🔍 올리브영 랭킹 수집 시작")
    resp = requests.get(BASE_URL)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    items = soup.select("p.tx_name")
    prices = soup.select("span.tx_num")

    data = []
    rank = 1
    for name_tag, price_tag in zip(items, prices):
        name = name_tag.get_text(strip=True)
        price = price_tag.get_text(strip=True)
        data.append({
            "순위": rank,
            "제품명": name,
            "가격": price
        })
        rank += 1

    df = pd.DataFrame(data)
    return df

# 급상승/급하락 분석
def analyze_rank_changes(today_df, yesterday_df):
    merged = pd.merge(today_df, yesterday_df, on="제품명", how="outer", suffixes=("_오늘", "_어제"))
    merged["변화"] = merged["순위_어제"] - merged["순위_오늘"]

    # 급상승: 어제보다 순위가 많이 올라간 순
    rising = merged.dropna(subset=["순위_오늘", "순위_어제"]).sort_values("변화", ascending=False).head(5)

    # 신규 진입
    new_entries = merged[merged["순위_어제"].isna()].sort_values("순위_오늘").head(5)

    # 급하락: 어제보다 순위가 많이 떨어진 순
    falling = merged.dropna(subset=["순위_오늘", "순위_어제"]).sort_values("변화", ascending=True).head(5)

    return rising, new_entries, falling

if __name__ == "__main__":
    today = datetime.now().strftime("%Y-%m-%d")
    csv_name = f"oliveyoung_{today}.csv"
    local_path = os.path.join("rankings", csv_name)
    os.makedirs("rankings", exist_ok=True)

    df_today = scrape_oliveyoung()
    df_today.to_csv(local_path, index=False, encoding="utf-8-sig")
    print(f"✅ CSV 저장 완료: {local_path}")

    # 어제 데이터 불러오기
    yesterday_date = (datetime.now() - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday_path = os.path.join("rankings", f"oliveyoung_{yesterday_date}.csv")

    rising, new_entries, falling = [], [], []
    if os.path.exists(yesterday_path):
        df_yesterday = pd.read_csv(yesterday_path)
        rising, new_entries, falling = analyze_rank_changes(df_today, df_yesterday)

    # Dropbox 업로드
    upload_to_dropbox(local_path, f"/oliveyoung_rankings/{csv_name}")

    # Slack 메시지 구성
    msg = f":bar_chart: 올리브영 전체 랭킹 (국내) ({today})\n\n"

    msg += "*TOP 10*\n"
    msg += "\n".join([f"{row.순위}. {row.제품명} — {row.가격}" for _, row in df_today.head(10).iterrows()])

    if len(rising) > 0:
        msg += "\n\n:arrow_up: *급상승 TOP 5*\n"
        for _, row in rising.iterrows():
            msg += f"- {row.제품명}: {int(row.순위_어제)}위 → {int(row.순위_오늘)}위 (▲{int(row.변화)})\n"

    if len(new_entries) > 0:
        msg += "\n:new: *신규 진입*\n"
        for _, row in new_entries.iterrows():
            msg += f"- {row.제품명}: {int(row.순위_오늘)}위 (NEW)\n"

    if len(falling) > 0:
        msg += "\n:arrow_down: *급하락 TOP 5*\n"
        for _, row in falling.iterrows():
            msg += f"- {row.제품명}: {int(row.순위_어제)}위 → {int(row.순위_오늘)}위 (▼{abs(int(row.변화))})\n"

    # Slack 발송
    send_slack_message(msg)
