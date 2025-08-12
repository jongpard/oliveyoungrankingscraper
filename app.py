#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# app.py — OAuth(사용자 계정) 기반 GDrive 업로드 전용

import os
import re
import json
import time
import logging
import base64
from io import BytesIO, StringIO
from datetime import datetime, timedelta, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

# Playwright (옵션): HTTP가 막히면 폴백
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False

# Google Drive (OAuth)
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from google.oauth2.credentials import Credentials as UserCredentials
from google.auth.transport.requests import Request as GoogleRequest

# ----------------------------- 설정(환경변수)
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL", "").strip()

# OAuth (반드시 세팅)
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip()

# 업로드 대상 폴더
GDRIVE_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID", "").strip()

OUT_DIR = "rankings"
MAX_ITEMS = 100

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# ----------------------------- 공통 헬퍼
def kst_now():
    # KST(UTC+9)
    return datetime.now(timezone.utc) + timedelta(hours=9)

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

# ----------------------------- 파싱/정제
def clean_title(raw: str) -> str:
    if not raw:
        return ""
    s = raw.strip()
    # 맨 앞 대괄호 태그들 제거
    s = re.sub(r'^\s*(?:\[[^\]]*\]\s*)+', '', s)
    # 프로모션 토막 제거 ("PICK |", "리뷰", 짧은 태그들 등)
    s = re.sub(r'^\s*([^|\n]{1,40}\|\s*)+', '', s)
    s = re.sub(r'^\s*(리뷰 이벤트|PICK|오특|이벤트|특가|[^\s]*PICK)\s*[:\-–—]?\s*', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def extract_brand_from_name(name: str) -> str:
    if not name:
        return ""
    parts = re.split(r'[\s·\-–—\/\\\|,]+', name)
    if parts:
        cand = parts[0]
        if re.match(r'^\d|\+|세트|기획', cand):
            if len(parts) > 1:
                return parts[1]
            return cand
        return cand
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
        for _, el in enumerate(els, start=1):
            if len(results) >= MAX_ITEMS:
                break
            # 이름
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

            # 가격
            price_node = el.select_one(".tx_cur .tx_num") or el.select_one(".tx_cur") or el.select_one(".prd_price .tx_num") or el.select_one(".prd_price")
            price = price_node.get_text(strip=True) if price_node else ""

            # 브랜드
            brand_node = el.select_one(".tx_brand") or el.select_one(".brand")
            brand = brand_node.get_text(strip=True) if brand_node else extract_brand_from_name(cleaned)

            # 링크
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
                "rank": None
            })
        if results:
            logging.info("parse_html_products: %s -> %d개", sel, len(results))
            break
    return results

def try_http_candidates():
    session = make_session()
    candidates = [
        ("getBestList", "https://www.oliveyoung.co.kr/store/main/getBestList.do", {"rowsPerPage": str(MAX_ITEMS), "pageIdx":"0"}),
        ("getBestList_disp_total", "https://www.oliveyoung.co.kr/store/main/getBestList.do", {"dispCatNo":"90000010001", "rowsPerPage": str(MAX_ITEMS), "pageIdx":"0"}),
        ("getTopSellerList", "https://www.oliveyoung.co.kr/store/main/getTopSellerList.do", {"rowsPerPage": str(MAX_ITEMS), "pageIdx":"0"}),
        ("getBestListJson", "https://www.oliveyoung.co.kr/store/main/getBestListJson.do", {"rowsPerPage": str(MAX_ITEMS), "pageIdx":"0"}),
    ]
    for name, url, params in candidates:
        try:
            logging.info("HTTP try: %s %s %s", name, url, params)
            r = session.get(url, params=params, timeout=15)
            logging.info(" -> status=%s, ct=%s, len=%d", r.status_code, r.headers.get("Content-Type"), len(r.text or ""))
            if r.status_code != 200:
                continue
            ct = r.headers.get("Content-Type","")
            text = r.text or ""

            # JSON 시도
            if "application/json" in ct or text.strip().startswith("{") or text.strip().startswith("["):
                try:
                    data = r.json()
                except Exception:
                    data = None
                if isinstance(data, dict):
                    for k in ["BestProductList", "list", "rows", "items", "bestList", "result"]:
                        if k in data and isinstance(data[k], list) and data[k]:
                            out = []
                            for it in data[k][:MAX_ITEMS]:
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
                                logging.info("HTTP JSON parse via key %s -> %d개", k, len(out))
                                return out, text[:800]
            # HTML 파싱
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
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
                locale="ko-KR"
            )
            page = context.new_page()
            logging.info("Playwright goto (try 1): https://www.oliveyoung.co.kr/store/main/getBest.do")
            try:
                page.goto("https://www.oliveyoung.co.kr/store/main/getBest.do", wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
            logging.info("Playwright goto (try 1): https://www.oliveyoung.co.kr/store/main/getBestList.do")
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
    out = []
    rank = 1
    for it in items:
        it["rank"] = rank
        out.append(it)
        rank += 1
        if rank > MAX_ITEMS:
            break
    return out

# ----------------------------- Google Drive (OAuth)
def build_drive_service_oauth():
    """사용자 OAuth(refresh token) 기반 Drive 서비스 생성"""
    if not (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REFRESH_TOKEN):
        logging.warning("OAuth env 미설정 (GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN)")
        return None
    try:
        creds = UserCredentials(
            None,
            refresh_token=GOOGLE_REFRESH_TOKEN,
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=["https://www.googleapis.com/auth/drive.file"],
        )
        creds.refresh(GoogleRequest())
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        return service
    except Exception as e:
        logging.exception("OAuth Drive service 생성 실패: %s", e)
        return None

def upload_csv_to_drive(service, csv_bytes, filename, folder_id=None):
    if not service:
        logging.warning("Drive service 없음 → 업로드 스킵")
        return None
    try:
        media = MediaIoBaseUpload(BytesIO(csv_bytes), mimetype="text/csv", resumable=False)
        body = {"name": filename}
        if folder_id:
            body["parents"] = [folder_id]
        f = service.files().create(body=body, media_body=media, fields="id,webViewLink").execute()
        logging.info("Uploaded to Drive: id=%s link=%s", f.get("id"), f.get("webViewLink"))
        return f
    except Exception as e:
        logging.exception("Drive upload 실패: %s", e)
        return None

def find_latest_csv_in_drive(service, folder_id):
    try:
        q = f"mimeType='text/csv' and name contains '올리브영_랭킹' and '{folder_id}' in parents" if folder_id \
            else "mimeType='text/csv' and name contains '올리브영_랭킹'"
        res = service.files().list(q=q, orderBy="createdTime desc", pageSize=10, fields="files(id,name,createdTime)").execute()
        files = res.get("files", [])
        return files[0] if files else None
    except Exception as e:
        logging.exception("find_latest_csv_in_drive error: %s", e)
        return None

def download_file_from_drive(service, file_id):
    try:
        request = service.files().get_media(fileId=file_id)
        fh = BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        fh.seek(0)
        return fh.read().decode("utf-8")
    except Exception as e:
        logging.exception("download_file_from_drive error: %s", e)
        return None

# ----------------------------- 분석(급상승/급하락/신규)
def analyze_trends(today_items, prev_items):
    prev_map = {}
    for p in (prev_items or []):
        key = p.get("name") or p.get("raw_name")
        prev_map[key] = p.get("rank")

    trends = []
    for it in today_items:
        key = it.get("name") or it.get("raw_name")
        prev_rank = prev_map.get(key)
        if prev_rank:
            change = prev_rank - it['rank']  # +면 상승, -면 하락
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
    up = sorted(movers, key=lambda x: x["change"], reverse=True)   # 급상승
    down = sorted(movers, key=lambda x: x["change"])               # 급하락(가장 음수)
    firsts = [t for t in trends if t.get("prev_rank") is None]     # 신규

    return up, down, firsts

# ----------------------------- Slack
def send_slack_text(text):
    if not SLACK_WEBHOOK:
        logging.warning("No SLACK_WEBHOOK configured.")
        return False
    try:
        res = requests.post(SLACK_WEBHOOK, json={"text": text}, timeout=10)
        if res.status_code // 100 == 2:
            logging.info("Slack sent")
            return True
        logging.warning("Slack returned %s: %s", res.status_code, res.text[:200])
        return False
    except Exception as e:
        logging.exception("Slack send error: %s", e)
        return False

# ----------------------------- 메인
def main():
    # 빌드 배너 (KST 기준 날짜 표시)
    today_kst = kst_now().date()
    logging.info("Build: oy-app gdrive-only %s", today_kst.isoformat())

    logging.info("Start scraping")
    items, sample = try_http_candidates()
    if not items:
        logging.info("HTTP failed → Playwright fallback")
        items, sample = try_playwright_render()
    if not items:
        logging.error("Scraping failed. sample head: %s", (sample or "")[:500])
        send_slack_text(f"❌ OliveYoung scraping failed. sample:\n{(sample or '')[:800]}")
        return 1

    if len(items) > MAX_ITEMS:
        items = items[:MAX_ITEMS]
    items_filled = fill_ranks_and_fix(items)

    # CSV 생성
    os.makedirs(OUT_DIR, exist_ok=True)
    fname = f"올리브영_랭킹_{today_kst.isoformat()}.csv"
    header = ["rank","brand","name","price","url","raw_name"]
    lines = [",".join(header)]

    def q(s):
        if s is None:
            return ""
        s = str(s).replace('"','""')
        if ',' in s or '\n' in s or '"' in s:
            return f'"{s}"'
        return s

    for it in items_filled:
        row = [q(it.get("rank")), q(it.get("brand")), q(it.get("name")), q(it.get("price")), q(it.get("url")), q(it.get("raw_name"))]
        lines.append(",".join(row))
    csv_data = ("\n".join(lines)).encode("utf-8")

    # 로컬 백업
    path = os.path.join(OUT_DIR, fname)
    with open(path, "wb") as f:
        f.write(csv_data)
    logging.info("Saved CSV locally: %s", path)

    # Google Drive 업로드 (OAuth)
    drive_service = build_drive_service_oauth()
    if drive_service and GDRIVE_FOLDER_ID:
        upload_csv_to_drive(drive_service, csv_data, fname, folder_id=GDRIVE_FOLDER_ID)
    else:
        logging.warning("OAuth Drive 미설정 또는 폴더ID 누락 -> 업로드 스킵")

    # 전일 파일 비교(있으면)
    prev_items = None
    if drive_service and GDRIVE_FOLDER_ID:
        latest = find_latest_csv_in_drive(drive_service, GDRIVE_FOLDER_ID)
        if latest and latest.get("name") != fname:
            logging.info("Found previous file %s - downloading", latest.get("name"))
            prev_csv_text = download_file_from_drive(drive_service, latest.get("id"))
            if prev_csv_text:
                prev_items = []
                try:
                    import csv
                    sio = StringIO(prev_csv_text)
                    rdr = csv.DictReader(sio)
                    for r in rdr:
                        try:
                            prev_items.append({"rank": int(r.get("rank") or 0), "name": r.get("name"), "raw_name": r.get("raw_name")})
                        except Exception:
                            continue
                except Exception as e:
                    logging.exception("CSV parse failed: %s", e)

    up, down, firsts = analyze_trends(items_filled, prev_items or [])

    # Slack 메시지 구성 (상위 10, 급상승/급하락/신규)
    top10 = items_filled[:10]
    msg = []
    now_kst = kst_now().strftime("%Y-%m-%d %H:%M KST")
    msg.append(f"📊 OliveYoung Total Ranking ({now_kst})")
    for it in top10:
        rank = it.get("rank")
        brand = it.get("brand") or ""
        name = it.get("name") or ""
        price = it.get("price") or ""
        url = it.get("url")
        if url:
            msg.append(f"{rank}. <{url}|{brand} {name}> — {price}")
        else:
            msg.append(f"{rank}. {brand} {name} — {price}")

    msg.append("")
    msg.append("🔥 급상승 TOP3")
    if up:
        for m in up[:3]:
            change = m["prev_rank"] - m["rank"]
            msg.append(f"- {m.get('brand')}: {m.get('prev_rank')}위 → {m.get('rank')}위 (+{change})")
            sample = m.get("sample_product") or m.get("name")
            if sample:
                msg.append(f"  ▶ {sample}")
    else:
        msg.append("- (이전 데이터 없음)")

    msg.append("")
    msg.append("📉 급하락 TOP3")
    downs = [m for m in down if m["change"] < 0][:3]
    if downs:
        for m in downs:
            change = m["rank"] - m["prev_rank"]
            msg.append(f"- {m.get('brand')}: {m.get('prev_rank')}위 → {m.get('rank')}위 (-{change})")
            sample = m.get("sample_product") or m.get("name")
            if sample:
                msg.append(f"  ▶ {sample}")
    else:
        msg.append("- (이전 데이터 없음)")

    msg.append("")
    msg.append("🆕 첫 등장/주목 신상품")
    if firsts:
        for f in firsts[:3]:
            msg.append(f"- {f.get('brand')}: 첫 등장 {f.get('rank')}위")
            msg.append(f"  ▶ {f.get('sample_product')}")
    else:
        msg.append("- (신규 없음)")

    send_slack_text("\n".join(msg))
    logging.info("Done.")
    return 0

if __name__ == "__main__":
    exit(main())
