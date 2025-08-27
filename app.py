#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# OliveYoung(국내) 랭킹 수집 + GDrive 업로드 + Slack 알림 (급하락=하락5 + OUT5)

import os
import re
import csv
import logging
from io import BytesIO, StringIO
from typing import List, Dict, Optional
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, parse_qs

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

# (선택) Playwright 폴백
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False

# Google Drive (OAuth 사용자 계정)
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from google.oauth2.credentials import Credentials as UserCredentials
from google.auth.transport.requests import Request as GoogleRequest

# ---------------- ENV
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL", "").strip()

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip()
GDRIVE_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID", "").strip()

OUT_DIR = "rankings"
MAX_ITEMS = 100

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
    if not s: return None
    m = _won_pat.search(s)
    if not m: return None
    try: return int(m.group(0).replace(",", ""))
    except Exception: return None

def fmt_price_with_discount(sale: Optional[int], disc_pct: Optional[int]) -> str:
    if not sale: return ""
    return f"{sale:,}원" if disc_pct is None else f"{sale:,}원 (↓{disc_pct}%)"

def _slack_escape(s: Optional[str]) -> str:
    if s is None: return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _clean_text(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def _oy_goodsno_from_url(u: Optional[str]) -> str:
    if not u: return ""
    try:
        return parse_qs(urlparse(u).query).get("goodsNo", [""])[0]
    except Exception:
        return ""

def _oy_key(it: Dict) -> str:
    g = _oy_goodsno_from_url((it.get("url") or "").strip())
    if g: return f"g:{g}"
    return (it.get("name") or it.get("raw_name") or "").strip()

def _link(name: str, url: Optional[str]) -> str:
    return f"<{url}|{_slack_escape(name)}>" if url else _slack_escape(name)

# ---------------- 파싱
def clean_title(raw: str) -> str:
    if not raw: return ""
    s = raw.strip()
    s = re.sub(r'^\s*(?:\[[^\]]*\]\s*)+', '', s)
    s = re.sub(r'^\s*([^|\n]{1,40}\|\s*)+', '', s)
    s = re.sub(r'^\s*(리뷰 이벤트|PICK|오특|이벤트|특가|[^\s]*PICK)\s*[:\-–—]?\s*', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def extract_brand_from_name(name: str) -> str:
    if not name: return ""
    parts = re.split(r'[\s·\-–—\/\\\|,]+', name)
    if parts:
        cand = parts[0]
        if re.match(r'^\d|\+|세트|기획', cand):
            return parts[1] if len(parts) > 1 else cand
        return cand
    return name

def parse_html_products(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    sels = ["ul.cate_prd_list li", "ul.prd_list li", ".cate_prd_list li", ".ranking_list li", ".rank_item"]
    out: List[Dict] = []
    for sel in sels:
        els = soup.select(sel)
        if not els: continue
        for el in els:
            if len(out) >= MAX_ITEMS: break

            name_node = None
            for ns in [".tx_name", ".prd_name .tx_name", ".prd_name", ".prd_tit", "a"]:
                node = el.select_one(ns)
                if node and node.get_text(strip=True):
                    name_node = node; break
            if not name_node: continue
            raw_name = name_node.get_text(" ", strip=True)
            cleaned = clean_title(raw_name)

            sale_node = el.select_one(".tx_cur .tx_num") or el.select_one(".tx_cur")
            org_node  = el.select_one(".tx_org .tx_num") or el.select_one(".tx_org")
            sale_price = parse_won_to_int(sale_node.get_text(strip=True) if sale_node else "")
            original_price = parse_won_to_int(org_node.get_text(strip=True) if org_node else "")

            brand_node = el.select_one(".tx_brand") or el.select_one(".brand")
            brand = brand_node.get_text(strip=True) if brand_node else extract_brand_from_name(cleaned)

            link_node = el.select_one("a")
            href = link_node.get("href") if link_node else None
            if href and href.startswith("/"):
                href = "https://www.oliveyoung.co.kr" + href

            disc_pct = None
            if original_price and sale_price and original_price > sale_price:
                disc_pct = int((original_price - sale_price) / original_price * 100)

            out.append({
                "raw_name": raw_name, "name": cleaned, "brand": brand, "url": href,
                "original_price": original_price, "sale_price": sale_price,
                "discount_pct": disc_pct, "rank": None,
            })
        if out: break
    return out

def try_http_candidates():
    s = make_session()
    cands = [
        ("getBestList", "https://www.oliveyoung.co.kr/store/main/getBestList.do",
         {"rowsPerPage": str(MAX_ITEMS), "pageIdx":"0"}),
        ("getBestList_disp_total", "https://www.oliveyoung.co.kr/store/main/getBestList.do",
         {"dispCatNo":"90000010001","rowsPerPage": str(MAX_ITEMS), "pageIdx":"0"}),
        ("getTopSellerList", "https://www.oliveyoung.co.kr/store/main/getTopSellerList.do",
         {"rowsPerPage": str(MAX_ITEMS), "pageIdx":"0"}),
        ("getBestListJson", "https://www.oliveyoung.co.kr/store/main/getBestListJson.do",
         {"rowsPerPage": str(MAX_ITEMS), "pageIdx":"0"}),
    ]
    for name, url, params in cands:
        try:
            logging.info("HTTP try: %s %s %s", name, url, params)
            r = s.get(url, params=params, timeout=15)
            logging.info(" -> status=%s, ct=%s, len=%d", r.status_code, r.headers.get("Content-Type"), len(r.text or ""))
            if r.status_code != 200:
                continue
            ct = r.headers.get("Content-Type","")
            text = r.text or ""

            # JSON 스키마
            if "application/json" in ct or text.strip().startswith(("{","[")):
                try: data = r.json()
                except Exception: data = None
                if isinstance(data, dict):
                    for k in ["BestProductList","list","rows","items","bestList","result"]:
                        if k in data and isinstance(data[k], list) and data[k]:
                            out=[]
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
                                    "raw_name": name_val, "name": cleaned, "brand": brand, "url": url_val,
                                    "original_price": original_price, "sale_price": sale_price,
                                    "discount_pct": disc_pct, "rank": None,
                                })
                            if out:
                                logging.info("HTTP JSON parse via key %s -> %d개", k, len(out))
                                return out, text[:800]
            # HTML
            items = parse_html_products(text)
            if items:
                return items, text[:800]
        except Exception as e:
            logging.exception("HTTP candidate error: %s %s", url, e)
    return None, None

def try_playwright_render(url="https://www.oliveyoung.co.kr/store/main/getBestList.do"):
    if not PLAYWRIGHT_AVAILABLE:
        return None, None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage"])
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
                locale="ko-KR"
            )
            page = ctx.new_page()
            try:
                page.goto("https://www.oliveyoung.co.kr/store/main/getBest.do",
                          wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
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
    out=[]; r=1
    for it in items:
        it["rank"]=r; out.append(it); r+=1
        if r>MAX_ITEMS: break
    return out

# ---------------- Google Drive (OAuth)
def build_drive_service_oauth():
    if not (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REFRESH_TOKEN):
        logging.warning("OAuth env 미설정")
        return None
    try:
        creds = UserCredentials(
            None, refresh_token=GOOGLE_REFRESH_TOKEN,
            client_id=GOOGLE_CLIENT_ID, client_secret=GOOGLE_CLIENT_SECRET,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=["https://www.googleapis.com/auth/drive.file"],
        )
        creds.refresh(GoogleRequest())
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        logging.exception("Drive service 생성 실패: %s", e)
        return None

def upload_csv_to_drive(service, csv_bytes, filename, folder_id=None):
    if not service: return None
    try:
        media = MediaIoBaseUpload(BytesIO(csv_bytes), mimetype="text/csv", resumable=False)
        body = {"name": filename}
        if folder_id: body["parents"]=[folder_id]
        f = service.files().create(body=body, media_body=media, fields="id,webViewLink,name").execute()
        logging.info("Uploaded to Drive: id=%s name=%s link=%s", f.get("id"), f.get("name"), f.get("webViewLink"))
        return f
    except Exception as e:
        logging.exception("Drive upload 실패: %s", e)
        return None

def find_csv_by_exact_name(service, folder_id: str, filename: str):
    try:
        q = f"name='{filename}' and mimeType='text/csv'"
        if folder_id:
            q += f" and '{folder_id}' in parents"
        res = service.files().list(q=q, pageSize=1, fields="files(id,name,createdTime)").execute()
        files = res.get("files", [])
        return files[0] if files else None
    except Exception as e:
        logging.exception("find_csv_by_exact_name error: %s", e)
        return None

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
        logging.exception("download_file_from_drive error: %s", e)
        return None

# ---------------- Slack
def send_slack_text(text: str) -> bool:
    if not SLACK_WEBHOOK:
        logging.warning("No SLACK_WEBHOOK configured.")
        return False
    try:
        res = requests.post(SLACK_WEBHOOK, json={"text": text}, timeout=10)
        return res.status_code // 100 == 2
    except Exception:
        return False

def build_slack_message_kor(
    date_str: str,
    today_items: List[Dict],
    prev_items: List[Dict],
    total_count: int
) -> str:
    """
    - TOP10: 배지(↑/↓/(-)/(new))
    - 🔥 급상승: |Δrank| >= 10, 최대 5개
    - 🆕 뉴랭커: 최대 5개
    - 📉 급하락: '하락 최대 5개' + 'OUT 최대 5개'를 한 섹션 안에 표시
    - ↔ 인&아웃: Top100 교체 수 (대칭차집합/2, goodsNo 키 기준)
    """
    # 전일 맵
    prev_rank_map: Dict[str, int] = {}
    prev_url_map:  Dict[str, str] = {}
    prev_name_map: Dict[str, str] = {}
    for p in (prev_items or []):
        k = _oy_key(p)
        if not k: continue
        try: prev_rank_map[k] = int(p.get("rank") or 0)
        except Exception: continue
        if p.get("url"):  prev_url_map[k]  = p["url"]
        if p.get("name") or p.get("raw_name"):
            prev_name_map[k] = p.get("name") or p.get("raw_name")

    # 오늘 맵
    today_key_rank: Dict[str, int] = {}
    today_key_url:  Dict[str, str] = {}
    today_key_name: Dict[str, str] = {}
    for t in (today_items or []):
        k = _oy_key(t)
        if not k: continue
        try: r = int(t.get("rank") or 0)
        except Exception: r = 0
        today_key_rank[k] = r
        today_key_url[k]  = t.get("url") or ""
        today_key_name[k] = t.get("name") or t.get("raw_name") or ""

    # TOP10
    top10_lines=[]
    for t in (today_items or [])[:10]:
        k=_oy_key(t); cur=int(t.get("rank") or 0)
        nm=_clean_text(t.get("name") or t.get("raw_name")); url=t.get("url")
        if k in prev_rank_map:
            prev=int(prev_rank_map.get(k) or 0)
            if prev>0:
                badge = f"(↑{prev-cur})" if cur<prev else f"(↓{cur-prev})" if cur>prev else "(-)"
            else: badge="(-)"
        else:
            badge="(new)"
        top10_lines.append(f"{cur}. {badge} {_link(nm, url)} — {fmt_price_with_discount(t.get('sale_price'), t.get('discount_pct'))}")

    if not prev_rank_map:
        header=f"*올리브영 데일리 전체 랭킹 100 (국내)* ({date_str})"
        return "\n".join([header,"","*TOP 10*",*(top10_lines or ["- 데이터 없음"])])

    today_keys=set(today_key_rank.keys())
    prev_keys=set(prev_rank_map.keys())
    common=today_keys & prev_keys

    # 🔥 급상승
    ups=[]
    for k in common:
        pr=int(prev_rank_map[k]); cr=int(today_key_rank[k]); diff=pr-cr
        if diff>=10: ups.append((diff,cr,pr,k))
    ups.sort(key=lambda x:(-x[0],x[1],x[2],x[3]))
    ups_lines=[f"- {_link(today_key_name.get(k,''), today_key_url.get(k))} {pr}위 → {cr}위 (↑{imp})"
               for imp,cr,pr,k in ups[:5]] or ["- 해당 없음"]

    # 🆕 뉴랭커
    newcomers=[]
    for k in today_keys - prev_keys:
        r=int(today_key_rank.get(k) or 0)
        if 1<=r<=100:
            newcomers.append((r, f"- {_link(today_key_name.get(k,''), today_key_url.get(k))} NEW → {r}위"))
    newcomers.sort(key=lambda x:x[0])
    newcomer_lines=[ln for _,ln in newcomers[:5]] or ["- 해당 없음"]

    # 📉 급하락 (하락 + OUT 각각 5개)
    # OUT
    out_cands=[]
    for k, pr in prev_rank_map.items():
        pr=int(pr)
        if 1<=pr<=100 and k not in today_keys:
            out_cands.append({
                "k":k, "prev":pr,
                "name": today_key_name.get(k) or prev_name_map.get(k,""),
                "url":  prev_url_map.get(k,"")
            })
    out_cands.sort(key=lambda x:x["prev"])
    out_lines=[f"- {_link(o['name'], o['url'])} {o['prev']}위 → OUT" for o in out_cands[:5]] or ["- OUT 해당 없음"]

    # 하락
    drop_cands=[]
    for k in common:
        pr=int(prev_rank_map[k]); cr=int(today_key_rank[k])
        diff=pr-cr
        if diff<=-10:
            drop_cands.append({"k":k,"prev":pr,"cur":cr,"drop":-diff,
                               "name":today_key_name.get(k,""),"url":today_key_url.get(k)})
    drop_cands.sort(key=lambda x:(-x["drop"], x["cur"], x["prev"], x["k"]))
    drop_lines=[f"- {_link(d['name'], d['url'])} {d['prev']}위 → {d['cur']}위 (↓{d['drop']})"
                for d in drop_cands[:5]] or ["- 하락 해당 없음"]

    # 인&아웃
    today_top_keys={k for k,r in today_key_rank.items() if 1<=r<=100}
    prev_top_keys ={k for k,r in prev_rank_map.items() if 1<=r<=100}
    inout_count=len(today_top_keys ^ prev_top_keys)//2

    # 메시지
    header=f"*올리브영 국내 Top 100* ({date_str})"
    lines=[
        header,"",
        "*TOP 10*",*(top10_lines or ["- 데이터 없음"]),
        "",
        "*🔥 급상승*",*ups_lines,
        "",
        "*🆕 뉴랭커*",*newcomer_lines,
        "",
        "*📉 급하락*",*drop_lines,*out_lines,
        "",
        "*↔ 랭크 인&아웃*",
        f"{inout_count}개의 제품이 인&아웃 되었습니다.",
    ]
    return "\n".join(lines)

# ---------------- 메인
def main() -> int:
    now=kst_now()
    today=now.date(); yday=(now - timedelta(days=1)).date()
    logging.info("Build: OY KR %s", today.isoformat())

    # 수집
    items,_ = try_http_candidates()
    if not items:
        logging.info("HTTP 실패 → Playwright 폴백")
        items,_ = try_playwright_render()
    if not items:
        send_slack_text("❌ 올리브영 국내 수집 실패")
        return 1
    items = fill_ranks_and_fix(items[:MAX_ITEMS])

    # CSV
    os.makedirs(OUT_DIR, exist_ok=True)
    fname_today=f"올리브영_랭킹_{today.isoformat()}.csv"
    header=["rank","brand","name","original_price","sale_price","discount_pct","url","raw_name"]
    def q(s):
        if s is None: return ""
        s=str(s).replace('"','""')
        return f'"{s}"' if any(c in s for c in [',','\n','"']) else s
    rows=[",".join(header)]
    for it in items:
        rows.append(",".join([
            q(it.get("rank")), q(it.get("brand")), q(it.get("name")),
            q(it.get("original_price") if it.get("original_price") is not None else ""),
            q(it.get("sale_price") if it.get("sale_price") is not None else ""),
            q(it.get("discount_pct") if it.get("discount_pct") is not None else ""),
            q(it.get("url")), q(it.get("raw_name")),
        ]))
    csv_bytes=("\n".join(rows)).encode("utf-8")
    with open(os.path.join(OUT_DIR, fname_today), "wb") as f:
        f.write(csv_bytes)

    # Drive 업로드
    service=build_drive_service_oauth()
    if service and GDRIVE_FOLDER_ID:
        upload_csv_to_drive(service, csv_bytes, fname_today, folder_id=GDRIVE_FOLDER_ID)

    # 전일 CSV 로드
    prev_items: List[Dict] = []
    if service and GDRIVE_FOLDER_ID:
        fname_yday=f"올리브영_랭킹_{yday.isoformat()}.csv"
        y_file=find_csv_by_exact_name(service, GDRIVE_FOLDER_ID, fname_yday)
        if not y_file:
            try:
                q=f"mimeType='text/csv' and name contains '올리브영_랭킹' and '{GDRIVE_FOLDER_ID}' in parents"
                r=service.files().list(q=q, orderBy="createdTime desc", pageSize=2,
                                       fields="files(id,name,createdTime)").execute()
                files=r.get("files", [])
                for fm in files:
                    if fm.get("name")!=fname_today:
                        y_file=fm; break
            except Exception as e:
                logging.exception("전일 파일 백업 검색 실패: %s", e)
        if y_file:
            txt=download_file_from_drive(service, y_file.get("id"))
            if txt:
                rdr=csv.DictReader(StringIO(txt))
                for r in rdr:
                    try:
                        prev_items.append({
                            "rank": int(r.get("rank") or 0),
                            "name": r.get("name"),
                            "raw_name": r.get("raw_name"),
                            "brand": r.get("brand"),
                            "url": r.get("url"),
                        })
                    except Exception:
                        continue

    # Slack
    text = build_slack_message_kor(
        date_str=now.strftime("%Y-%m-%d %H:%M KST"),
        today_items=items,
        prev_items=prev_items or [],
        total_count=len(items),
    )
    send_slack_text(text)
    logging.info("Done.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
