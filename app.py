#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# app.py — Google Drive(서비스 계정) 업로드 전용 + Playwright 우회 + 급상승/급하락 분석 + 14:01 KST 고정

import os
import re
import json
import base64
import logging
from datetime import datetime
from io import BytesIO, StringIO
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

# ───────── Playwright (HTTP 실패 시만 사용)
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False

# ───────── Google Drive (서비스 계정)
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

# ───────── ENV
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
GDRIVE_SA_JSON_B64 = os.environ.get("GDRIVE_SA_JSON_B64", "").strip()  # 서비스계정 JSON(Base64)
GDRIVE_FOLDER_ID   = os.environ.get("GDRIVE_FOLDER_ID", "").strip()    # 업로드 폴더 ID

OUT_DIR = "rankings"
ART_DIR = "artifacts"
MAX_ITEMS = 100
KST = ZoneInfo("Asia/Seoul")
FIXED_HHMM = "14:01"  # ‘오후 2:01’ 고정 표기

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
APP_BUILD = "oy-app gdrive-only 2025-08-13"

# ───────── 공통 세션
def make_session():
    s = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[429,500,502,503,504])
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.oliveyoung.co.kr/",
    })
    return s

# ───────── 파싱 유틸
def clean_title(raw: str) -> str:
    if not raw: return ""
    s = raw.strip()
    s = re.sub(r'^\s*(?:\[[^\]]*\]\s*)+', '', s)                       # [ ... ] 제거
    s = re.sub(r'^\s*([^|\n]{1,40}\|\s*)+', '', s)                     # 태그|태그|... 제거
    s = re.sub(r'^\s*(리뷰 이벤트|PICK|오특|이벤트|특가|[^\s]*PICK)\s*[:\-–—]?\s*', '', s, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', s).strip()

def extract_brand_from_name(name: str) -> str:
    if not name: return ""
    parts = re.split(r'[\s·\-–—\/\\\|,]+', name)
    if not parts: return ""
    cand = parts[0]
    if re.match(r'^\d|\+|세트|기획', cand):
        return parts[1] if len(parts) > 1 else cand
    return cand

def parse_html_products(html: str):
    soup = BeautifulSoup(html, "html.parser")
    selectors = [
        "ul.cate_prd_list li", "ul.prd_list li",
        ".cate_prd_list li", ".prd_info", ".prd_box",
        ".ranking_list li", ".rank_item",
    ]
    results = []
    for sel in selectors:
        els = soup.select(sel)
        if not els: continue
        for el in els:
            if len(results) >= MAX_ITEMS: break
            name_node = None
            for ns in [".tx_name", ".prd_name .tx_name", ".prd_name", ".prd_tit", "a"]:
                node = el.select_one(ns)
                if node and node.get_text(strip=True):
                    name_node = node; break
            if not name_node: continue
            raw_name = name_node.get_text(" ", strip=True)
            cleaned = clean_title(raw_name)
            price_node = (el.select_one(".tx_cur .tx_num") or el.select_one(".tx_cur")
                          or el.select_one(".prd_price .tx_num") or el.select_one(".prd_price"))
            price = price_node.get_text(strip=True) if price_node else ""
            brand_node = el.select_one(".tx_brand") or el.select_one(".brand")
            brand = brand_node.get_text(strip=True) if brand_node else extract_brand_from_name(cleaned)
            link_node = el.select_one("a")
            href = link_node.get("href") if link_node else None
            if href and href.startswith("/"):
                href = "https://www.oliveyoung.co.kr" + href
            results.append({"raw_name": raw_name, "name": cleaned, "brand": brand, "price": price, "url": href, "rank": None})
        if results:
            logging.info("parse_html_products: %s -> %d개", sel, len(results))
            break
    return results

# ───────── 수집 (HTTP → 실패 시 Playwright)
def try_http_candidates():
    session = make_session()
    candidates = [
        ("getBestList", "https://www.oliveyoung.co.kr/store/main/getBestList.do",
         {"rowsPerPage": str(MAX_ITEMS), "pageIdx": "0"}),
        ("getBestList_disp_total", "https://www.oliveyoung.co.kr/store/main/getBestList.do",
         {"dispCatNo":"90000010001","rowsPerPage": str(MAX_ITEMS),"pageIdx":"0"}),
        ("getTopSellerList", "https://www.oliveyoung.co.kr/store/main/getTopSellerList.do",
         {"rowsPerPage": str(MAX_ITEMS), "pageIdx": "0"}),
        ("getBestListJson", "https://www.oliveyoung.co.kr/store/main/getBestListJson.do",
         {"rowsPerPage": str(MAX_ITEMS), "pageIdx": "0"}),
    ]
    for name, url, params in candidates:
        try:
            logging.info("HTTP try: %s %s %s", name, url, params)
            r = session.get(url, params=params, timeout=15)
            logging.info(" -> status=%s, ct=%s, len=%d", r.status_code, r.headers.get("Content-Type"), len(r.text or ""))
            if r.status_code != 200: continue
            text = r.text or ""
            ct = r.headers.get("Content-Type","")
            # JSON 추정일 때
            if "application/json" in ct or text.strip().startswith("{") or text.strip().startswith("["):
                try: data = r.json()
                except Exception: data = None
                if isinstance(data, dict):
                    for k in ["BestProductList","list","rows","items","bestList","result"]:
                        if k in data and isinstance(data[k], list) and data[k]:
                            out = []
                            for it in data[k]:
                                name_val = it.get("prdNm") or it.get("prodName") or it.get("goodsNm") or it.get("name")
                                price_val = it.get("price") or it.get("salePrice") or it.get("onlinePrice")
                                brand_val = it.get("brandNm") or it.get("brand")
                                url_val = it.get("goodsUrl") or it.get("prdUrl") or it.get("url")
                                if isinstance(url_val, str) and url_val.startswith("/"):
                                    url_val = "https://www.oliveyoung.co.kr" + url_val
                                cleaned = clean_title(name_val or "")
                                out.append({
                                    "raw_name": name_val, "name": cleaned,
                                    "brand": brand_val or extract_brand_from_name(cleaned),
                                    "price": str(price_val or ""), "url": url_val, "rank": None
                                })
                            if out:
                                logging.info("HTTP JSON parsed via key=%s -> %d개", k, len(out))
                                return out, text[:800]
            # HTML 파싱
            items = parse_html_products(text)
            if items: return items, text[:800]
        except Exception as e:
            logging.exception("HTTP candidate error: %s %s", url, e)
    return None, None

def _dump_artifacts(page, tag):
    try:
        os.makedirs(ART_DIR, exist_ok=True)
        page.screenshot(path=f"{ART_DIR}/{tag}.png", full_page=True)
        with open(f"{ART_DIR}/{tag}.html", "w", encoding="utf-8") as f:
            f.write(page.content())
    except Exception:
        pass

def try_playwright_render(urls=None, max_retries=2):
    """domcontentloaded + 셀렉터 대기 + 다중 URL 재시도 + 간단 스텔스"""
    if not PLAYWRIGHT_AVAILABLE:
        logging.warning("Playwright not available."); return None, None

    urls = urls or [
        "https://www.oliveyoung.co.kr/store/main/getBest.do",
        "https://www.oliveyoung.co.kr/store/main/getBestList.do",
    ]
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage"])
            context = browser.new_context(
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
                locale="ko-KR", timezone_id="Asia/Seoul",
                extra_http_headers={"Accept-Language":"ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"},
                viewport={"width":1440, "height":900},
            )
            context.add_init_script("""() => {
              Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
              Object.defineProperty(navigator, 'languages', { get: () => ['ko-KR','ko','en-US','en'] });
              Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3] });
            }""")
            page = context.new_page()
            page.route("**/*", lambda route: route.abort() if route.request.resource_type in {"image","font","media"} else route.continue_())

            candidate_selectors = [
                "ul.cate_prd_list li", "ul.prd_list li",
                ".cate_prd_list li", ".ranking_list li", ".rank_item"
            ]

            last_err = None
            for attempt in range(1, max_retries+1):
                for u in urls:
                    try:
                        logging.info("Playwright goto (try %d): %s", attempt, u)
                        page.goto(u, wait_until="domcontentloaded", timeout=45000)
                        # 쿠키/팝업 닫기 시도
                        for sel in ["button:has-text('동의')","button:has-text('확인')","button:has-text('닫기')",".btnClose",".btn-close","#chkToday"]:
                            try:
                                if page.locator(sel).count() > 0:
                                    page.locator(sel).first.click(timeout=800)
                            except Exception:
                                pass
                        page.wait_for_timeout(600)
                        # 셀렉터 대기
                        roots = ", ".join([s.replace(" li","") for s in candidate_selectors])
                        try: page.locator(roots).first.wait_for(state="attached", timeout=15000)
                        except PWTimeout: pass
                        try: page.locator(roots).first.wait_for(state="visible", timeout=15000)
                        except PWTimeout: pass
                        # li 최소 개수
                        page.wait_for_function(
                            """(sels)=>{for(const s of sels){if(document.querySelectorAll(s).length>=5)return true;}return false;}""",
                            arg=candidate_selectors, timeout=20000
                        )

                        html = page.content()
                        items = parse_html_products(html)
                        if items:
                            context.close(); browser.close()
                            return items, html[:800]
                        else:
                            _dump_artifacts(page, f"no_items_try{attempt}")
                            last_err = RuntimeError("리스트 파싱 실패")
                    except Exception as e:
                        last_err = e
                        _dump_artifacts(page, f"fail_try{attempt}")
                        try: page.wait_for_timeout(800)
                        except Exception: pass
                        continue

            context.close(); browser.close()
            if last_err: logging.error("Playwright render error: %s", last_err)
            return None, None
    except Exception as e:
        logging.exception("Playwright outer error: %s", e)
        return None, None

def fill_ranks(items):
    out = []
    for i, it in enumerate(items, start=1):
        it["rank"] = i
        out.append(it)
        if i >= MAX_ITEMS: break
    return out

# ───────── Google Drive helpers
def build_drive_service():
    if not GDRIVE_SA_JSON_B64:
        logging.warning("No GDRIVE_SA_JSON_B64 provided."); return None
    try:
        sa_info = json.loads(base64.b64decode(GDRIVE_SA_JSON_B64).decode("utf-8"))
        creds = service_account.Credentials.from_service_account_info(
            sa_info, scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive","v3",credentials=creds, cache_discovery=False)
    except Exception as e:
        logging.exception("Failed to build Drive service: %s", e); return None

def upload_csv_to_drive(service, csv_bytes, filename, folder_id=None):
    if not service:
        logging.warning("Drive service not available."); return None
    try:
        media = MediaIoBaseUpload(BytesIO(csv_bytes), mimetype="text/csv", resumable=False)
        meta = {"name": filename}
        if folder_id: meta["parents"] = [folder_id]
        f = service.files().create(body=meta, media_body=media, fields="id,webViewLink").execute()
        logging.info("Uploaded to Drive: id=%s link=%s", f.get("id"), f.get("webViewLink"))
        return f
    except Exception as e:
        logging.exception("Drive upload failed: %s", e); return None

def find_latest_csv_in_drive(service, folder_id):
    try:
        q = f"mimeType='text/csv' and name contains '올리브영_랭킹' and '{folder_id}' in parents" if folder_id \
            else "mimeType='text/csv' and name contains '올리브영_랭킹'"
        res = service.files().list(q=q, orderBy="createdTime desc", pageSize=10,
                                   fields="files(id,name,createdTime)").execute()
        files = res.get("files", [])
        return files[0] if files else None
    except Exception as e:
        logging.exception("find_latest_csv_in_drive error: %s", e); return None

def download_file_from_drive(service, file_id):
    try:
        req = service.files().get_media(fileId=file_id)
        fh = BytesIO()
        downloader = MediaIoBaseDownload(fh, req)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        fh.seek(0)
        return fh.read().decode("utf-8")
    except Exception as e:
        logging.exception("download_file_from_drive error: %s", e); return None

# ───────── 분석 (전일 대비)
def analyze_trends(today_items, prev_items):
    prev_map = {}
    for p in (prev_items or []):
        key = p.get("name") or p.get("raw_name")
        if key: prev_map[key] = p.get("rank")
    trends = []
    for it in today_items:
        key = it.get("name") or it.get("raw_name")
        prev_rank = prev_map.get(key)
        if prev_rank:
            change = prev_rank - it["rank"]  # 양수=상승, 음수=하락
            trends.append({"name": key, "brand": it.get("brand"), "rank": it["rank"],
                           "prev_rank": prev_rank, "change": change, "sample_product": it.get("name")})
        else:
            trends.append({"name": key, "brand": it.get("brand"), "rank": it["rank"],
                           "prev_rank": None, "change": None, "sample_product": it.get("name")})
    movers = [t for t in trends if t.get("prev_rank")]
    movers_up = sorted(movers, key=lambda x: x["change"], reverse=True)
    movers_down = sorted(movers, key=lambda x: x["change"])
    firsts = [t for t in trends if t.get("prev_rank") is None]
    return movers_up, firsts, movers_down

# ───────── 슬랙 유틸(브랜드 중복 제거 포함)
def _norm(s: str) -> str:
    if not s: return ""
    return re.sub(r'[\s\[\]\(\)\-–—·|:,/\\]+', '', s.lower())

def format_title_for_slack(brand: str, name: str) -> str:
    b, n = (brand or "").strip(), (name or "").strip()
    if not b: return n
    return n if _norm(n).startswith(_norm(b)) else f"{b} {n}"

def send_slack_text(text):
    if not SLACK_WEBHOOK:
        logging.warning("No SLACK_WEBHOOK_URL configured."); return False
    try:
        r = requests.post(SLACK_WEBHOOK, json={"text": text}, timeout=10)
        if r.status_code // 100 == 2:
            logging.info("Slack sent"); return True
        logging.warning("Slack returned %s: %s", r.status_code, r.text[:200]); return False
    except Exception as e:
        logging.exception("Slack send error: %s", e); return False

# ───────── 메인
def main():
    logging.info("Build: %s", APP_BUILD)
    logging.info("Start scraping")

    items, sample = try_http_candidates()
    if not items:
        logging.info("HTTP failed → Playwright fallback")
        items, sample = try_playwright_render()
    if not items:
        logging.error("Scraping failed. sample head: %s", (sample or "")[:500])
        send_slack_text(f"❌ OliveYoung scraping failed.\n{(sample or '')[:800]}")
        return 1

    items = fill_ranks(items)

    now_kst = datetime.now(KST)
    date_str = now_kst.date().isoformat()
    time_str = FIXED_HHMM
    fname = f"올리브영_랭킹_{date_str}.csv"

    # CSV 직작성
    def q(s):
        if s is None: return ""
        s = str(s).replace('"','""')
        return f'"{s}"' if any(c in s for c in [',','"','\n']) else s
    csv_lines = ["rank,brand,name,price,url,raw_name"]
    for it in items:
        csv_lines.append(",".join([q(it.get("rank")), q(it.get("brand")), q(it.get("name")),
                                   q(it.get("price")), q(it.get("url")), q(it.get("raw_name"))]))
    csv_bytes = ("\n".join(csv_lines)).encode("utf-8")

    # 로컬 백업 저장
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, fname), "wb") as f:
        f.write(csv_bytes)
    logging.info("Saved CSV locally: %s/%s", OUT_DIR, fname)

    # ── Google Drive 업로드
    drive = build_drive_service()
    if drive and GDRIVE_FOLDER_ID:
        upload_csv_to_drive(drive, csv_bytes, fname, folder_id=GDRIVE_FOLDER_ID)
    else:
        logging.warning("Drive env 미설정 -> 업로드 스킵")

    # ── 상단 슬랙 메시지
    lines = [f"📊 OliveYoung Total Ranking ({date_str} {time_str} KST)"]
    for it in items[:10]:
        title = format_title_for_slack(it.get("brand") or "", it.get("name") or "")
        if it.get("url"):
            lines.append(f"{it['rank']}. <{it['url']}|{title}> — {it.get('price') or ''}")
        else:
            lines.append(f"{it['rank']}. {title} — {it.get('price') or ''}")

    # ── 전일 파일(Drive)로 추세 분석
    prev_items = []
    if drive and GDRIVE_FOLDER_ID:
        latest = find_latest_csv_in_drive(drive, GDRIVE_FOLDER_ID)
        if latest and latest.get("name") != fname:
            prev_text = download_file_from_drive(drive, latest["id"])
            if prev_text:
                try:
                    import csv
                    rdr = csv.DictReader(StringIO(prev_text))
                    for r in rdr:
                        try:
                            prev_items.append({"rank": int(r.get("rank") or 0), "name": r.get("name"), "raw_name": r.get("raw_name")})
                        except: pass
                except Exception as e:
                    logging.exception("Prev CSV parse failed: %s", e)

    movers_up, firsts, movers_down = analyze_trends(items, prev_items)

    lines.append(""); lines.append("🔥 급상승 브랜드")
    if movers_up:
        for m in movers_up[:3]:
            change = m["prev_rank"] - m["rank"]
            lines.append(f"- {m.get('brand')}: {m.get('prev_rank')}위 → {m.get('rank')}위 (▲{change})")
            sample = m.get("sample_product") or m.get("name")
            if sample: lines.append(f"  ▶ {sample}")
    else:
        lines.append("- (전일 데이터 없음)")

    lines.append(""); lines.append("⭐ 첫 등장/주목 신상품")
    first_true = [f for f in firsts if f.get("prev_rank") is None]
    if first_true:
        for f in first_true[:3]:
            lines.append(f"- {f.get('brand')}: 첫 등장 {f.get('rank')}위")
            lines.append(f"  ▶ {f.get('sample_product')}")
    else:
        lines.append("- (전일 대비 신규 진입 없음)")

    lines.append(""); lines.append("📉 급하락 브랜드")
    if movers_down:
        for m in movers_down[:3]:
            drop = m["rank"] - m["prev_rank"]
            lines.append(f"- {m.get('brand')}: {m.get('prev_rank')}위 → {m.get('rank')}위 (▼{drop})")
            sample = m.get("sample_product") or m.get("name")
            if sample: lines.append(f"  ▶ {sample}")
    else:
        lines.append("- (전일 데이터 없음)")

    send_slack_text("\n".join(lines))
    logging.info("Done.")
    return 0

if __name__ == "__main__":
    exit(main())
