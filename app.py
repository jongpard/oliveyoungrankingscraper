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

def upload_to_dropbox(local_path, dropbox_path):
    with open(local_path, "rb") as f:
        data = f.read()
    headers = {
        "Authorization": f"Bearer {DROPBOX_TOKEN}",
        "Dropbox-API-Arg": f'{{"path": "{dropbox_path}", "mode": "overwrite"}}',
        "Content-Type": "application/octet-stream"
    }
    r = requests.post("https://content.dropboxapi.com/2/files/upload", headers=headers, data=data)
    print("✅ Dropbox 업로드 성공" if r.status_code == 200 else f"❌ Dropbox 업로드 실패: {r.text}")

def send_slack_message(text):
    payload = {"text": text}
    r = requests.post(SLACK_WEBHOOK_URL, json=payload)
    print("✅ Slack 전송 성공" if r.status_code == 200 else f"❌ Slack 전송 실패: {r.text}")

async def scrape_oliveyoung():
    print("🔍 올리브영 랭킹 수집 시작 (Playwright 우회)")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(BASE_URL, timeout=60000)
        content = await page.content()
        await browser.close()

    soup = BeautifulSoup(content, "html.parser")
    items = soup.select("ul.cate_prd_list li")

    data = []
    real_rank = 1

    for item in items:
        name_tag = item.select_one("p.tx_name")
        price_tag = item.select_one("span.tx_num")
        link_tag = item.select_one("a")
        rank_tag = item.select_one("span.rank_num")

        name = name_tag.get_text(strip=True) if name_tag else "이름 없음"
        price = price_tag.get_text(strip=True) if price_tag else "-"
        link = "https://www.oliveyoung.co.kr" + link_tag["href"] if link_tag else ""

        rank_raw = rank_tag.get_text(strip=True) if rank_tag else ""
        is_special = "오특" in rank_raw or not rank_raw.isdigit()

        rank_display = f"[오특]" if is_special else str(real_rank)
        name_display = f"[오특] {name}" if is_special else name
        name_linked = f"<{link}|{name_display}>"

        data.append({"순위": rank_display, "제품명": name_linked, "가격": price})

        if not is_special:
            real_rank += 1

    return pd.DataFrame(data)

def analyze_rank_changes(today_df, yesterday_df):
    def clean_name(x):
        return BeautifulSoup(x, "html.parser").text.replace("[오특]", "").strip()

    today_df["제품명_비교"] = today_df["제품명"].apply(clean_name)
    yesterday_df["제품명_비교"] = yesterday_df["제품명"].apply(clean_name)

    df_today_ranked = today_df[today_df["순위"] != "[오특]"].copy()
    df_today_ranked["순위"] = pd.to_numeric(df_today_ranked["순위"])

    df_yesterday_ranked = yesterday_df[yesterday_df["순위"] != "[오특]"].copy()
    df_yesterday_ranked["순위"] = pd.to_numeric(df_yesterday_ranked["순위"])

    merged = pd.merge(df_today_ranked, df_yesterday_ranked, on="제품명_비교", how="outer", suffixes=("_오늘", "_어제"))
    merged["변화"] = merged["순위_어제"] - merged["순위_오늘"]

    rising = merged.dropna().sort_values("변화", ascending=False).head(5)
    new_entries = merged[merged["순위_어제"].isna()].sort_values("순위_오늘").head(5)
    falling = merged.dropna().sort_values("변화", ascending=True).head(5)

    return rising, new_entries, falling

if __name__ == "__main__":
    today = datetime.now().strftime("%Y-%m-%d")
    os.makedirs("rankings", exist_ok=True)
    filename = f"oliveyoung_{today}.csv"
    local_path = os.path.join("rankings", filename)

    df_today = asyncio.run(scrape_oliveyoung())
    df_today.to_csv(local_path, index=False, encoding="utf-8-sig")
    print(f"✅ CSV 저장 완료: {local_path}")

    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday_path = os.path.join("rankings", f"oliveyoung_{yesterday}.csv")

    rising = new_entries = falling = pd.DataFrame()
    if os.path.exists(yesterday_path):
        df_yesterday = pd.read_csv(yesterday_path)
        rising, new_entries, falling = analyze_rank_changes(df_today, df_yesterday)

    upload_to_dropbox(local_path, f"/oliveyoung_rankings/{filename}")

    # 슬랙 메시지 구성
    msg = f":bar_chart: 올리브영 전체 랭킹 (국내) ({today})\n\n"
    msg += "*TOP 10*\n"
    msg += "\n".join([f"{row['순위']}. {row['제품명']} — {row['가격']}" for _, row in df_today.head(10).iterrows()])

    if not rising.empty:
        msg += "\n\n:arrow_up: *급상승 TOP 5*\n"
        for _, row in rising.iterrows():
            msg += f"- {row['제품명_오늘']}: {int(row['순위_어제'])}위 → {int(row['순위_오늘'])}위 (▲{int(row['변화'])})\n"

    if not new_entries.empty:
        msg += "\n:new: *신규 진입*\n"
        for _, row in new_entries.iterrows():
            msg += f"- {row['제품명_오늘']}: {int(row['순위_오늘'])}위 (NEW)\n"

    if not falling.empty:
        msg += "\n\n:arrow_down: *급하락 TOP 5*\n"
        for _, row in falling.iterrows():
            msg += f"- {row['제품명_오늘']}: {int(row['순위_어제'])}위 → {int(row['순위_오늘'])}위 (▼{abs(int(row['변화']))})\n"

    send_slack_message(msg)
