import requests
from playwright.sync_api import sync_playwright
import json
import os
from datetime import datetime

def scrape_oliveyoung_rankings():
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            )
            page = context.new_page()

            print("Navigating to Olive Young main page...")
            page.goto("https://www.oliveyoung.co.kr/store/main/main.do", timeout=120000)
            
            # 전략 변경: 페이지 전체가 안정화되길 기다리는 대신, 핵심 요소인 '검색창'이 나타날 때까지 최대 2분간 기다립니다.
            print("Waiting for a key element (#query) to appear...")
            page.wait_for_selector("#query", timeout=120000)
            print("Key element found. Page is ready.")

            api_url = "https://www.oliveyoung.co.kr/store/main/getBestList.do"
            payload = {
                "dispCatNo": "100000100010001",
                "pageIdx": "1",
                "rowsPerPage": "100",
                "sortBy": "BEST"
            }
            
            print("Sending API request from the browser's context...")
            api_response = page.request.post(api_url, data=payload)
            
            if not api_response.ok:
                print(f"API request failed with status {api_response.status}")
                browser.close()
                return None
            
            data = api_response.json()
            items = data.get("goodsList", [])
            
            top_products = []
            for idx, item in enumerate(items, start=1):
                name = item.get("goodsNm", "").strip()
                brand = item.get("brandNm", "").strip()
                top_products.append(f"{idx}. [{brand}] {name}")
            
            browser.close()
            return top_products

        except Exception as e:
            print(f"❌ An error occurred during scraping: {e}")
            if 'browser' in locals() and browser.is_connected():
                browser.close()
            return None

def send_to_slack(message_lines, is_error=False):
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url: return

    if is_error:
        text = f"🚨 올리브영 랭킹 수집 실패"
        error_message = message_lines[0] if message_lines else "알 수 없는 에러"
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{text}*"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": error_message}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}]}
        ]
    else:
        text = f"🏆 올리브영 랭킹 Top {len(message_lines[:10])}" if message_lines else "데이터 없음"
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{text}*"}},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(message_lines[:10]) if message_lines else ""}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}]}
        ]
    
    try:
        requests.post(webhook_url, json={"text": text, "blocks": blocks}, timeout=10).raise_for_status()
        print("✅ Slack message sent successfully")
    except Exception as e:
        print(f"❌ Failed to send Slack message: {e}")

if __name__ == "__main__":
    print("🔍 올리브영 랭킹 수집 시작 (Playwright 최종 안정화 모드)")
    rankings = scrape_oliveyoung_rankings()

    if rankings:
        print(f"✅ Successfully scraped {len(rankings)} items.")
        send_to_slack(rankings)
    else:
        print("❌ Scraping failed.")
        send_to_slack(["Playwright 실행 중 에러가 발생했습니다. 로그를 확인해주세요."], is_error=True)
