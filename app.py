# app.py
import asyncio
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

KST = ZoneInfo("Asia/Seoul")

BEST_URL = "https://www.oliveyoung.co.kr/store/main/getBestList.do"

# 사이트 개편/AB테스트 대응: 후보 셀렉터를 넓게 잡고, 첫 매칭을 사용
# (쉼표로 묶으면 "OR"처럼 동작)
PRODUCT_LIST_SELECTORS = [
    "ul.tab_cont_list li",           # 과거 셀렉터
    "ul.cate_prd_list li",           # 또 다른 과거 셀렉터
    "ul.prd_list li",                # 일반 리스트
    "div.best_prd_area ul li",       # 베스트 영역 리스트
    "div#Container ul li",           # 최후의 보루
    ".ranking_list .prd_info",       # 랭킹 리스트
    ".cate_prd_list > li",           # 카테고리 상품 리스트
    "ul li",                         # 일반적인 리스트
]

# 각 카드 내부에서 시도할 하위 셀렉터(여러 후보)
NAME_CANDIDATES = [
    ".tx_name", ".prd_name", ".name", "a .name", "strong", "a[title]", ".prd_info .name"
]
PRICE_CANDIDATES = [
    ".tx_cur", ".cur_price", ".price .num", ".price", ".won", ".cost", ".prd_info .price"
]
RANK_CANDIDATES = [
    ".tx_num", ".num", ".rank", ".best_num", "em", "i", ".prd_info .rank"
]
LINK_CANDIDATES = [
    "a", "a.prd_thumb", "a.prd_info", ".prd_info a"
]

# 절대 URL로 변환
def to_abs(url: str) -> str:
    if not url:
        return ""
    if url.startswith("http"):
        return url
    return "https://www.oliveyoung.co.kr" + (url if url.startswith("/") else f"/{url}")

async def extract_first_text(card, selectors):
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

def clean_price(text: str) -> float | None:
    if not text:
        return None
    # 숫자만 잡아내기
    m = re.findall(r"\d+", text.replace(",", ""))
    if not m:
        return None
    try:
        return float("".join(m))
    except:
        return None

def clean_rank(text: str) -> float | None:
    if not text:
        return None
    m = re.search(r"\d+", text)
    if not m:
        return None
    try:
        return float(m.group())
    except:
        return None

async def wait_for_any_selector(page, selectors, timeout_ms=30000):
    """
    여러 후보 셀렉터 중 하나라도 등장할 때까지 대기.
    """
    # 각 셀렉터를 개별적으로 시도
    for selector in selectors:
        try:
            await page.locator(selector).first.wait_for(state="visible", timeout=timeout_ms)
            print(f"✅ 셀렉터 '{selector}' 발견")
            return True
        except PWTimeout:
            print(f"⚠️ 셀렉터 '{selector}' 대기 시간 초과")
            continue
    
    print("❌ 모든 셀렉터에서 요소를 찾을 수 없습니다.")
    return False

async def smart_scroll(page, step_px=1200, max_rounds=15, pause_ms=300):
    """
    무한 스크롤/지연 로딩 대비: 아래로 여러 번 스크롤
    """
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
    """
    올리브영 베스트 상품 정보를 수집합니다.
    """
    print("🔍 올리브영 랭킹 수집 시작 (Playwright 우회)")
    
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
            
            # 페이지 소스 확인
            content = await page.content()
            print(f"📄 페이지 내용 길이: {len(content)}")
            
            # 페이지 제목 확인
            title = await page.title()
            print(f"📋 페이지 제목: {title}")
            
            # 현재 URL 확인
            current_url = page.url
            print(f"🔗 현재 URL: {current_url}")
            
            # 상품 리스트 셀렉터 대기
            print("🔍 상품 리스트 요소 대기 중...")
            if not await wait_for_any_selector(page, PRODUCT_LIST_SELECTORS, timeout_ms=35000):
                print("⚠️ 상품 리스트를 찾을 수 없습니다. 다른 방법 시도...")
                
                # 페이지 내용에서 상품 관련 키워드 검색
                content_lower = content.lower()
                keywords = ["상품", "랭킹", "베스트", "제품", "상품명", "가격"]
                found_keywords = [kw for kw in keywords if kw in content_lower]
                
                if found_keywords:
                    print(f"✅ 페이지에 상품 관련 키워드 발견: {found_keywords}")
                    
                    # 다른 접근 방법 시도 - 더 일반적인 셀렉터
                    alternative_selectors = [
                        "li", "div", "a[href*='product']", "a[href*='goods']",
                        ".item", ".product", ".goods", "[class*='prd']", "[class*='item']"
                    ]
                    
                    print("🔄 대안 셀렉터로 시도 중...")
                    for selector in alternative_selectors:
                        try:
                            elements = await page.query_selector_all(selector)
                            if len(elements) > 0:
                                print(f"✅ 셀렉터 '{selector}'로 {len(elements)}개 요소 발견")
                                # 이 요소들을 상품으로 간주하고 처리
                                break
                        except:
                            continue
                    else:
                        print("❌ 대안 셀렉터로도 요소를 찾을 수 없습니다.")
                        return pd.DataFrame()
                else:
                    print("❌ 페이지에 상품 관련 내용을 찾을 수 없습니다.")
                    return pd.DataFrame()
            
            # 스크롤로 더 많은 상품 로드
            print("📜 페이지 스크롤 중...")
            await smart_scroll(page, step_px=800, max_rounds=10, pause_ms=500)
            
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
            else:
                # 대안 셀렉터 사용
                for selector in alternative_selectors:
                    try:
                        items = await page.query_selector_all(selector)
                        if len(items) > 0:
                            print(f"✅ 대안 셀렉터 '{selector}'로 {len(items)}개 요소 발견")
                            break
                    except:
                        continue
                else:
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
            
            # 결과 저장
            today = datetime.now(KST).strftime("%Y-%m-%d")
            filename = f"ranking_{today}.json"
            df.to_json(filename, orient="records", force_ascii=False, indent=2)
            print(f"💾 결과 저장: {filename}")
            
            return df
            
        except Exception as e:
            print(f"❌ 스크래핑 오류: {e}")
            return pd.DataFrame()
        finally:
            await browser.close()

if __name__ == "__main__":
    try:
        df_today = asyncio.run(scrape_oliveyoung())
        if not df_today.empty:
            print("\n📊 수집된 상품 정보:")
            print(df_today[["rank", "title", "price"]].head(10))
        else:
            print("❌ 데이터 수집에 실패했습니다.")
    except Exception as e:
        print(f"❌ 실행 오류: {e}")
