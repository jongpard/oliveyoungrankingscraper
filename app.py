#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# app.py — Dropbox Refresh Token 업로드 + 급하락 분석 + 14:01 KST 고정 표기

import os
import re
import json
import logging
from datetime import datetime
from io import BytesIO, StringIO
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

# ---------------- Playwright (옵션: HTTP가 실패할 때만 사용)
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False

# ---------------- 환경변수
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL", "").strip()

# Dropbox (Refresh Token 방식)
DROPBOX_APP_KEY = os.environ.get("DROPBOX_APP_KEY", "").strip()
DROPBOX_APP_SECRET = os.environ.get("DROPBOX_APP_SECRET", "").strip()
DROPBOX_REFRESH_TOKEN = os.environ.get("DROPBOX_REFRESH_TOKEN", "").strip()

# 업로드/저장
OUT_DIR = "rankings"
DROPBOX_DIR = "/rankings"   # Dropbox 내 업로드 폴더
MAX_ITEMS = 100

# 표기 시간
KST = ZoneInfo("Asia/Seoul")
FIXED_HHMM = "14:01"        # ‘오후 2시 1분’ 고정 표기

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# ---------------- 공통 세션
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

# ---------------- 파싱 유틸
def clean_title(raw: str) -> str:
    if not raw:
        return ""
    s = raw.strip()
    s = re.sub(r'^\s*(?:\[[^\]]*\]\s*)+', '', s)                       # [ ... ] 프리픽스 제거
    s = re.sub(r'^\s*([^|\n]{1,40}\|\s*)+', '', s)                     # 태그 | 태그 | ... 제거
    s = re.sub(r'^\s*(리뷰 이벤트|PICK|오특|이벤트|특가|[^\s]*PICK)\s*[:\-–—]?\s*',
               '', s, flags=re.IGNORECASE)                              # 홍보어 제거
    return re.sub(r'\s+', ' ', s).strip()

def extract_brand_from_name(name: str) -> str:
    if not name:
        return ""
    parts = re.split(r'[\s·\-–—\/\\\|,]+', name)
    if not parts:
        return ""
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
            price_node = (el.select_one(".tx_cur .tx_num") or el.select_one(".tx_cur")
                          or el.select_one(".prd_price .tx_num") or el.select_one(".prd_price"))
            price = price_node.get_text(strip=True) if price_node else ""
            brand_node = el.select_one(".tx_brand") or el.select_one(".brand")
            brand = brand_node.get_text(strip=True) if brand_node else extract_brand_from_name(cleaned)
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

# ---------------- 수집 (HTTP 우선, 실패 시 Playwright)
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
            logging.info("HTTP try: %s %s %s", name, url, params)
            r = session.get(url, params=params, timeout=15)
            logging.info(" -> status=%s, ct=%s, len=%d",
                         r.status_code, r.headers.get("Content-Type"), len(r.text or ""))
            if r.status_code != 200:
                continue
            text = r.text or ""
            ct = r.headers.get("Content-Type", "")
            # JSON 케이스
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
                                logging.info("HTTP JSON parsed via key=%s -> %d개", k, len(out))
                                return out, text[:800]
            # HTML 조각 파싱
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
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/120 Safari/537.36"),
                locale="ko-KR"
            )
            page = context.new_page()
            logging.info("Playwright goto: %s", url)
            page.goto(url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(2500)
            html = page.content()
            items = parse_html_products(html)
            browser.close()
            return items, html[:800]
    except Exception as e:
        logging.exception("Playwright render error: %s", e)
        return None, None

def fill_ranks(items):
    out = []
    for i, it in enumerate(items, start=1):
        it["rank"] = i
        out.append(it)
        if i >= MAX_ITEMS:
            break
    return out

# ---------------- Dropbox: 토큰 발급/업로드/검색/다운로드
def dbx_get_access_token():
    if not (DROPBOX_APP_KEY and DROPBOX_APP_SECRET and DROPBOX_REFRESH_TOKEN):
        raise RuntimeError("Dropbox env(DROPBOX_APP_KEY/SECRET/REFRESH_TOKEN) 미설정")
    r = requests.post(
        "https://api.dropboxapi.com/oauth2/token",
        data={"grant_type": "refresh_token", "refresh_token": DROPBOX_REFRESH_TOKEN},
        auth=(DROPBOX_APP_KEY, DROPBOX_APP_SECRET),
        timeout=15
    )
    r.raise_for_status()
    return r.json()["access_token"]

def dbx_upload(file_bytes: bytes, path: str):
    token = dbx_get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/octet-stream",
        "Dropbox-API-Arg": json.dumps({"path": path, "mode": "overwrite", "mute": False})
    }
    r = requests.post("https://content.dropboxapi.com/2/files/upload",
                      headers=headers, data=file_bytes, timeout=60)
    if r.status_code != 200:
        logging.error("Dropbox upload failed: %s %s", r.status_code, r.text[:200])
        return False
    logging.info("Uploaded to Dropbox: %s", path)
    return True

def dbx_list_latest_csv(prefix="올리브영_랭킹_", folder=DROPBOX_DIR):
    token = dbx_get_access_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"path": folder, "recursive": False, "include_media_info": False, "include_deleted": False}
    r = requests.post("https://api.dropboxapi.com/2/files/list_folder",
                      headers=headers, data=json.dumps(body), timeout=30)
    if r.status_code != 200:
        logging.warning("Dropbox list_folder failed: %s %s", r.status_code, r.text[:200])
        return None
    entries = r.json().get("entries", [])
    # 파일만 필터 + 이름 패턴 매칭
    files = [e for e in entries if e[".tag"] == "file" and e.get("name", "").startswith(prefix)]
    if not files:
        return None
    # server_modified(없으면 client_modified) 기준 최신
    files.sort(key=lambda x: x.get("server_modified") or x.get("client_modified") or x.get("name"), reverse=True)
    return files[0]

def dbx_download(path: str) -> str | None:
    token = dbx_get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Dropbox-API-Arg": json.dumps({"path": path})
    }
    r = requests.post("https://content.dropboxapi.com/2/files/download",
                      headers=headers, timeout=60)
    if r.status_code != 200:
        logging.warning("Dropbox download failed: %s %s", r.status_code, r.text[:200])
        return None
    return r.text

# ---------------- 분석: 전일 대비 상승/첫등장/하락
def analyze_trends(today_items, prev_items):
    """change = prev_rank - today_rank (양수=상승, 음수=하락)"""
    prev_map = {}
    for p in (prev_items or []):
        key = p.get("name") or p.get("raw_name")
        if key:
            prev_map[key] = p.get("rank")

    trends = []
    for it in today_items:
        key = it.get("name") or it.get("raw_name")
        prev_rank = prev_map.get(key)
        if prev_rank:
            change = prev_rank - it["rank"]
            trends.append({
                "name": key,
                "brand": it.get("brand"),
                "rank": it["rank"],
                "prev_rank": prev_rank,
                "change": change,
                "sample_product": it.get("name")
            })
        else:
            trends.append({
                "name": key,
                "brand": it.get("brand"),
                "rank": it["rank"],
                "prev_rank": None,
                "change": None,
                "sample_product": it.get("name")
            })

    movers = [t for t in trends if t.get("prev_rank")]
    movers_up = sorted(movers, key=lambda x: x["change"], reverse=True)   # 상승 TOP
    movers_down = sorted(movers, key=lambda x: x["change"])               # 하락 TOP(음수 큰順)
    firsts = [t for t in trends if t.get("prev_rank") is None]
    return movers_up, firsts, movers_down

# ---------------- Slack 전송
def send_slack_text(text):
    if not SLACK_WEBHOOK:
        logging.warning("No SLACK_WEBHOOK_URL configured.")
        return False
    try:
        r = requests.post(SLACK_WEBHOOK, json={"text": text}, timeout=10)
        if r.status_code // 100 == 2:
            logging.info("Slack sent")
            return True
        logging.warning("Slack returned %s: %s", r.status_code, r.text[:200])
        return False
    except Exception as e:
        logging.exception("Slack send error: %s", e)
        return False

# ---------------- 메인 플로우
def main():
    logging.info("Start scraping")

    items, sample = try_http_candidates()
    if not items:
        logging.info("HTTP failed → Playwright fallback")
        items, sample = try_playwright_render()

    if not items:
        logging.error("Scraping failed. sample head: %s", (sample or "")[:500])
        send_slack_text(f"❌ OliveYoung scraping failed.\n{(sample or '')[:800]}")
        return 1

    # 순위 연속 부여(오특 로직 없음)
    items = fill_ranks(items)

    # KST 날짜 + 고정 시간 표기(파일명은 날짜만)
    now_kst = datetime.now(KST)
    date_str = now_kst.date().isoformat()     # YYYY-MM-DD
    time_str = FIXED_HHMM
    fname = f"올리브영_랭킹_{date_str}.csv"

    # CSV 직작성
    def q(s):
        if s is None:
            return ""
        s = str(s).replace('"', '""')
        return f'"{s}"' if any(c in s for c in [',', '"', '\n']) else s

    csv_lines = ["rank,brand,name,price,url,raw_name"]
    for it in items:
        csv_lines.append(",".join([
            q(it.get("rank")), q(it.get("brand")), q(it.get("name")),
            q(it.get("price")), q(it.get("url")), q(it.get("raw_name"))
        ]))
    csv_bytes = ("\n".join(csv_lines)).encode("utf-8")

    # 로컬 백업 저장
    os.makedirs(OUT_DIR, exist_ok=True)
    local_path = os.path.join(OUT_DIR, fname)
    with open(local_path, "wb") as f:
        f.write(csv_bytes)
    logging.info("Saved CSV locally: %s", local_path)

    # Dropbox 업로드
    dropbox_path = f"{DROPBOX_DIR}/{fname}"
    dbx_upload(csv_bytes, dropbox_path)

    # Slack 상단 메시지
    top10 = items[:10]
    lines = [f"📊 OliveYoung Total Ranking ({date_str} {time_str} KST)"]
    for it in top10:
        if it.get("url"):
            lines.append(f"{it['rank']}. <{it['url']}|{it['brand']} {it['name']}> — {it['price']}")
        else:
            lines.append(f"{it['rank']}. {it['brand']} {it['name']} — {it['price']}")

    # Dropbox에서 "어제 파일" 찾기 → 추세 분석
    prev_items = []
    latest = dbx_list_latest_csv(prefix="올리브영_랭킹_", folder=DROPBOX_DIR)
    if latest and latest.get("name") != fname:
        prev_text = dbx_download(f"{DROPBOX_DIR}/{latest['name']}")
        if prev_text:
            try:
                import csv
                sio = StringIO(prev_text)
                rdr = csv.DictReader(sio)
                for r in rdr:
                    try:
                        prev_items.append({
                            "rank": int(r.get("rank") or 0),
                            "name": r.get("name"),
                            "raw_name": r.get("raw_name")
                        })
                    except:
                        continue
            except Exception as e:
                logging.exception("Prev CSV parse failed: %s", e)

    movers_up, firsts, movers_down = analyze_trends(items, prev_items)

    # 급상승
    lines.append("")
    lines.append("🔥 급상승 브랜드")
    if movers_up:
        for m in movers_up[:3]:
            change = m["prev_rank"] - m["rank"]
            lines.append(f"- {m.get('brand')}: {m.get('prev_rank')}위 → {m.get('rank')}위 (▲{change})")
            sample = m.get("sample_product") or m.get("name")
            if sample:
                lines.append(f"  ▶ {sample}")
    else:
        lines.append("- (전일 데이터 없음)")

    # 첫 등장
    first_true = [f for f in firsts if f.get("prev_rank") is None]
    lines.append("")
    lines.append("⭐ 첫 등장/주목 신상품")
    if first_true:
        for f in first_true[:3]:
            lines.append(f"- {f.get('brand')}: 첫 등장 {f.get('rank')}위")
            lines.append(f"  ▶ {f.get('sample_product')}")
    else:
        lines.append("- (전일 대비 신규 진입 없음)")

    # 급하락
    lines.append("")
    lines.append("📉 급하락 브랜드")
    if movers_down:
        for m in movers_down[:3]:
            drop = m["rank"] - m["prev_rank"]  # 양수면 하락 폭
            lines.append(f"- {m.get('brand')}: {m.get('prev_rank')}위 → {m.get('rank')}위 (▼{drop})")
            sample = m.get("sample_product") or m.get("name")
            if sample:
                lines.append(f"  ▶ {sample}")
    else:
        lines.append("- (전일 데이터 없음)")

    send_slack_text("\n".join(lines))
    logging.info("Done.")
    return 0

if __name__ == "__main__":
    exit(main())
