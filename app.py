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
from zoneinfo import ZoneInfo  # KST 고정 표기용

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
GDRIVE_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID", "").strip()      # target folder in Drive
OUT_DIR = "rankings"
MAX_ITEMS = 100

# 고정 표기 시간(로컬 시간과 무관하게 Slack 헤더에 이 시간을 표기)
KST = ZoneInfo("Asia/Seoul")
FIXED_HHMM = "14:01"  # '오후 2시 1분' 고정 표기

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# ---------------- helpers
def make_session():
    s = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
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
    # remove leading tokens up to real product name
    s = re.sub(r'^\s*([^|\n]{1,40}\|\s*)+', '', s)
    # remove common promotional phrases at start (오특도 제거하지만 '오특 판단' 로직은 아예 사용 안함)
    s = re.sub(r'^\s*(리뷰 이벤트|PICK|오특|이벤트|특가|[^\s]*PICK)\s*[:\-–—]?\s*', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def extract_brand_from_name(name: str) -> str:
    if not name:
        return ""
    parts = re.split(r'[\s·\-–—\/\\\|,]+', name)
    if parts:
        candidate = parts[0]
        if re.match(r'^\d|\+|세트|기획', candidate):
            if len(parts) > 1:
                return parts[1]
            return candidate
        return candidate
    return name

def parse_html_products(html: str):
    soup = BeautifulSoup(html, "html.parser")
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
        ("getBestList", "https://www.oliveyoung.co.kr/store/main/getBestList.do",
         {"rowsPerPage": str(MAX_ITEMS), "pageIdx": "0"}),
        ("getBestList_disp_total", "https://www.oliveyoung.co.kr/store/main/getBestList.do",
         {"dispCatNo": "90000010001", "rowsPerPage": str(MAX_ITEMS), "pageIdx": "0"}),
        ("getTopSellerList", "https://www.oliveyoung.co.kr/store/main/getTopSellerList.do",
         {"rowsPerPage": str(MAX_ITEMS), "pageIdx": "0"}),
        ("getBestListJson", "https://www.oliveyoung.co.kr/store/main/getBestListJson.do",
         {"rowsPerPage": str(MAX_ITEMS), "pageIdx": "0"}),
    ]
    for name, url, params in candidates:
        try:
            logging.info("HTTP try %s %s %s", name, url, params)
            r = session.get(url, params=params, timeout=15)
            logging.info(" -> status=%s content-type=%s len=%d", r.status_code, r.headers.get("Content-Type"), len(r.text or ""))
            if r.status_code != 200:
                continue
            ct = r.headers.get("Content-Type", "")
            text = r.text or ""
            # try JSON
            if "application/json" in ct or text.strip().startswith("{") or text.strip().startswith("["):
                try:
                    data = r.json()
                except Exception:
                    data = None
                if isinstance(data, dict):
                    for k in ["BestProductList", "list", "rows", "items", "bestList", "result"]:
                        if k in data and isinstance(data[k], list) and data[k]:
                            out = []
                            for idx, it in enumerate(data[k], start=1):
                                name_val = it.get("prdNm") or it.get("prodName") or it.get("goodsNm") or it.get("name")
                                price_val = it.get("price") or it.get("salePrice") or it.get("onlinePrice")
                                brand_val = it.get("brandNm") or it.get("brand")
                                url_val = it.get("goodsUrl") or it.get("prdUrl") or it.get("url")
                                if isinstance(url_val, str) and url_val.startswith("/"):
                                    url_val = "https://www.oliveyoung.co.kr" + url_val
                                cleaned = clean_title(name_val or "")
                                out.append({
                                    "raw_name": name_val,
                                    "name": cleaned,
                                    "brand": brand_val or extract_brand_from_name(cleaned),
                                    "price": str(price_val or ""),
                                    "url": url_val,
                                    "rank": None
                                })
                            if out:
                                logging.info("HTTP JSON parse via key %s found %d items", k, len(out))
                                return out, text[:800]
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
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
                locale="ko-KR"
            )
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
    # 순위는 1..MAX_ITEMS로 연속 부여
    out = []
    rank = 1
    for it in items:
        it['rank'] = rank
        out.append(it)
        rank += 1
        if rank > MAX_ITEMS:
            break
    return out

# ---------------- Google Drive helpers
def build_drive_service():
    if not GDRIVE_SA_JSON_B64:
        logging.warning("No GDRIVE_SA_JSON_B64 provided.")
        return None
    try:
        sa_json = base64.b64decode(GDRIVE_SA_JSON_B64)
        sa_info = json.loads(sa_json.decode("utf-8"))
        creds = service_account.Credentials.from_service_account_info(
            sa_info, scopes=["https://www.googleapis.com/auth/drive"]
        )
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
    try:
        q = (
            f"mimeType='text/csv' and name contains '올리브영_랭킹' and '{folder_id}' in parents"
            if folder_id else
            "mimeType='text/csv' and name contains '올리브영_랭킹'"
        )
        res = service.files().list(q=q, orderBy="createdTime desc", pageSize=10, fields="files(id,name,createdTime)").execute()
        files = res.get("files", [])
        if files:
            return files[0]
        return None
    except Exception as e:
        logging.exception("find_latest_csv_in_drive error: %s", e)
        return None

def download_file_from_drive(service, file_id):
    try:
        request = service.files().get_media(fileId=file_id)
        from googleapiclient.http import MediaIoBaseDownload
        fh = BytesIO()
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
    """전일 대비 순위 변화 계산.
    change = prev_rank - today_rank  (양수=상승, 음수=하락)
    반환: (상승 top 리스트, 첫등장 리스트, 하락 top 리스트)
    """
    prev_map = {}
    for p in (prev_items or []):
        key = p.get("name") or p.get("raw_name")
        prev_map[key] = p.get("rank")

    trends = []
    for it in today_items:
        key = it.get("name") or it.get("raw_name")
        prev_rank = prev_map.get(key)
        if prev_rank:
            change = prev_rank - it['rank']
            trends.append({
                "name": key,
                "brand": it.get("brand"),
                "rank": it['rank'],
                "prev_rank": prev_rank,
                "change": change,
                "sample_product": it.get("name")
            })
        else:
            trends.append({
                "name": key,
                "brand": it.get("brand"),
                "rank": it['rank'],
                "prev_rank": None,
                "change": None,
                "sample_product": it.get("name")
            })

    movers = [t for t in trends if t.get("prev_rank")]
    movers_up = sorted(movers, key=lambda x: x["change"], reverse=True)   # 상승 상위
    movers_down = sorted(movers, key=lambda x: x["change"])               # 하락 상위(가장 음수)
    firsts = [t for t in trends if t.get("prev_rank") is None]
    return movers_up, firsts, movers_down

# ---------------- Slack
def send_slack_text(text):
    if not SLACK_WEBHOOK:
        logging.warning("No SLACK_WEBHOOK configured.")
        return False
    try:
        res = requests.post(SLACK_WEBHOOK,_
