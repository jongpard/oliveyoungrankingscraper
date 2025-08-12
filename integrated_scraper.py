#!/usr/bin/env python3
"""
올리브영 통합 스크래퍼 - 드롭박스, Google Sheets, Slack 연동 포함
"""

import os
import asyncio
import json
import requests
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

# 환경변수 설정
KST = ZoneInfo("Asia/Seoul")
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK_URL")
DROPBOX_ACCESS_TOKEN = os.getenv("DROPBOX_ACCESS_TOKEN")
GOOGLE_SHEETS_CREDENTIALS = os.getenv("GOOGLE_SHEETS_CREDENTIALS")

# 올리브영 랭킹 페이지
BEST_URL = "https://www.oliveyoung.co.kr/store/main/getBestList.do"

# 상품 리스트 셀렉터
PRODUCT_LIST_SELECTORS = [
    "ul.cate_prd_list li",
    ".ranking_list .prd_info",
    "ul.tab_cont_list li",
    "ul.prd_list li",
    "div.best_prd_area ul li",
    "div#Container ul li",
]

# 상품 정보 추출 셀렉터
NAME_CANDIDATES = [
    ".tx_name", ".prd_name", ".name", "a .name", "strong", "a[title]", ".prd_info .name"
]
PRICE_CANDIDATES = [
    ".tx_cur", ".cur_price", ".price .num", ".price", ".won", ".cost", ".prd_info .price"
]
LINK_CANDIDATES = [
    "a", "a.prd_thumb", "a.prd_info", ".prd_info a"
]

def clean_price(text: str) -> float | None:
    """가격 텍스트에서 숫자만 추출"""
    if not text:
        return None
    import re
    m = re.findall(r"\d+", text.replace(",", ""))
    if not m:
        return None
    try:
        return float("".join(m))
    except:
        return None

def to_abs(url: str) -> str:
    """상대 URL을 절대 URL로 변환"""
    if not url:
        return ""
    if url.startswith("http"):
        return url
    return "https://www.oliveyoung.co.kr" + (url if url.startswith("/") else f"/{url}")

async def extract_first_text(card, selectors):
    """여러 셀렉터 중에서 첫 번째로 발견되는 텍스트 추출"""
    for sel in selectors:
        try:
            el = await card.query_selector(sel)
            if el:
                txt = (await el.get_attribute("title") or "").strip() or (await el.inner_text() or "").strip()
                if txt:
                    return txt
        except:
            continue
    return ""

async def extract_first_href(card, selectors):
    """여러 셀렉터 중에서 첫 번째로 발견되는 링크 추출"""
    for sel in selectors:
        try:
            el = await card.query_selector(sel)
            if el:
                href = await el.get_attribute("href") or ""
                if href:
                    return to_abs(href)
        except:
            continue
    return ""

async def wait_for_any_selector(page, selectors, timeout_ms=30000):
    """여러 후보 셀렉터 중 하나라도 등장할 때까지 대기"""
    for selector in selectors:
        try:
            await page.locator(selector).first.wait_for(state="visible", timeout=timeout_ms)
            print(f"✅ 셀렉터 '{selector}' 발견")
            return True
        except PWTimeout:
            print(f"⚠️ 셀렉터 '{selector}' 대기 시간 초과")
            continue
    return False

async def smart_scroll(page, step_px=800, max_rounds=10, pause_ms=500):
    """페이지 스크롤로 더 많은 상품 로드"""
    last_height = await page.evaluate("() => document.body.scrollHeight")
    rounds = 0
    while rounds < max_rounds:
        rounds += 1
        await page.evaluate(f"window.scrollBy(0, {step_px})")
        await page.wait_for_timeout(pause_ms)
        
        new_height = await page.evaluate("() => document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height

async def scrape_oliveyoung():
    """올리브영 베스트 상품 정보를 수집"""
    print("🔍 올리브영 랭킹 수집 시작")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas",
                "--no-first-run",
                "--no-zygote",
                "--disable-gpu"
            ]
        )
        
        page = await browser.new_page()
        
        # User-Agent 설정
        await page.set_extra_http_headers({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        
        # JavaScript 실행 방지 우회
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
        """)
        
        try:
            print(f"🌐 페이지 로딩 중: {BEST_URL}")
            await page.goto(BEST_URL, wait_until="domcontentloaded", timeout=60000)
            
            # 페이지 로딩 대기
            await page.wait_for_timeout(5000)
            
            # 상품 리스트 셀렉터 대기
            print("🔍 상품 리스트 요소 대기 중...")
            if not await wait_for_any_selector(page, PRODUCT_LIST_SELECTORS, timeout_ms=35000):
                print("❌ 상품 리스트를 찾을 수 없습니다.")
                return pd.DataFrame()
            
            # 스크롤로 더 많은 상품 로드
            print("📜 페이지 스크롤 중...")
            await smart_scroll(page)
            
            # 상품 정보 추출
            print("📊 상품 정보 추출 중...")
            products = []
            
            # 여러 셀렉터로 상품 찾기
            items = []
            for selector in PRODUCT_LIST_SELECTORS:
                try:
                    items = await page.query_selector_all(selector)
                    if items:
                        print(f"✅ 셀렉터 '{selector}'로 {len(items)}개 상품 발견")
                        break
                except:
                    continue
            
            if not items:
                print("❌ 어떤 셀렉터로도 상품을 찾을 수 없습니다.")
                return pd.DataFrame()
            
            for i, item in enumerate(items[:100]):  # 최대 100개
                try:
                    # 상품명 추출
                    name = await extract_first_text(item, NAME_CANDIDATES)
                    if not name:
                        continue
                    
                    # 가격 추출
                    price_text = await extract_first_text(item, PRICE_CANDIDATES)
                    price = clean_price(price_text)
                    
                    # 링크 추출
                    link = await extract_first_href(item, LINK_CANDIDATES)
                    
                    # 순위 추출 (인덱스 기반)
                    rank = i + 1
                    
                    products.append({
                        "rank": rank,
                        "title": name,
                        "price": price_text if price_text else "가격 정보 없음",
                        "price_num": price,
                        "link": link,
                        "timestamp": datetime.now(KST).isoformat()
                    })
                    
                except Exception as e:
                    print(f"⚠️ 상품 {i+1} 파싱 오류: {e}")
                    continue
            
            print(f"✅ 총 {len(products)}개 상품 정보 수집 완료")
            
            if not products:
                print("❌ 수집된 상품이 없습니다.")
                return pd.DataFrame()
            
            # DataFrame 생성
            df = pd.DataFrame(products)
            df = df.sort_values("rank").reset_index(drop=True)
            
            return df
            
        except Exception as e:
            print(f"❌ 스크래핑 오류: {e}")
            return pd.DataFrame()
        finally:
            await browser.close()

def save_to_files(df: pd.DataFrame):
    """데이터를 다양한 형식으로 저장"""
    today = datetime.now(KST).strftime("%Y-%m-%d")
    
    # JSON 저장
    json_filename = f"ranking_{today}.json"
    df.to_json(json_filename, orient="records", force_ascii=False, indent=2)
    print(f"💾 JSON 저장: {json_filename}")
    
    # CSV 저장
    csv_filename = f"oliveyoung_rankings_{today}.csv"
    df.to_csv(csv_filename, index=False, encoding="utf-8-sig")
    print(f"💾 CSV 저장: {csv_filename}")
    
    # Excel 저장
    try:
        excel_filename = f"oliveyoung_rankings_{today}.xlsx"
        df.to_excel(excel_filename, index=False)
        print(f"💾 Excel 저장: {excel_filename}")
    except Exception as e:
        print(f"⚠️ Excel 저장 실패: {e}")
    
    return json_filename, csv_filename

def upload_to_dropbox(file_path: str):
    """드롭박스에 파일 업로드"""
    if not DROPBOX_ACCESS_TOKEN:
        print("⚠️ DROPBOX_ACCESS_TOKEN이 설정되지 않았습니다.")
        return False
    
    try:
        import dropbox
        
        dbx = dropbox.Dropbox(DROPBOX_ACCESS_TOKEN)
        
        # 파일명만 추출
        filename = os.path.basename(file_path)
        
        # 드롭박스 경로 설정
        dropbox_path = f"/oliveyoung_rankings/{filename}"
        
        # 파일 업로드
        with open(file_path, 'rb') as f:
            dbx.files_upload(f.read(), dropbox_path, mode=dropbox.files.WriteMode.overwrite)
        
        print(f"✅ 드롭박스 업로드 성공: {dropbox_path}")
        return True
        
    except Exception as e:
        print(f"❌ 드롭박스 업로드 실패: {e}")
        return False

def upload_to_google_sheets(df: pd.DataFrame):
    """Google Sheets에 데이터 업로드"""
    if not GOOGLE_SHEETS_CREDENTIALS:
        print("⚠️ GOOGLE_SHEETS_CREDENTIALS가 설정되지 않았습니다.")
        return False
    
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        
        # Google Sheets API 권한 설정
        scope = [
            'https://spreadsheets.google.com/feeds',
            'https://www.googleapis.com/auth/drive'
        ]
        
        # 서비스 계정 키 파일에서 인증 정보 로드
        creds = Credentials.from_service_account_file(
            GOOGLE_SHEETS_CREDENTIALS, scopes=scope
        )
        
        client = gspread.authorize(creds)
        
        # 스프레드시트 열기 (없으면 생성)
        try:
            sheet = client.open("올리브영 랭킹")
        except:
            sheet = client.create("올리브영 랭킹")
        
        # 워크시트 선택 (첫 번째 시트)
        worksheet = sheet.get_worksheet(0)
        if not worksheet:
            worksheet = sheet.add_worksheet(title="랭킹 데이터", rows=1000, cols=10)
        
        # 헤더 추가
        headers = ["순위", "상품명", "가격", "가격(숫자)", "링크", "수집시간"]
        worksheet.update('A1:F1', [headers])
        
        # 데이터 준비
        data = []
        for _, row in df.iterrows():
            data.append([
                row['rank'],
                row['title'],
                row['price'],
                row['price_num'] if pd.notna(row['price_num']) else "",
                row['link'],
                row['timestamp']
            ])
        
        # 데이터 업로드
        if data:
            worksheet.update(f'A2:F{len(data)+1}', data)
        
        print(f"✅ Google Sheets 업로드 성공: {len(data)}개 행")
        return True
        
    except Exception as e:
        print(f"❌ Google Sheets 업로드 실패: {e}")
        return False

def send_to_slack(df: pd.DataFrame):
    """Slack으로 결과 전송"""
    if not SLACK_WEBHOOK:
        print("⚠️ SLACK_WEBHOOK_URL이 설정되지 않았습니다.")
        return False
    
    try:
        today = datetime.now(KST).strftime("%Y-%m-%d")
        
        message = f"*📊 {today} 올리브영 랭킹 TOP10*\n"
        
        for i, row in df.head(10).iterrows():
            rank = row['rank']
            title = row['title'][:50] + "..." if len(row['title']) > 50 else row['title']
            price = row['price']
            link = row['link']
            
            if link:
                message += f"{rank}. <{link}|{title}> — {price}\n"
            else:
                message += f"{rank}. {title} — {price}\n"
        
        payload = {"text": message}
        response = requests.post(SLACK_WEBHOOK, json=payload, timeout=10)
        response.raise_for_status()
        
        print("✅ Slack 메시지 전송 성공")
        return True
        
    except Exception as e:
        print(f"❌ Slack 메시지 전송 실패: {e}")
        return False

async def main():
    """메인 실행 함수"""
    print("🚀 올리브영 통합 스크래퍼 시작\n")
    
    # 1. 스크래핑 실행
    df = await scrape_oliveyoung()
    
    if df.empty:
        print("❌ 데이터 수집에 실패했습니다.")
        return
    
    # 2. 파일 저장
    json_file, csv_file = save_to_files(df)
    
    # 3. 드롭박스 업로드
    if DROPBOX_ACCESS_TOKEN:
        upload_to_dropbox(json_file)
        upload_to_dropbox(csv_file)
    else:
        print("💡 드롭박스 연동을 원한다면 DROPBOX_ACCESS_TOKEN 환경변수를 설정하세요.")
    
    # 4. Google Sheets 업로드
    if GOOGLE_SHEETS_CREDENTIALS:
        upload_to_google_sheets(df)
    else:
        print("💡 Google Sheets 연동을 원한다면 GOOGLE_SHEETS_CREDENTIALS 환경변수를 설정하세요.")
    
    # 5. Slack 전송
    if SLACK_WEBHOOK:
        send_to_slack(df)
    else:
        print("💡 Slack 연동을 원한다면 SLACK_WEBHOOK_URL 환경변수를 설정하세요.")
    
    # 6. 결과 요약
    print(f"\n🎉 스크래핑 완료!")
    print(f"📊 수집된 상품: {len(df)}개")
    print(f"📁 저장된 파일: {json_file}, {csv_file}")
    
    if DROPBOX_ACCESS_TOKEN:
        print("☁️ 드롭박스: 업로드 완료")
    if GOOGLE_SHEETS_CREDENTIALS:
        print("📊 Google Sheets: 업로드 완료")
    if SLACK_WEBHOOK:
        print("💬 Slack: 메시지 전송 완료")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️ 사용자에 의해 중단되었습니다.")
    except Exception as e:
        print(f"❌ 예상치 못한 오류: {e}")