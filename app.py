# app.py
import asyncio
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

KST = ZoneInfo("Asia/Seoul")
BEST_URL = "https://www.oliveyoung.co.kr/store/main/getBest.do"

PRODUCT_LIST_SELECTORS = [
    "ul.tab_cont_list li",
    "ul.cate_prd_list li",
    "ul.prd_list li",
    "div.best_prd_area ul li",
    "div#Container ul li",
]

NAME_CANDIDATES = [".tx_name", ".prd_name", ".name", "a .name", "strong", "a[title]"]
PRICE_CANDIDATES = [".tx_cur", ".cur_price", ".price .num", ".price", ".won", ".cost"]
RANK_CANDIDATES = [".tx_num", ".num", ".rank", ".best_num", "em", "i"]
LINK_CANDIDATES = ["a", "a.prd_thumb", "a.prd_info"]

def to_abs(url: str) -> str:
    if not url:
        return ""
    if url.startswith("http"):
        return url
    return "https://www.oliveyoung.co.kr" + (url if url.startswith("/") else f"/{url}")

def clean_price(text: str):
    if not text: return None
    m = re.findall(r"\d+", text.replace(",", ""))
    if not m: return None
    try: return float("".join(m))
    except: return None

def clean_rank(text: str):
    if not text: return None
    m = re.search(r"\d+", text)
    if not m: return None
    try: return float(m.group())
    except: return None

async def close_popups(page):
    # 쿠키/약관/광고 팝업 대충 닫기
    candidates = [
        "button:has-text('동의')", "button:has-text('확인')", "button:has-text('닫기')",
        "a:has-text('동의')", "a:has-text('확인')", "a:has-text('닫기')",
        "#chkToday", ".btnClose", ".btn-close", ".oy-cookie-accept",
        "div.layerPop button", "div.popup button"
    ]
    for sel in candidates:
        try:
            btn = page.locator(sel)
            if await btn.count() > 0:
                await btn.first.click(timeout=1000)
                await page.wait_for_timeout(300)
        except Exception:
            pass

async def wait_product_list(page, timeout_ms=35000):
    # 1) attached(붙기만 해도) → 2) visible(보일 때까지) → 3) 개수 검증
    roots = [s.replace(" li", "") for s in PRODUCT_LIST_SELECTORS]
    combined_root = ", ".join(roots)
    try:
        await page.locator(combined_root).first.wait_for(state="attached", timeout=timeout_ms//2)
    except PWTimeout:
        # 최후: 개수 함수로 재시도
        pass

    try:
        await page.locator(combined_root).first.wait_for(state="visible", timeout=timeout_ms//2)
    except PWTimeout:
        # 일부 환경에서 display 처리 지연 → 개수 검사로 넘어감
        pass

    # li가 5개 이상 붙으면 성공으로 간주
    selectors_js_array = "[" + ",".join([f"'{s}'" for s in PRODUCT_LIST_SELECTORS]) + "]"
    await page.wait_for_function(
        """(sels) => {
            for (const s of sels){
              const els = document.querySelectorAll(s);
              if (els && els.length >= 5) return true;
            }
            return false;
        }""",
        arg=PRODUCT_LIST_SELECTORS,
        timeout=timeout_ms
    )

async def smart_scroll(page, step_px=1200, max_rounds=15, pause_ms=300):
    last_h = await page.evaluate("() => document.body.scrollHeight")
    for _ in range(max_rounds):
        await page.mouse.wheel(0, step_px)
        await page.wait_for_timeout(pause_ms)
        new_h = await page.evaluate("() => document.body.scrollHeight")
        if new_h <= last_h:
            break
        last_h = new_h

async def dump_debug(page, prefix="debug"):
    os.makedirs("artifacts", exist_ok=True)
    try:
        await page.screenshot(path=f"artifacts/{prefix}.png", full_page=True)
    except Exception:
        pass
    try:
        html = await page.content()
        with open(f"artifacts/{prefix}.html", "w", encoding="utf-8") as f:
            f.write(html)
    except Exception:
        pass
    # 콘솔 대비 본문 일부 로그
    try:
        text_preview = await page.eval_on_selector("body", "el => el.innerText.slice(0, 2000)")
        print("----- BODY PREVIEW -----")
        print(text_preview)
        print("----- /BODY PREVIEW -----")
    except Exception:
        pass

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
            java_script_enabled=True,
            extra_http_headers={
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            },
        )
        await context.add_init_script("""
            () => {
              Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
              Object.defineProperty(navigator, 'languages', { get: () => ['ko-KR','ko','en-US','en'] });
              Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3] });
            }
        """)
        page = await context.new_page()

        attempt = 0
        last_err = None
        while attempt < max_retries:
            attempt += 1
            try:
                print(f"🔍 올리브영 랭킹 수집 시작 (시도 {attempt}/{max_retries})")
                await page.goto(BEST_URL, wait_until="load", timeout=50000)
                await page.wait_for_load_state("domcontentloaded", timeout=30000)
                await close_popups(page)

                # 네트워크가 잠잠해진 뒤 잠깐 대기(지연 렌더링 대비)
                try:
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass
                await page.wait_for_timeout(500)

                # 스크롤 로딩
                await smart_scroll(page)
                await close_popups(page)

                # 제품 리스트 대기(보이든, 붙어있든, 개수든 무엇이든)
                await wait_product_list(page, timeout_ms=40000)

                # 가장 많은 li를 가진 셀렉터 선택
                best_sel = None
                best_cnt = 0
                for sel in PRODUCT_LIST_SELECTORS:
                    cnt = await page.locator(sel).count()
                    if cnt > best_cnt:
                        best_cnt = cnt
                        best_sel = sel
                if not best_sel or best_cnt == 0:
                    raise RuntimeError("상품 리스트가 비어 있습니다.")

                loc = page.locator(best_sel)
                cards = [loc.nth(i) for i in range(await loc.count())]

                results = []
                for card in cards:
                    handle = await card.element_handle()
                    if not handle:
                        continue

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

                    # 광고성 빈 li 스킵
                    if not name and not link:
                        continue

                    results.append({
                        "수집일자": now_kst.strftime("%Y-%m-%d"),
                        "제품명": name,
                        "가격": clean_price(price_text),
                        "링크": link,
                        "순위": clean_rank(rank_text),
                    })

                df = pd.DataFrame(results)
                df["오특"] = df["순위"].isna()

                if len(df) < 5:
                    raise RuntimeError(f"수집 결과가 비정상적으로 적습니다. ({len(df)}건)")

                await context.close()
                await browser.close()
                return df

            except (PWTimeout, RuntimeError) as e:
                last_err = e
                print(f"⚠️ 시도 {attempt} 실패: {e}")
                await dump_debug(page, prefix=f"fail_attempt_{attempt}")
                # 새로고침 후 재시도
                try:
                    await page.reload(timeout=25000)
                    await page.wait_for_load_state("domcontentloaded", timeout=20000)
                except Exception:
                    pass

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

    with pd.option_context("display.max_colwidth", 120):
        print(df_today.head(10))
