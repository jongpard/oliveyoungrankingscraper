import requests
from playwright.sync_api import sync_playwright
from playwright_stealth.sync import Stealth # '투명 망토'를 올바른 방식으로 불러옵니다.
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

            # 브라우저에 '투명 망토'를 올바른 방식으로 적용합니다.
            Stealth.apply(page)

            print("Navigating to Olive Young main page with STEALTH mode...")
            page.goto("https://www.oliveyoung.co.kr/store/main/main.do", timeout=120000)
            
            print("Waiting for the page to pass security checks...")
            # 페이지의 제목이 'OLIVEYOUNG'으로 바뀔 때까지 기다립니다. (보안 페이지 통과 확인)
            page.wait_for_function("document.title.includes('OLIVEYOUNG')", timeout=120000)
            print("Security check passed. Page is ready.")

            api_url = "https://www.oliveyoung.co.kr/store/main/getBestList.do"
            payload = { "dispCatNo": "100000100010001", "pageIdx": "1", "rowsPerPage": "100", "sortBy": "BEST" }
            
            print("Sending API request from the stealthy browser's context...")
            api_response = page.request.post(api_url, data=payload)
            
            if not api_response.ok:
                raise Exception(f"API request failed with status {api_response.status}")
            
            data = api_response.json()
            items = data.get("goodsList", [])
            
            top_products = [f"{idx+1}. [{item.get('brandNm', '').strip()}] {item.get('goodsNm', '').strip()}" for idx, item in enumerate(items)]
            
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
    else:
        text = f"🏆 올리브영 랭킹 Top {len(message_lines[:10])}" if message_lines else "데이터 없음"

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{text}*"}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(message_lines[:10]) if not is_error and message_lines else (error_message if is_error else "")}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}]}
    ]
    
    try:
        requests.post(webhook_url, json={"text": text, "blocks": blocks}, timeout=10).raise_for_status()
        print("✅ Slack message sent successfully")
    except Exception as e:
        print(f"❌ Failed to send Slack message: {e}")

if __name__ == "__main__":
    print("🔍 올리브영 랭킹 수집 시작 (Playwright + STEALTH 최종 모드)")
    rankings = scrape_oliveyoung_rankings()

    if rankings:
        print(f"✅ Successfully scraped {len(rankings)} items.")
        send_to_slack(rankings)
    else:
        print("❌ Scraping failed.")
        send_to_slack(["Cloudflare 보안 페이지를 통과하지 못했습니다."], is_error=True)
