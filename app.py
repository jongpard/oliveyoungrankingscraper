# app.py
import os
import asyncio
import pandas as pd
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import requests
import pytz

# 환경변수
DROPBOX_TOKEN = os.environ.get("DROPBOX_ACCESS_TOKEN")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

BASE_URL = "https://www.oliveyoung.co.kr/store/main/getBestList.do"

# 한국 시간 기준 날짜
def get_kst_now():
    return datetime.now(pytz.timezone("Asia/Seoul"))

# Dropbox 업로드
def upload_to_dropbox(local_path, dropbox_path):
    with open(local_path, "rb") as f:
        data = f.read()
    headers = {
        "Authorization": f"Bearer {DROPBOX_TOKEN}",
        "Dropbox-API-Arg": '{"path": "' + dropbox_path + '", "mode": "overwrite"}',
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
        await page.goto(BASE_URL, timeout=60000)
        await page.wait_for_selector("ul.tab_cont_list", timeout=30000)  # 제품 로딩 대기
        html = await page.content()
        await browser.close()

    soup = BeautifulSoup(html, "html.parser")
    names = soup.select("p.tx_name")
    prices = soup.select("span.tx_num")
    links = [a["href"] for a in soup.select("a.thumb_flag") if a.get("href")]

    data = []
    rank = 1
    for name_tag, price_tag, link in zip(names, prices, links):
        name = name_tag.get_text(strip=True)
        price = price_tag.get_text(strip=True)
        product_url = f"https://www.oliveyoung.co.kr{link}"
        data.append({
            "순위": rank,
            "제품명": name,
            "가격": price,
            "링크": product_url,
        })
        rank += 1

    return pd.DataFrame(data)

# 메인 실행
if __name__ == "__main__":
    now_kst = get_kst_now()
    today_str = now_kst.strftime("%Y-%m-%d")
    os.makedirs("rankings", exist_ok=True)
    csv_name = f"oliveyoung_{today_str}.csv"
    local_path = os.path.join("rankings", csv_name)

    # 데이터 수집
    df_today = asyncio.run(scrape_oliveyoung())

    # 파일 저장
    df_today.to_csv(local_path, index=False, encoding="utf-8-sig")
    print(f"✅ CSV 저장 완료: {local_path}")

    # Dropbox 업로드
    upload_to_dropbox(local_path, f"/oliveyoung_rankings/{csv_name}")

    # Slack 메시지
    msg = f":bar_chart: 올리브영 전체 랭킹 (국내) ({today_str})\n\n"
    msg += "*TOP 10*\n"
    for _, row in df_today.head(10).iterrows():
        msg += f"{row['순위']}. <{row['링크']}|{row['제품명']}> — {row['가격']}\n"

    send_slack_message(msg)
