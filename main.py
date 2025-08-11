import os
import time
import json
import requests
from bs4 import BeautifulSoup
import undetected_chromedriver as uc
from selenium.webdriver.chrome.options import Options

# Slack Webhook URL (GitHub Secrets에서 불러오기)
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK_URL")

# 올리브영 랭킹 페이지
URL = "https://www.oliveyoung.co.kr/store/main/getBestList.do"

def send_to_slack(message):
    """슬랙으로 메시지 전송"""
    payload = {"text": message}
    requests.post(SLACK_WEBHOOK, json=payload)

def scrape_oliveyoung():
    """올리브영 랭킹 데이터 크롤링"""
    options = Options()
    options.headless = True
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = uc.Chrome(options=options)
    driver.get(URL)
    time.sleep(3)  # 페이지 로딩 대기

    soup = BeautifulSoup(driver.page_source, "html.parser")
    driver.quit()

    items = soup.select(".ranking_list .prd_info")
    results = []
    for idx, item in enumerate(items[:10], start=1):
        name = item.select_one(".tx_name").get_text(strip=True)
        price = item.select_one(".tx_cur").get_text(strip=True)
        results.append(f"{idx}위: {name} - {price}")
    return "\n".join(results)

if __name__ == "__main__":
    try:
        ranking_text = scrape_oliveyoung()
        send_to_slack(f"📊 오늘의 올리브영 랭킹 Top 10\n{ranking_text}")
    except Exception as e:
        send_to_slack(f"❌ 랭킹 크롤링 실패: {str(e)}")
