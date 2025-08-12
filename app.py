# app.py
import os
import asyncio
import pandas as pd
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import requests

# 환경변수
DROPBOX_TOKEN = os.environ.get("DROPBOX_ACCESS_TOKEN")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
BASE_URL = "https://www.oliveyoung.co.kr/store/main/getBestList.do"

# Dropbox 업로드
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

# Slack 메시지 전송
def send_slack_message(text):
    payload = {"text": text}
    r = requests.post(SLACK_WEBHOOK_URL, json=payload)
    if r.status_code == 200:
        print("✅ Slack 전송 성공")
    else:
        print(f"❌ Slack 전송 실패: {r.text}")

# 올리브영 크롤링
async def scrape_oliveyoung():
    print("🔍 올리브영 랭킹 수집 시작 (Playwright 우회)")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://www.oliveyoung.co.kr/store/main/main.do", timeout=60000)
        await page.click("text=랭킹")  # 랭킹 탭 클릭
        await page.wait_for_selector("ul.tab_cont_list")  # 제품 리스트 로딩 대기
        content = await page.content()
        await browser.close()

    soup = BeautifulSoup(content, "html.parser")
    items = soup.select("ul.tab_cont_list li")

    data = []
    rank = 1
    for item in items:
        name_tag = item.select_one("p.tx_name")
        price_tag = item.select_one("span.tx_num")
        link_tag = item.select_one("a")
        rank_tag = item.select_one("span.rank")

        if not name_tag or not price_tag or not link_tag:
            continue

        name = name_tag.get_text(strip=True)
        price = price_tag.get_text(strip=True)
        link = "https://www.oliveyoung.co.kr" + link_tag.get("href")

        # 순위 파싱
        if rank_tag and rank_tag.get_text(strip=True).isdigit():
            순위 = int(rank_tag.get_text(strip=True))
            오특 = ""
        else:
            순위 = rank
            오특 = "오특"

        data.append({
            "순위": 순위,
            "오특": 오특,
            "제품명": name,
            "가격": price,
            "링크": link
        })

        rank += 1

    return pd.DataFrame(data)

# 급상승·급하락 분석
def analyze_rank_changes(today_df, yesterday_df):
    merged = pd.merge(today_df, yesterday_df, on="제품명", how="outer", suffixes=("_오늘", "_어제"))
    merged["변화"] = merged["순위_어제"] - merged["순위_오늘"]

    rising = merged.dropna(subset=["순위_오늘", "순위_어제"]).sort_values("변화", ascending=False).head(5)
    new_entries = merged[merged["순위_어제"].isna()].sort_values("순위_오늘").head(5)
    falling = merged.dropna(subset=["순위_오늘", "순위_어제"]).sort_values("변화", ascending=True).head(5)

    return rising, new_entries, falling

# 메인 실행
if __name__ == "__main__":
    today_str = datetime.now().strftime("%Y-%m-%d")
    os.makedirs("rankings", exist_ok=True)
    csv_name = f"oliveyoung_{today_str}.csv"
    local_path = os.path.join("rankings", csv_name)

    df_today = asyncio.run(scrape_oliveyoung())
    df_today.to_csv(local_path, index=False, encoding="utf-8-sig")
    print(f"✅ CSV 저장 완료: {local_path}")

    yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday_path = os.path.join("rankings", f"oliveyoung_{yesterday_str}.csv")

    rising = new_entries = falling = pd.DataFrame()
    if os.path.exists(yesterday_path):
        df_yesterday = pd.read_csv(yesterday_path)
        rising, new_entries, falling = analyze_rank_changes(df_today, df_yesterday)

    # Dropbox 업로드
    upload_to_dropbox(local_path, f"/oliveyoung_rankings/{csv_name}")

    # Slack 메시지 생성
    msg = f":bar_chart: 올리브영 전체 랭킹 (국내) ({today_str})\n\n*TOP 10*\n"
    for i, row in df_today.head(10).iterrows():
        otek = "[오특] " if row["오특"] == "오특" else ""
        msg += f"{row['순위']}. {otek}<{row['링크']}|{row['제품명']}> — {row['가격']}\n"

    if not rising.empty:
        msg += "\n:arrow_up: *급상승 TOP 5*\n" + "\n".join(
            [f"- {row.제품명}: {int(row.순위_어제)}위 → {int(row.순위_오늘)}위 (▲{int(row.변화)})" for _, row in rising.iterrows()]
        )

    if not new_entries.empty:
        msg += "\n:new: *신규 진입*\n" + "\n".join(
            [f"- {row.제품명}: {int(row.순위_오늘)}위 (NEW)" for _, row in new_entries.iterrows()]
        )

    if not falling.empty:
        msg += "\n\n:arrow_down: *급하락 TOP 5*\n" + "\n".join(
            [f"- {row.제품명}: {int(row.순위_어제)}위 → {int(row.순위_오늘)}위 (▼{abs(int(row.변화))})" for _, row in falling.iterrows()]
        )

    send_slack_message(msg)
