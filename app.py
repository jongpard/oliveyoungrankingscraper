# app.py
import asyncio
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

KST = ZoneInfo("Asia/Seoul")

BEST_URL = "https://www.oliveyoung.co.kr/store/main/getBest.do"

# 사이트 개편/AB테스트 대응: 후보 셀렉터를 넓게 잡고, 첫 매칭을 사용
# (쉼표로 묶으면 "OR"처럼 동작)
PRODUCT_LIST_SELECTORS = [
    "ul.tab_cont_list li",           # 과거 셀렉터
    "ul.cate_prd_list li",           # 또 다른 과거 셀렉터
    "ul.prd_list li",                # 일반 리스트
    "div.best_prd_area ul li",       # 베스트 영역 리스트
    "div#Container ul li",           # 최후의 보루
]
# 각 카드 내부에서 시도할 하위 셀렉터(여러 후보)
NAME_CANDIDATES = [
    ".tx_name", ".prd_name", ".name", "a .name", "strong", "a[title]"
]
PRICE_CANDIDATES = [
    ".tx_cur", ".cur_price", ".price .num", ".price", ".won", ".cost"
]
RANK_CANDIDATES = [
    ".tx_num", ".num", ".rank", ".best_num", "em", "i"
]
LINK_CANDIDATES = [
    "a", "a.prd_thumb", "a.prd_info"
]

# 절대 URL로 변환
def to_abs(url: str) -> str:
    if not url:
        return ""
    if url.startswith("http"):
        return url
    return "https://www.oliveyoung.co.kr" + (url if url.startswith("/") else f"/{url}")

def extract_first_text(card, selectors):
    for sel in selectors:
        el = card.query_selector(sel)
        if el:
            txt = (el.get_attribute("title") or "").strip() or (el.inner_text() or "").strip()
            if txt:
                return txt
    return ""

def extract_first_href(card, selectors):
    for sel in selectors:
        el = card.query_selector(sel)
        if el:
            href = el.get_attribute("href") or ""
            if href:
                return to_abs(href)
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
    combined = ", ".join(selectors)
    await page.locator(combined).first.wait_for(state="visible", timeout=timeout_ms)

async def smart_scroll(page, step_px=1200, max_rounds=15, pause_ms=300):
    """
    무한 스크롤/지연 로딩 대비: 아래로 여러 번 스크롤
    """
    last_height = await page.evaluate("() => document.body.scrollHeight")
    rounds = 0
    while rounds < max_rounds:
        rounds += 1
        await page.mouse.wheel(0, step_px)
        await page.wait_for_timeout(pause_ms)
        new_height = await page.evaluate("() => document.body.scrollHeight")
        if new_height <= last_height:
            break
        last_height = new_height

async def scrape_oliveyoung(max_retries=3) -> pd.DataFrame:
    now_kst = datetime.now(KST)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
        ])
        context = await browser.new_context(
            locale="ko-KR",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
        )
        # 간단 스텔스: webdriver 감추기
        await context.add_init_script(
            """() => { Object.defineProperty(navigator, 'webdriver', { get: () => undefined }); }"""
        )
        page = await context.new_page()

        attempt = 0
        last_err = None
        while attempt < max_retries:
            attempt += 1
            try:
                print(f"🔍 올리브영 랭킹 수집 시작 (시도 {attempt}/{max_retries})")
                await page.goto(BEST_URL, wait_until="domcontentloaded", timeout=40000)
                # 네트워크 안정화
                await page.wait_for_load_state("networkidle", timeout=20000)

                # 어느 리스트든 보일 때까지 대기
                await wait_for_any_selector(page, [s.replace(" li", "") for s in PRODUCT_LIST_SELECTORS], timeout_ms=35000)

                # 스크롤로 지연 로딩 처리
                await smart_scroll(page)

                # 실제 카드 수집
                cards = None
                for sel in PRODUCT_LIST_SELECTORS:
                    loc = page.locator(sel)
                    count = await loc.count()
                    if count > 0:
                        cards = [loc.nth(i) for i in range(count)]
                        break

                if not cards:
                    raise RuntimeError("상품 카드를 찾지 못했습니다. 셀렉터가 변경된 것 같습니다.")

                results = []
                for card in cards:
                    handle = await card.element_handle()
                    if not handle:
                        continue

                    # DOM에서 안전 추출 (동기 방식으로 호출)
                    name = await handle.evaluate(
                        "(el, sels) => {"
                        "  for (const s of sels){const t=el.querySelector(s);"
                        "    if(t){const v=(t.getAttribute('title')||t.textContent||'').trim();"
                        "      if(v) return v;}} return ''; }",
                        NAME_CANDIDATES
                    )
                    price_text = await handle.evaluate(
                        "(el, sels) => {"
                        "  for (const s of sels){const t=el.querySelector(s);"
                        "    if(t){return (t.textContent||'').trim();}} return ''; }",
                        PRICE_CANDIDATES
                    )
                    rank_text = await handle.evaluate(
                        "(el, sels) => {"
                        "  for (const s of sels){const t=el.querySelector(s);"
                        "    if(t){return (t.textContent||'').trim();}} return ''; }",
                        RANK_CANDIDATES
                    )
                    link = await handle.evaluate(
                        "(el, sels) => {"
                        "  const toAbs = (u)=>{ if(!u) return ''; "
                        "    if(/^https?:\\/\\//i.test(u)) return u;"
                        "    return 'https://www.oliveyoung.co.kr' + (u.startsWith('/')? u : '/' + u); };"
                        "  for (const s of sels){const a=el.querySelector(s);"
                        "    if(a){const href=a.getAttribute('href'); if(href) return toAbs(href);}} return ''; }",
                        LINK_CANDIDATES
                    )

                    price = clean_price(price_text)
                    rank = clean_rank(rank_text)

                    # 비어있는 카드(광고/빈 li) 스킵
                    if not name and not link:
                        continue

                    results.append({
                        "수집일자": now_kst.strftime("%Y-%m-%d"),
                        "제품명": name,
                        "가격": price,
                        "링크": link,
                        "순위": rank,
                    })

                df = pd.DataFrame(results)

                # 오특: 순위가 NaN인 경우 True
                df["오특"] = df["순위"].isna()

                # 최소 검증: 데이터가 너무 적으면 실패로 처리 (사이트 일시 오류 방지)
                if len(df) < 5:
                    raise RuntimeError(f"수집 결과가 비정상적으로 적습니다. ({len(df)}건)")

                await context.close()
                await browser.close()
                return df

            except (PWTimeout, RuntimeError) as e:
                last_err = e
                print(f"⚠️ 시도 {attempt} 실패: {e}")
                # 새로고침 후 재시도
                try:
                    await page.reload(timeout=25000)
                    await page.wait_for_load_state("domcontentloaded", timeout=20000)
                except Exception:
                    pass

        # 모든 시도 실패
        if last_err:
            raise last_err
        raise RuntimeError("알 수 없는 이유로 수집에 실패했습니다.")

def save_csv_kst(df: pd.DataFrame) -> str:
    now_kst = datetime.now(KST)
    fname = now_kst.strftime("oliveyoung_rank_%Y%m%d.csv")
    df.to_csv(fname, index=False, encoding="utf-8-sig")
    return fname

if __name__ == "__main__":
    print("🔍 올리브영 랭킹 수집 시작 (Playwright 우회)")
    df_today = asyncio.run(scrape_oliveyoung())
    csv_path = save_csv_kst(df_today)
    print(f"✅ 수집 완료: {len(df_today)}건, CSV 저장: {csv_path}")

    # 디버깅 출력 (앞부분 미리보기)
    with pd.option_context("display.max_colwidth", 120):
        print(df_today.head(10))
