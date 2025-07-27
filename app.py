import requests # 슬랙 메시지 전송을 위해 다시 추가!
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

            print("Navigating to Olive Young main page to solve challenges...")
            page.goto("https://www.oliveyoung.co.kr/store/main/main.do", timeout=60000)
            
            # 페이지가 로드될 때까지 잠시 대기 (Cloudflare가 JS 챌린지를 해결할 시간)
            page.wait_for_load_state('networkidle')
            print("Page loaded and challenges should be solved.")

            api_url = "https://www.oliveyoung.co.kr/store/main/getBestList.do"
            payload = {
                "dispCatNo": "100000100010001",
                "pageIdx": "1",
                "rowsPerPage": "100",
                "sortBy": "BEST"
            }
            
            print("Sending API request from browser context...")
            # page.request는 현재 브라우저의 모든 쿠키와 상태를 가지고 요청함
            api_response = page.request.post(api_url, data=payload)
            
            if not api_response.ok:
                print(f"API request failed with status {api_response.status}")
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
            return None

def send_to_slack(message_lines, is_error=False):
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url: return

    if is_error:
        text = f"🚨 올리브영 랭킹 수집 실패\n{message_lines[0]}"
    else:
        text = f"🏆 올리브영 랭킹 Top {len(message_lines[:10])}"

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{text}*"}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(message_lines[:10]) if not is_error and message_lines else ""}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}]}
    ]
    
    try:
        requests.post(webhook_url, json={"text": text, "blocks": blocks}, timeout=10).raise_for_status()
        print("✅ Slack message sent successfully")
    except Exception as e:
        print(f"❌ Failed to send Slack message: {e}")

if __name__ == "__main__":
    print("🔍 올리브영 랭킹 수집 시작 (Playwright 모드)")
    rankings = scrape_oliveyoung_rankings()

    if rankings:
        print(f"✅ Successfully scraped {len(rankings)} items.")
        send_to_slack(rankings)
    else:
        print("❌ Scraping failed.")
        send_to_slack(["Playwright 실행 중 에러가 발생했습니다. 로그를 확인해주세요."], is_error=True)
