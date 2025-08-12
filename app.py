#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# app.py (Dropbox 업로드 추가)

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

# (optional) Playwright fallback if HTTP endpoints fail
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False

# ---------------- config (env)
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
DROPBOX_ACCESS_TOKEN = os.environ.get("DROPBOX_ACCESS_TOKEN", "").strip()  # Dropbox 업로드용
OUT_DIR = "rankings"
MAX_ITEMS = 100
KST = ZoneInfo("Asia/Seoul")
FIXED_HHMM = "14:01"

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

def clean_title(raw: str) -> str:
    if not raw:
        return ""
    s = raw.strip()
    s = re.sub(r'^\s*(?:\[[^\]]*\]\s*)+', '', s)
    s = re.sub(r'^\s*([^|\n]{1,40}\|\s*)+', '', s)
    s = re.sub(r'^\s*(리뷰 이벤트|PICK|오특|이벤트|특가|[^\s]*PICK)\s*[:\-–—]?\s*', '', s, flags=re.IGNORECASE)
    return re.sub(r'\s+', ' ', s).strip()

def extract_brand_from_name(name: str) -> str:
    if not name:
        return ""
    parts = re.split(r'[\s·\-–—\/\\\|,]+', name)
    if parts:
        candidate = parts[0]
        if re.match(r'^\d|\+|세트|기획', candidate):
            return parts[1] if len(parts) > 1 else candidate
        return candidate
    return name

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
        if not els:
            continue
        for el in els:
            if len(results) >= MAX_ITEMS:
                break
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
            price_node = el.select_one(".tx_cur .tx_num") or el.select_one(".tx_cur") \
                         or el.select_one(".prd_price .tx_num") or el.select_one(".prd_price")
            price = price_node.get_text(strip=True) if price_node else ""
            brand_node = el.select_one(".tx_brand") or el.select_one(".brand")
            brand = brand_node.get_text(strip=True) if brand_node else extract_brand_from_name(cleaned)
            link_node = el.select_one("a")
            href = link_node.get("href") if link_node else None
            if href and href.startswith("/"):
                href = "https://www.oliveyoung.co.kr" + href
            results.append({"raw_name": raw_name, "name": cleaned, "brand": brand, "price": price, "url": href, "rank": None})
        if results:
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
            r = session.get(url, params=params, timeout=15)
            if r.status_code != 200:
                continue
            text = r.text or ""
            if "application/json" in r.headers.get("Content-Type", "") or text.strip().startswith("{"):
                try:
                    data = r.json()
                except:
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
                                out.append({"raw_name": name_val, "name": cleaned, "brand": brand_val or extract_brand_from_name(cleaned), "price": str(price_val or ""), "url": url_val, "rank": None})
                            return out, text[:800]
            items = parse_html_products(text)
            if items:
                return items, text[:800]
        except:
            pass
    return None, None

def try_playwright_render(url="https://www.oliveyoung.co.kr/store/main/getBestList.do"):
    if not PLAYWRIGHT_AVAILABLE:
        return None, None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = browser.new_context(user_agent="Mozilla/5.0 ...", locale="ko-KR")
            page = context.new_page()
            page.goto(url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(2500)
            html = page.content()
            items = parse_html_products(html)
            browser.close()
            return items, html[:800]
    except:
        return None, None

def fill_ranks_and_fix(items):
    out = []
    for i, it in enumerate(items, start=1):
        it["rank"] = i
        out.append(it)
    return out

# Dropbox 업로드
def upload_to_dropbox(file_bytes, dropbox_path):
    if not DROPBOX_ACCESS_TOKEN:
        logging.warning("No DROPBOX_ACCESS_TOKEN set, skipping Dropbox upload")
        return False
    try:
        headers = {
            "Authorization": f"Bearer {DROPBOX_ACCESS_TOKEN}",
            "Content-Type": "application/octet-stream",
            "Dropbox-API-Arg": json.dumps({"path": dropbox_path, "mode": "overwrite", "mute": False})
        }
        r = requests.post("https://content.dropboxapi.com/2/files/upload", headers=headers, data=file_bytes)
        if r.status_code == 200:
            logging.info(f"Uploaded to Dropbox: {dropbox_path}")
            return True
        else:
            logging.error(f"Dropbox upload failed: {r.status_code} {r.text}")
            return False
    except Exception as e:
        logging.exception(f"Dropbox upload error: {e}")
        return False

# Slack 전송
def send_slack_text(text):
    if not SLACK_WEBHOOK:
        return False
    try:
        res = requests.post(SLACK_WEBHOOK, json={"text": text}, timeout=10)
        return res.status_code // 100 == 2
    except:
        return False

# Main
def main():
    items, sample = try_http_candidates()
    if not items:
        items, sample = try_playwright_render()
    if not items:
        send_slack_text("❌ OliveYoung scraping failed.")
        return 1

    items = fill_ranks_and_fix(items)
    now_kst = datetime.now(KST)
    date_str = now_kst.date().isoformat()
    time_str = FIXED_HHMM
    fname = f"올리브영_랭킹_{date_str}.csv"

    csv_lines = ["rank,brand,name,price,url,raw_name"]
    for it in items:
        def q(s):
            if s is None:
                return ""
            s = str(s).replace('"', '""')
            return f'"{s}"' if any(c in s for c in [',', '"', '\n']) else s
        csv_lines.append(",".join([q(it.get("rank")), q(it.get("brand")), q(it.get("name")), q(it.get("price")), q(it.get("url")), q(it.get("raw_name"))]))
    csv_data = "\n".join(csv_lines).encode("utf-8")

    # Dropbox 업로드
    dropbox_path = f"/rankings/{fname}"
    upload_to_dropbox(csv_data, dropbox_path)

    # Slack 메시지
    lines = [f"📊 OliveYoung Total Ranking ({date_str} {time_str} KST)"]
    for it in items[:10]:
        if it.get("url"):
            lines.append(f"{it['rank']}. <{it['url']}|{it['brand']} {it['name']}> — {it['price']}")
        else:
            lines.append(f"{it['rank']}. {it['brand']} {it['name']} — {it['price']}")
    send_slack_text("\n".join(lines))
    return 0

if __name__ == "__main__":
    exit(main())
