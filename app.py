#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# app.py — GDrive(OAuth, 사용자 계정) 업로드 + 할인율/전일비 분석(한국시간) + Slack 포맷 개선(국내 OY)

import os
import re
import csv
import json
import logging
from io import BytesIO, StringIO
from typing import List, Dict, Optional
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, parse_qs

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

# (optional) Playwright fallback
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

# ---------------- 설정(ENV)
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL", "").strip()

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip()
GDRIVE_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID", "").strip()

OUT_DIR = "rankings"
MAX_ITEMS = 100        # 크롤링 최대 아이템

KST = timezone(timedelta(hours=9))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")


# ---------------- 유틸
def kst_now() -> datetime:
    return datetime.now(KST)

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

_won_pat = re.compile(r"[\d,]+")

def parse_won_to_int(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    m = _won_pat.search(s)
    if not m:
        return None
    try:
        return int(m.group(0).replace(",", ""))
    except Exception:
        return None

def fmt_price_with_discount(sale: Optional[int], disc_pct: Optional[int]) -> str:
    if not sale:
        return ""
    if disc_pct is None:
        return f"{sale:,}원"
    return f"{sale:,}원 (↓{disc_pct}%)"

def _slack_escape(s: Optional[str]) -> str:
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _clean_text(s: Optional[str]) -> str:
    # 연속 공백 정규화
    return re.sub(r"\s+", " ", (s or "")).strip()

def _oy_goodsno_from_url(u: Optional[str]) -> str:
    """URL에서 goodsNo만 추출해 안정 키로 사용"""
    if not u:
        return ""
    try:
        return parse_qs(urlparse(u).query).get("goodsNo", [""])[0]
    except Exception:
        return ""

def _oy_key(it: Dict) -> str:
    """키 생성: URL 정규화(goodsNo) 우선, 없으면 name/raw_name"""
    g = _oy_goodsno_from_url((it.get("url") or "").strip())
    if g:
        return f"g:{g}"
    return (it.get("name") or it.get("raw_name") or "").strip()

def _link(name: str, url: Optional[str]) -> str:
    return f"<{url}|{_slack_escape(name)}>" if url else _slack_escape(name)


# ---------------- 파싱/정제
def clean_title(raw: str) -> str:
    if not raw:
        return ""
    s = raw.strip()
    s = re.sub(r'^\s*(?:\[[^\]]*\]\s*)+', '', s)  # [ ... ] 제거
    s = re.sub(r'^\s*([^|\n]{1,40}\|\s*)+', '', s)  # 앞단 프로모션 토막 제거
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
            return parts[1] if len(parts) > 1 else cand
        return cand
    return name

def parse_html_products(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    candidate_selectors = [
        "ul.cate_prd_list li",
        "ul.prd_list li",
        ".cate_prd_list li",
        ".ranking_list li",
        ".rank_item",
    ]
    results: List[Dict] = []
    for sel in candidate_selectors:
        els = soup.select(sel)
        if not els:
            continue
        for el in els:
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
            sale_node = el.select_one(".tx_cur .tx_num") or el.select_one(".tx_cur")
            org_node  = el.select_one(".tx_org .tx_num") or el.select_one(".tx_org")
            sale_price = parse_won_to_int(sale_node.get_text(strip=True) if sale_node else "")
            original_price = parse_won_to_int(org_node.get_text(strip=True) if org_node else "")

            # 브랜드
            brand_node = el.select_one(".tx_brand") or el.select_one(".brand")
            brand = brand_node.get_text(strip=True) if brand_node else extract_brand_from_name(cleaned)

            # 링크
            link_node = el.select_one("a")
            href = link_node.get("href") if link_node else None
            if href and href.startswith("/"):
                href = "https://www.oliveyoung.co.kr" + href

            # 할인율
            disc_pct = None
            if original_price and sale_price and original_price > sale_price:
                disc_pct = int((original_price - sale_price) / original_price * 100)

            results.append({
                "raw_name": raw_name,
                "name": cleaned,
                "brand": brand,
                "url": href,
                "original_price": original_price,
                "sale_price": sale_price,
                "discount_pct": disc_pct,
                "rank": None,
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

            # JSON 스키마 추정
            if "application/json" in ct or text.strip().startswith("{") or text.strip().startswith("["):
                try:
                    data = r.json()
                except Exception:
                    data = None
                if isinstance(data, dict):
                    for k in ["BestProductList", "list", "rows", "items", "bestList", "result"]:
                        if k in data and isinstance(data[k], list) and data[k]:
                            out: List[Dict] = []
                            for it in data[k][:MAX_ITEMS]:
                                name_val = it.get("prdNm") or it.get("prodName") or it.get("goodsNm") or it.get("name")
                                brand_val = it.get("brandNm") or it.get("brand")
                                url_val = it.get("goodsUrl") or it.get("prdUrl") or it.get("url")

                                sale_val = it.get("price") or it.get("salePrice") or it.get("onlinePrice") or it.get("finalPrice")
                                org_val  = it.get("orgPrice") or it.get("originalPrice") or it.get("listPrice")
                                sale_price = parse_won_to_int(str(sale_val) if sale_val is not None else "")
                                original_price = parse_won_to_int(str(org_val) if org_val is not None else "")

                                if isinstance(url_val, str) and url_val.startswith("/"):
                                    url_val = "https://www.oliveyoung.co.kr" + url_val
                                cleaned = clean_title(name_val or "")
                                brand = brand_val or extract_brand_from_name(cleaned)

                                disc_pct = None
                                if original_price and sale_price and original_price > sale_price:
                                    disc_pct = int((original_price - sale_price) / original_price * 100)

                                out.append({
                                    "raw_name": name_val,
                                    "name": cleaned,
                                    "brand": brand,
                                    "url": url_val,
                                    "original_price": original_price,
                                    "sale_price": sale_price,
                                    "discount_pct": disc_pct,
                                    "rank": None,
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

def fill_ranks_and_fix(items: List[Dict]) -> List[Dict]:
    out: List[Dict] = []
    rank = 1
    for it in items:
        it["rank"] = rank
        out.append(it)
        rank += 1
        if rank > MAX_ITEMS:
            break
    return out


# ---------------- Google Drive (OAuth)
def build_drive_service_oauth():
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
        return None
    try:
        media = MediaIoBaseUpload(BytesIO(csv_bytes), mimetype="text/csv", resumable=False)
        body = {"name": filename}
        if folder_id:
            body["parents"] = [folder_id]
        f = service.files().create(body=body, media_body=media, fields="id,webViewLink,name").execute()
        logging.info("Uploaded to Drive: id=%s name=%s link=%s", f.get("id"), f.get("name"), f.get("webViewLink"))
        return f
    except Exception as e:
        logging.exception("Drive upload 실패: %s", e)
        return None

def find_csv_by_exact_name(service, folder_id: str, filename: str):
    """파일명(정확일치)으로 검색 (한국시간 기반 전일 파일 찾기에 사용)."""
    try:
        if folder_id:
            q = f"name='{filename}' and '{folder_id}' in parents and mimeType='text/csv'"
        else:
            q = f"name='{filename}' and mimeType='text/csv'"
        res = service.files().list(q=q, pageSize=1, fields="files(id,name,createdTime)").execute()
        files = res.get("files", [])
        return files[0] if files else None
    except Exception as e:
        logging.exception("find_csv_by_exact_name error: %s", e)
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


# ---------------- Slack 기본 전송
def send_slack_text(text: str) -> bool:
    if not SLACK_WEBHOOK:
        logging.warning("No SLACK_WEBHOOK configured.")
        return False
    try:
        res = requests.post(SLACK_WEBHOOK, json={"text": text}, timeout=10)
        return res.status_code // 100 == 2
    except Exception:
        return False


# ---------------- Slack 메시지(국내판)
def build_slack_message_kor(
    date_str: str,
    today_items: List[Dict],
    prev_items: List[Dict],
    total_count: int
) -> str:
    """
    규칙:
      - TOP10: 전일 대비 배지 (↑n / ↓n / (-) / (new))
      - 🔥 급상승 / 📉 급하락: Top100 전체, 변동 10계단 이상, 각 5개
      - 🆕 뉴랭커: 최대 5개
      - ❌ OUT: 전일 ≤100 이고 오늘 Top100에 없는 항목, 최대 5개 (전일 URL로 링크)
      - ↔ 인&아웃: Top100 교체 수(대칭차집합/2, goodsNo 기준)
    """

    # 전일 rank/url 맵 (key = goodsNo 기반의 _oy_key)
    prev_rank_map: Dict[str, int] = {}
    prev_url_map: Dict[str, str] = {}
    for p in (prev_items or []):
        k = _oy_key(p)
        if not k:
            continue
        try:
            prev_rank_map[k] = int(p.get("rank") or 0)
        except Exception:
            continue
        if p.get("url"):
            prev_url_map[k] = p["url"]

    # 오늘 key → rank/url/name
    today_key_rank: Dict[str, int] = {}
    today_key_url: Dict[str, str] = {}
    today_key_name: Dict[str, str] = {}
    for t in (today_items or []):
        k = _oy_key(t)
        if not k:
            continue
        try:
            r = int(t.get("rank") or 0)
        except Exception:
            r = 0
        today_key_rank[k] = r
        today_key_url[k]  = t.get("url") or ""
        today_key_name[k] = t.get("name") or t.get("raw_name") or ""

    # ---------- TOP10 ----------
    top10_lines: List[str] = []
    for t in (today_items or [])[:10]:
        k   = _oy_key(t)
        cur = int(t.get("rank") or 0)
        nm  = _clean_text(t.get("name") or t.get("raw_name"))
        url = t.get("url")
        if k in prev_rank_map:
            prev = int(prev_rank_map.get(k) or 0)
            if prev > 0:
                if cur < prev:
                    badge = f"(↑{prev - cur})"
                elif cur > prev:
                    badge = f"(↓{cur - prev})"
                else:
                    badge = "(-)"
            else:
                badge = "(-)"
        else:
            badge = "(new)"
        price_txt = fmt_price_with_discount(t.get("sale_price"), t.get("discount_pct"))
        top10_lines.append(f"{cur}. {badge} {_link(nm, url)} — {price_txt}")

    # 전일 데이터 없으면 TOP10만
    if not prev_rank_map:
        header = f"*올리브영 국내 Top 100* ({date_str})"
        return "\n".join([header, "", "*TOP 10*", *(top10_lines or ["- 데이터 없음"])])

    # ---------- Top100 비교 ----------
    today_keys = set(today_key_rank.keys())
    prev_keys  = set(prev_rank_map.keys())
    common     = today_keys & prev_keys

    # 급상승/급하락 (±10)
    ups, downs = [], []
    for k in common:
        pr = int(prev_rank_map[k])
        cr = int(today_key_rank[k])
        diff = pr - cr
        if diff >= 10:
            ups.append((diff, cr, pr, k))
        elif diff <= -10:
            downs.append((-diff, cr, pr, k))  # 절댓값

    ups.sort(key=lambda x: (-x[0], x[1], x[2], x[3]))
    downs.sort(key=lambda x: (-x[0], x[1], x[2], x[3]))

    ups_lines   = [f"- {_link(today_key_name.get(k,''), today_key_url.get(k))} {pr}위 → {cr}위 (↑{imp})"
                   for imp, cr, pr, k in ups[:5]] or ["- 해당 없음"]
    downs_lines = [f"- {_link(today_key_name.get(k,''), today_key_url.get(k))} {pr}위 → {cr}위 (↓{drop})"
                   for drop, cr, pr, k in downs[:5]] or ["- 해당 없음"]

    # 뉴랭커
    newcomers = []
    for k in today_keys - prev_keys:
        r = int(today_key_rank.get(k) or 0)
        if 1 <= r <= 100:
            newcomers.append((r, f"- {_link(today_key_name.get(k,''), today_key_url.get(k))} NEW → {r}위"))
    newcomers.sort(key=lambda x: x[0])
    newcomer_lines = [ln for _, ln in newcomers[:5]] or ["- 해당 없음"]

    # OUT(전일 ≤100, 오늘 Top100 미포함)
    outs = []
    for k, pr in sorted(prev_rank_map.items(), key=lambda kv: kv[1]):
        if 1 <= pr <= 100 and k not in today_keys:
            outs.append((pr, f"- {_link(today_key_name.get(k, ''), prev_url_map.get(k))} {pr}위 → OUT"))
    out_lines = [ln for _, ln in outs[:5]] or ["- 해당 없음"]

    # 인&아웃(교체 수) – Top100 대칭차집합/2
    today_top_keys = {k for k, r in today_key_rank.items() if 1 <= r <= 100}
    prev_top_keys  = {k for k, r in prev_rank_map.items() if 1 <= r <= 100}
    inout_count    = len(today_top_keys ^ prev_top_keys) // 2

    # 메시지 조립
    header = f"*올리브영 국내 Top 100* ({date_str})"
    lines: List[str] = [
        header, "",
        "*TOP 10*", *(top10_lines or ["- 데이터 없음"]),
        "",
        "*🔥 급상승*", *ups_lines,
        "",
        "*🆕 뉴랭커*", *newcomer_lines,
        "",
        "*📉 급하락*", *downs_lines,
        "",
        "*❌ OUT*", *out_lines,
        "",
        "*↔ 랭크 인&아웃*",
        f"{inout_count}개의 제품이 인&아웃 되었습니다.",
    ]
    return "\n".join(lines)


# ---------------- 메인
def main() -> int:
    now = kst_now()
    today_ymd = now.date()
    yesterday_ymd = (now - timedelta(days=1)).date()
    logging.info("Build: oy-app gdrive+discount %s", today_ymd.isoformat())

    # 1) 스크래핑
    logging.info("Start scraping")
    items, sample = try_http_candidates()
    if not items:
        logging.info("HTTP failed → Playwright fallback")
        items, sample = try_playwright_render()
    if not items:
        logging.error("Scraping failed. sample head: %s", (sample or "")[:500])
        send_slack_text(f"❌ OliveYoung scraping failed.\n{(sample or '')[:800]}")
        return 1

    if len(items) > MAX_ITEMS:
        items = items[:MAX_ITEMS]
    items_filled = fill_ranks_and_fix(items)

    # 2) CSV 생성
    os.makedirs(OUT_DIR, exist_ok=True)
    fname_today = f"올리브영_랭킹_{today_ymd.isoformat()}.csv"
    header = ["rank","brand","name","original_price","sale_price","discount_pct","url","raw_name"]
    rows = [",".join(header)]

    def q(s):
        if s is None:
            return ""
        s = str(s).replace('"','""')
        if any(c in s for c in [',','\n','"']):
            return f'"{s}"'
        return s

    for it in items_filled:
        rows.append(",".join([
            q(it.get("rank")),
            q(it.get("brand")),
            q(it.get("name")),
            q(it.get("original_price") if it.get("original_price") is not None else ""),
            q(it.get("sale_price") if it.get("sale_price") is not None else ""),
            q(it.get("discount_pct") if it.get("discount_pct") is not None else ""),
            q(it.get("url")),
            q(it.get("raw_name")),
        ]))
    csv_bytes = ("\n".join(rows)).encode("utf-8")

    # 로컬 저장
    path = os.path.join(OUT_DIR, fname_today)
    with open(path, "wb") as f:
        f.write(csv_bytes)
    logging.info("Saved CSV locally: %s", path)

    # 3) GDrive 업로드
    drive_service = build_drive_service_oauth()
    if drive_service and GDRIVE_FOLDER_ID:
        upload_csv_to_drive(drive_service, csv_bytes, fname_today, folder_id=GDRIVE_FOLDER_ID)
    else:
        logging.warning("OAuth Drive 미설정 또는 폴더ID 누락 -> 업로드 스킵")

    # 4) 전일(csv) 로드 — 한국시간 파일명 기준
    prev_items: List[Dict] = []
    if drive_service and GDRIVE_FOLDER_ID:
        fname_yesterday = f"올리브영_랭킹_{yesterday_ymd.isoformat()}.csv"
        y_file = find_csv_by_exact_name(drive_service, GDRIVE_FOLDER_ID, fname_yesterday)
        if not y_file:
            logging.warning("전일 파일명(%s)로 찾지 못함 → 최신 CSV 백업 검색", fname_yesterday)
            try:
                q = f"mimeType='text/csv' and name contains '올리브영_랭킹' and '{GDRIVE_FOLDER_ID}' in parents"
                r = drive_service.files().list(q=q, orderBy="createdTime desc", pageSize=2,
                                               fields="files(id,name,createdTime)").execute()
                files = r.get("files", [])
                for fmeta in files:
                    if fmeta.get("name") != fname_today:
                        y_file = fmeta
                        break
            except Exception as e:
                logging.exception("백업 검색 실패: %s", e)
        if y_file:
            prev_csv_text = download_file_from_drive(drive_service, y_file.get("id"))
            if prev_csv_text:
                sio = StringIO(prev_csv_text)
                rdr = csv.DictReader(sio)
                for r in rdr:
                    try:
                        prev_items.append({
                            "rank": int(r.get("rank") or 0),
                            "name": r.get("name"),
                            "raw_name": r.get("raw_name"),
                            "brand": r.get("brand"),
                            "url": r.get("url"),   # OUT 링크용
                        })
                    except Exception:
                        continue

    # 5) 슬랙 메시지 생성 + 전송
    date_str = now.strftime("%Y-%m-%d %H:%M KST")
    text = build_slack_message_kor(
        date_str=date_str,
        today_items=items_filled,
        prev_items=prev_items or [],
        total_count=len(items_filled),
    )
    send_slack_text(text)

    logging.info("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
