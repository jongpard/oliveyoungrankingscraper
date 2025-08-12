import os
import time
import json
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# Slack Webhook URL (GitHub Secrets에서 불러오기)
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK_URL")

# 올리브영 랭킹 페이지
URL = "https://www.oliveyoung.co.kr/store/main/getBestList.do"

def send_to_slack(message):
    """슬랙으로 메시지 전송"""
    if SLACK_WEBHOOK:
        payload = {"text": message}
        try:
            response = requests.post(SLACK_WEBHOOK, json=payload)
            response.raise_for_status()
            print("Slack 메시지 전송 성공")
        except Exception as e:
            print(f"Slack 메시지 전송 실패: {e}")
    else:
        print("SLACK_WEBHOOK_URL 환경변수가 설정되지 않았습니다.")

def scrape_oliveyoung():
    """올리브영 랭킹 데이터 크롤링"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        try:
            page.goto(URL, wait_until="networkidle")
            time.sleep(3)  # 페이지 로딩 대기
            
            # 페이지 소스 가져오기
            page_content = page.content()
            soup = BeautifulSoup(page_content, "html.parser")
            
            # 상품 정보 추출
            items = soup.select(".ranking_list .prd_info")
            if not items:
                # 다른 셀렉터 시도
                items = soup.select(".cate_prd_list > li")
            
            results = []
            for idx, item in enumerate(items[:10], start=1):
                try:
                    name_elem = item.select_one(".tx_name") or item.select_one(".prd_name") or item.select_one("a[title]")
                    price_elem = item.select_one(".tx_cur") or item.select_one(".cur_price") or item.select_one(".price")
                    
                    if name_elem:
                        name = name_elem.get_text(strip=True) or name_elem.get("title", "").strip()
                    else:
                        name = "상품명 없음"
                    
                    if price_elem:
                        price = price_elem.get_text(strip=True)
                    else:
                        price = "가격 정보 없음"
                    
                    results.append(f"{idx}위: {name} - {price}")
                except Exception as e:
                    print(f"상품 {idx} 파싱 오류: {e}")
                    results.append(f"{idx}위: 파싱 오류")
            
            browser.close()
            return "\n".join(results) if results else "상품 정보를 찾을 수 없습니다."
            
        except Exception as e:
            browser.close()
            raise e

if __name__ == "__main__":
    try:
        print("올리브영 랭킹 크롤링 시작...")
        ranking_text = scrape_oliveyoung()
        print("크롤링 결과:")
        print(ranking_text)
        
        if SLACK_WEBHOOK:
            send_to_slack(f"📊 오늘의 올리브영 랭킹 Top 10\n{ranking_text}")
        else:
            print("Slack 웹훅이 설정되지 않아 메시지를 전송하지 않습니다.")
            
    except Exception as e:
        error_msg = f"❌ 랭킹 크롤링 실패: {str(e)}"
        print(error_msg)
        if SLACK_WEBHOOK:
            send_to_slack(error_msg)
