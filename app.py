#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# app.py
import os
import re
import json
import time
import base64
import logging
from datetime import datetime, timedelta
from io import BytesIO, StringIO

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

# (optional) Playwright fallback if HTTP endpoints fail
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False

# Google Drive libs
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ---------------- config (env)
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
GDRIVE_SA_JSON_B64 = os.environ.get("GDRIVE_SA_JSON_B64", "").strip()  # base64-encoded service account json
GDRIVE_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID", "").strip()  # target folder in Drive
OUT_DIR = "rankings"
MAX_ITEMS = 100

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# ---------------- helpers
def make_session():
    s = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[429,500,502,503,504])
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.oliveyoung.co.kr/",
    })
    return s

# remove leading bracketed tags and leading promo segments like "푸디젠 PICK | 리뷰 이벤트"
def clean_title(raw: str) -> str:
    if not raw:
        return ""
    s = raw.strip()
    # remove any [ ... ] at start (one or more)
    s = re.sub(r'^\s*(?:\[[^\]]*\]\s*)+', '', s)
    # remove leading segments that are short tags separated by '|' or '-' or ':' up to first real product name
    # e.g. "푸디젠 PICK | 리뷰 이벤트] 구달 ...", after bracket removal might be "푸디젠 PICK | 리뷰 이벤트 구달..."
    # we'll remove leading tokens containing 'PICK' or '리뷰' or words that are uppercase or short (<=4 chars) followed by '|'
    s = re.sub(r'^\s*([^|\n]{1,40}\|\s*)+', '', s)
    # remove common promotional phrases at start
    s = re.sub(r'^\s*(리뷰 이벤트|PICK|오특|이벤트|특가|[^\s]*PICK)\s*[:\-–—]?\s*', '', s, flags=re.IGNORECASE)
    # collapse multiple spaces
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def extract_brand_from_name(name: str) -> str:
    # try to get first token which is likely brand; many product names start with brand
    if not name:
        return ""
    # split by whitespace and punctuation
    parts = re.split(r'[\s·\-–—\/\\\|,]+', name)
    if parts:
        candidate = parts[0]
        # if candidate is too generic (like '1+1' or '세트'), try second
        if re.match(r'^\d|\+|세트|기획', candidate):
            if len(parts) > 1:
                return parts[1]
            return candidate
        return candidate
    return name

def parse_html_products(html: str):
    soup = BeautifulSoup(html, "html.parser")
    # Candidate selectors seen on oliveyoung fragments
    candidate_selectors = [
        "ul.cate_prd_list li",
        "ul.prd_list li",
        ".cate_prd_list li",
        ".prd_info",
        ".prd_box",
        ".ranking_list li",
        ".rank_item",
    ]
    results = []
    for sel in candidate_selectors:
        els = soup.select(sel)
        if not els:
            continue
        for idx, el in enumerate(els, start=1):
            if len(results) >= MAX_ITEMS:
                break
            # name heuristics
            name_node = None
            for ns in [".tx_name", ".prd_name .tx_name", ".prd_name", ".prd_tit", "a"]:
                node = el.select_one(ns)
                if node and node.get_text(strip=True):
                    name_node = node
                    break
            if not name_node:
                continue
            raw_name = name_node.get_text(" ", strip=True)
            cleaned = clean_title(raw_name)
            # price
            price_node = el.select_one(".tx_cur .tx_num") or el.select_one(".tx_cur") or el.select_one(".prd_price .tx_num") or el.select_one(".prd_price")
            price = price_node.get_text(strip=True) if price_node else ""
            # brand
            brand_node = el.select_one(".tx_brand") or el.select_one(".brand")
            brand = brand_node.get_text(strip=True) if brand_node else extract_brand_from_name(cleaned)
            # link
            link_node = el.select_one("a")
            href = link_node.get("href") if link_node else None
            if href and href.startswith("/"):
                href = "https://www.oliveyoung.co.kr" + href
            results.append({
                "raw_name": raw_name,
                "name": cleaned,
                "brand": brand,
                "price": price,
                "url": href,
                "rank": None  # fill later
            })
        if results:
            logging.info("parse_html_products: found %d items using selector %s", len(results), sel)
            break
    return results

def try_http_candidates():
    session = make_session()
    candidates = [
        # primary guess: HTML fragment endpoint
        ("getBestList", "https://www.oliveyoung.co.kr/store/main/getBestList.do", {"rowsPerPage": str(MAX_ITEMS), "pageIdx":"0"}),
        # alt with dispCatNo possibly for total
        ("getBestList_disp_total", "https://www.oliveyoung.co.kr/store/main/getBestList.do", {"dispCatNo":"90000010001", "rowsPerPage": str(MAX_ITEMS), "pageIdx":"0"}),
        ("getTopSellerList", "https://www.oliveyoung.co.kr/store/main/getTopSellerList.do", {"rowsPerPage": str(MAX_ITEMS), "pageIdx":"0"}),
        # JSON-like endpoints that sometimes exist (heuristic)
        ("getBestListJson", "https://www.oliveyoung.co.kr/store/main/getBestListJson.do", {"rowsPerPage": str(MAX_ITEMS), "pageIdx":"0"}),
    ]
    for name, url, params in candidates:
        try:
            logging.info("HTTP try %s %s %s", name, url, params)
            r = session.get(url, params=params, timeout=15)
            logging.info(" -> status=%s content-type=%s len=%d", r.status_code, r.headers.get("Content-Type"), len(r.text or ""))
            if r.status_code != 200:
                continue
            ct = r.headers.get("Content-Type","")
            text = r.text or ""
            # try JSON
            if "application/json" in ct or text.strip().startswith("{") or text.strip().startswith("["):
                try:
                    data = r.json()
                except Exception:
                    data = None
                if isinstance(data, dict):
                    # look for list keys
                    for k in ["BestProductList", "list", "rows", "items", "bestList", "result"]:
                        if k in data and isinstance(data[k], list) and data[k]:
                            out = []
                            for idx, it in enumerate(data[k], start=1):
                                name_val = it.get("prdNm") or it.get("prodName") or it.get("goodsNm") or it.get("name")
                                price_val = it.get("price") or it.get("salePrice") or it.get("onlinePrice")
                                brand_val = it.get("brandNm") or it.get("brand")
                                url_val = it.get("goodsUrl") or it.get("prdUrl") or it.get("url")
                                if url_val and isinstance(url_val, str) and url_val.startswith("/"):
                                    url_val = "https://www.oliveyoung.co.kr" + url_val
                                cleaned = clean_title(name_val or "")
                                out.append({"raw_name": name_val, "name": cleaned, "brand": brand_val or extract_brand_from_name(cleaned), "price": str(price_val or ""), "url": url_val, "rank": None})
                            if out:
                                logging.info("HTTP JSON parse via key %s found %d items", k, len(out))
                                return out, text[:800]
                # else continue to html parse
            # else parse HTML fragment
            items = parse_html_products(text)
            if items:
                return items, text[:800]
        except Exception as e:
            logging.exception("HTTP candidate error: %s %s", url, e)
    return None, None

def try_playwright_render(url="https://www.oliveyoung.co.kr/store/main/getBestList.do"):
    if not PLAYWRIGHT_AVAILABLE:
        logging.warning("Playwright not available.")
        return None, None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage"])
            context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36", locale="ko-KR")
            page = context.new_page()
            logging.info("Playwright navigating %s", url)
            page.goto(url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(2500)
            html = page.content()
            items = parse_html_products(html)
            browser.close()
            return items, html[:800]
    except Exception as e:
        logging.exception("Playwright render error: %s", e)
        return None, None

def fill_ranks_and_fix(items):
    # If items have some 'rank' filled or not. We'll assign sequential ranks ignoring any missing markers from source.
    out = []
    rank = 1
    for it in items:
        it['rank'] = rank
        out.append(it)
        rank += 1
        if rank > MAX_ITEMS:
            break
    # if fewer than MAX_ITEMS, that's fine.
    return out

# ---------------- Google Drive helpers
def build_drive_service():
    if not GDRIVE_SA_JSON_B64:
        logging.warning("No GDRIVE_SA_JSON_B64 provided.")
        return None
    try:
        sa_json = base64.b64decode(GDRIVE_SA_JSON_B64)
        sa_info = json.loads(sa_json.decode("utf-8"))
        creds = service_account.Credentials.from_service_account_info(sa_info, scopes=["https://www.googleapis.com/auth/drive"])
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return service
    except Exception as e:
        logging.exception("Failed to build Drive service: %s", e)
        return None

def upload_csv_to_drive(service, csv_bytes, filename, folder_id=None):
    if not service:
        logging.warning("Drive service not available; skipping upload.")
        return None
    try:
        media = MediaIoBaseUpload(BytesIO(csv_bytes), mimetype="text/csv", resumable=False)
        file_metadata = {"name": filename}
        if folder_id:
            file_metadata["parents"] = [folder_id]
        file = service.files().create(body=file_metadata, media_body=media, fields="id,webViewLink").execute()
        logging.info("Uploaded to Drive id=%s link=%s", file.get("id"), file.get("webViewLink"))
        return file
    except Exception as e:
        logging.exception("Drive upload failed: %s", e)
        return None

def find_latest_csv_in_drive(service, folder_id):
    # find latest file with name pattern '올리브영_랭킹_YYYY-MM-DD' in folder
    try:
        q = f"mimeType='text/csv' and name contains '올리브영_랭킹' and '{folder_id}' in parents" if folder_id else "mimeType='text/csv' and name contains '올리브영_랭킹'"
        res = service.files().list(q=q, orderBy="createdTime desc", pageSize=10, fields="files(id,name,createdTime)").execute()
        files = res.get("files", [])
        if files:
            return files[0]  # latest
        return None
    except Exception as e:
        logging.exception("find_latest_csv_in_drive error: %s", e)
        return None

def download_file_from_drive(service, file_id):
    try:
        request = service.files().get_media(fileId=file_id)
        fh = BytesIO()
        downloader = MediaIoBaseUpload  # placeholder not used
        # simpler: use execute_media
        from googleapiclient.http import MediaIoBaseDownload
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        fh.seek(0)
        data = fh.read().decode("utf-8")
        return data
    except Exception as e:
        logging.exception("download_file_from_drive error: %s", e)
        return None

# ---------------- analysis
def analyze_trends(today_items, prev_items):
    # prev_items: list of dicts with 'name' and 'rank'
    prev_map = {}
    for p in (prev_items or []):
        key = p.get("name") or p.get("raw_name")
        prev_map[key] = p.get("rank")
    trends = []
    for it in today_items:
        key = it.get("name") or it.get("raw_name")
        prev_rank = prev_map.get(key)
        if prev_rank:
            change = prev_rank - it['rank']  # positive means improved (moved up)
            trends.append({"name": key, "brand": it.get("brand"), "rank": it['rank'], "prev_rank": prev_rank, "change": change, "sample_product": it.get("name")})
        else:
            # first appearance
            trends.append({"name": key, "brand": it.get("brand"), "rank": it['rank'], "prev_rank": None, "change": None, "sample_product": it.get("name")})
    # movers
    movers = [t for t in trends if t.get("prev_rank")]
    movers_sorted = sorted(movers, key=lambda x: x["change"], reverse=True)  # biggest improvement first
    firsts = [t for t in trends if t.get("prev_rank") is None]
    return movers_sorted, firsts

# ---------------- Slack
def send_slack_text(text):
    if not SLACK_WEBHOOK:
        logging.warning("No SLACK_WEBHOOK configured.")
        return False
    try:
        res = requests.post(SLACK_WEBHOOK, json={"text": text}, timeout=10)
        if res.status_code // 100 == 2:
            logging.info("Slack sent")
            return True
        else:
            logging.warning("Slack returned %s: %s", res.status_code, res.text[:200])
            return False
    except Exception as e:
        logging.exception("Slack send error: %s", e)
        return False

# ---------------- main flow
def main():
    logging.info("Start scraping")
    items, sample = try_http_candidates()
    if not items:
        logging.info("HTTP failed, trying Playwright fallback")
        items, sample = try_playwright_render()
    if not items:
        logging.error("Scraping failed entirely. Sample head: %s", (sample or "")[:500])
        send_slack_text(f"❌ OliveYoung scraping failed. Sample head:\n{(sample or '')[:800]}")
        return 1

    # ensure up to MAX_ITEMS
    if len(items) > MAX_ITEMS:
        items = items[:MAX_ITEMS]
    # fill ranks sequentially and fix "오특" gaps by sequential numbering
    items_filled = fill_ranks_and_fix(items)

    # CSV content
    today = datetime.now().date()
    fname = f"올리브영_랭킹_{today.isoformat()}.csv"
    os.makedirs(OUT_DIR, exist_ok=True)
    csv_lines = []
    header = ["rank","brand","name","price","url","raw_name"]
    csv_lines.append(",".join(header))
    for it in items_filled:
        # escape commas by quoting if needed
        def q(s): 
            if s is None: 
                return ""
            s = str(s).replace('"','""')
            if ',' in s or '\n' in s or '"' in s:
                return f'"{s}"'
            return s
        row = [q(it.get("rank")), q(it.get("brand")), q(it.get("name")), q(it.get("price")), q(it.get("url")), q(it.get("raw_name"))]
        csv_lines.append(",".join(row))
    csv_data = ("\n".join(csv_lines)).encode("utf-8")

    # upload to Drive
    drive_service = build_drive_service()
    if drive_service and GDRIVE_FOLDER_ID:
        upload_csv_to_drive(drive_service, csv_data, fname, folder_id=GDRIVE_FOLDER_ID)
    else:
        # fallback: save locally
        path = os.path.join(OUT_DIR, fname)
        with open(path, "wb") as f:
            f.write(csv_data)
        logging.info("Saved CSV locally: %s", path)

    # prepare Slack message
    top10 = items_filled[:10]
    lines = []
    lines.append(f"📊 올리브영 전체 랭킹(국내) ({today.isoformat()})")
    for it in top10:
        rank = it.get("rank")
        brand = it.get("brand") or ""
        name = it.get("name") or ""
        price = it.get("price") or ""
        url = it.get("url")
        if url:
            lines.append(f"{rank}. <{url}|{brand} {name}> — {price}")
        else:
            lines.append(f"{rank}. {brand} {name} — {price}")

    # try to fetch previous day's CSV from Drive for trend analysis
    prev_items = None
    if drive_service and GDRIVE_FOLDER_ID:
        latest = find_latest_csv_in_drive(drive_service, GDRIVE_FOLDER_ID)
        if latest and latest.get("name") != fname:
            # download
            logging.info("Found previous file %s - attempting download", latest.get("name"))
            prev_csv_text = download_file_from_drive(drive_service, latest.get("id"))
            if prev_csv_text:
                prev_items = []
                # parse CSV
                sio = StringIO(prev_csv_text)
                header = sio.readline()
                for ln in sio:
                    parts = []
                    # simple CSV parse by splitting respecting quotes is complex; we'll use csv module
                try:
                    import csv
                    sio.seek(0)
                    rdr = csv.DictReader(sio)
                    for r in rdr:
                        try:
                            prev_items.append({"rank": int(r.get("rank") or 0), "name": r.get("name"), "raw_name": r.get("raw_name")})
                        except:
                            continue
                except Exception as e:
                    logging.exception("CSV parse failed: %s", e)
    # analyze trends
    movers_sorted, firsts = analyze_trends(items_filled, prev_items or [])

    # build analysis section
    lines.append("")
    lines.append("🔥 급상승 브랜드")
    top_movers = movers_sorted[:3]
    if not top_movers:
        lines.append("- (데이터 부족 또는 이전 데이터 없음)")
    else:
        for m in top_movers:
            if m.get("prev_rank"):
                change = m["prev_rank"] - m["rank"]
                lines.append(f"- {m.get('brand')}: {m.get('prev_rank')}위 → {m.get('rank')}위 (+{change})")
                sample = m.get("sample_product") or m.get("name")
                if sample:
                    lines.append(f"  ▶ {sample}")
    lines.append("")
    lines.append("⭐ 첫 등장/주목 신상품")
    for f in firsts[:3]:
        # only true firsts (prev_rank is None)
        if f.get("prev_rank") is None:
            lines.append(f"- {f.get('brand')}: 첫 등장 {f.get('rank')}위")
            lines.append(f"  ▶ {f.get('sample_product')}")
    send_slack_text("\n".join(lines))
    logging.info("Done.")
    return 0

if __name__ == "__main__":
    exit(main())
