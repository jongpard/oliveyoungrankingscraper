#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# app.py — GDrive(OAuth, 사용자 계정) 업로드 + 할인율/전일비 분석(한국시간) + Slack 포맷 개선

import os
import re
import json
import logging
from io import BytesIO, StringIO
from datetime import datetime, timedelta, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

...
def kst_now():
    return datetime.now(timezone.utc) + timedelta(hours=9)

def make_session():
    s = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)...ppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.oliveyoung.co.kr/",
    })
    return s

_won_pat = re.compile(r"[\d,]+")

def parse_won_to_int(s: str | None) -> int | None:
    if not s:
        return None
    m = _won_pat.search(s)
    if not m:
        return None
    try:
        return int(m.group(0).replace(",", ""))
    except Exception:
        return None

def fmt_price_with_discount(sale: int | None, disc_pct: int | None) -> str:
    if not sale:
        return ""
...
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
...
                except Exception:
                    data = None
                if isinstance(data, dict):
                    for k in ["BestProductList", "list", "rows", "items", "bestList", "result"]:
                        if k in data and isinstance(data[k], list) and data[k]:
                            out = []
                            for it in data[k][:MAX_ITEMS]:
                                name_val = it.get("prdNm") or it.get("prodName") or it.get("goodsNm") or it.get("name")
                                brand_val = it.get("brandNm") or it.get("brand")
                                url_val = it.get("goodsUrl") or it.get("prdUrl") or it.get("url")

                                sale_val = it.get("price") or it...et("salePrice") or it.get("onlinePrice") or it.get("finalPrice")
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
...
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
...
    up_sorted = sorted(movers, key=lambda x: x["change"], reverse=True)    # 상승 많을수록 먼저
    down_sorted = sorted(movers, key=lambda x: x["change"])                # 하락 많을수록 먼저

    # 차트인: 전일에 없었고 금일 top_window 이내
    chart_ins = [t for t in trends if t["prev_rank"] is None and t["rank"] <= top_window]

    # 랭크아웃: 전일 top_window 이내였고 금일 목록에 없음
    today_names = {t.get("name") or t.get("raw_name") for t in today_items}
    rank_out_names = [nm for nm in prev_top_names if nm not in today_names]
    # prev_items에서 해당 이름과 순위 가져오기
    rank_out = []
    for p in (prev_items or []):
        nm = p.get("name") or p.get("raw_name")
        if nm in rank_out_names:
            rank_out.append({"name": nm, "brand": p.get("brand"), "prev_rank": p.get("rank")})

    in_out_count = len(chart_ins) + len(rank_out)

    return up_sorted, down_sorted, chart_ins, rank_out, in_out_count


# ---------------- Slack 메시지(글로벌 규칙과 동일) ----------------
def _name_key(it: dict) -> str:
    return (it.get("name") or it.get("raw_name") or "").strip()

def _mk_link(name: str, url: str | None) -> str:
    return f"<{url}|{name}>" if url else name

def build_slack_message_global(today_items: list[dict], prev_items: list[dict], now_kst) -> str:
    """
    - TOP10: 전일 대비 (↑n)/(↓n)/(-)/(new) 배지
    - 🔥/📉: Top100 전체, 변동 10계단 이상, 각 5개
    - ❌ OUT: 전일 70위 이내만, 최대 5개 (전일 순 오름차순)
    - 🆕 뉴랭커: Top30 신규 진입, 최대 3개
    """
    # prev map
    prev_rank_map: dict[str, int] = {}
    for p in (prev_items or []):
        k = _name_key(p)
        if not k: 
            continue
        try:
            prev_rank_map[k] = int(p.get("rank") or 0)
        except Exception:
            continue

    # today url map
    today_url: dict[str, str] = {}
    for t in today_items:
        k = _name_key(t)
        if k and t.get("url"):
            today_url[k] = t["url"]

    # TOP10
    top10_lines: list[str] = []
    for it in today_items[:10]:
        cur = int(it.get("rank") or 0)
        k   = _name_key(it)
        prev= prev_rank_map.get(k)
        if prev is None: badge="(new)"
        elif prev>cur:   badge=f"(↑{prev-cur})"
        elif prev<cur:   badge=f"(↓{cur-prev})"
        else:            badge="(-)"
        price_txt = fmt_price_with_discount(it.get("sale_price"), it.get("discount_pct"))
        top10_lines.append(f"{cur}. {badge} {_mk_link(it.get('name') or '', it.get('url'))} — {price_txt}")

    # sets
    today_keys = {_name_key(x) for x in today_items if _name_key(x)}
    prev_keys  = set(prev_rank_map.keys())
    common     = today_keys & prev_keys

    # rising / falling
    rising=[]; falling=[]
    for it in today_items:
        k=_name_key(it)
        if k not in common: continue
        pr=int(prev_rank_map[k]); cr=int(it.get("rank") or 0)
        diff = pr - cr
        if diff>=10: rising.append((diff, cr, pr, k))
        elif diff<=-10: falling.append((-diff, cr, pr, k))
    rising.sort(key=lambda x:(-x[0], x[1], x[2], x[3]))
    falling.sort(key=lambda x:(-x[0], x[1], x[2], x[3]))
    rising_lines = [f"- {_mk_link(k, today_url.get(k))} {pr}위 → {cr}위 (↑{imp})" for imp,cr,pr,k in rising[:5]]
    falling_lines= [f"- {_mk_link(k, today_url.get(k))} {pr}위 → {cr}위 (↓{drop})" for drop,cr,pr,k in falling[:5]]

    # newcomers (Top30)
    newcomers=[]
    prev_top30 = {k for k,r in prev_rank_map.items() if r<=30}
    for it in today_items:
        k=_name_key(it)
        if k and k not in prev_keys and int(it.get('rank') or 0) <= 30:
            newcomers.append((int(it['rank']), f"- {_mk_link(k, it.get('url'))} NEW → {int(it['rank'])}위"))
    newcomers.sort(key=lambda x:x[0])
    newcomer_lines=[ln for _,ln in newcomers[:3]]

    # outs (prev <=70)
    outs=[]
    for k, r in sorted(prev_rank_map.items(), key=lambda kv: kv[1]):
        if r<=70 and k not in today_keys:
            outs.append((r, f"- {_mk_link(k, None)} {r}위 → OUT"))
    out_lines=[ln for _, ln in outs[:5]]

    inout_count = len(newcomer_lines) + len(out_lines)

    # build
    lines=[f"*올리브영 데일리 전체 랭킹 100 (국내)* ({now_kst.strftime('%Y-%m-%d %H:%M KST')})",
           "",
           "*TOP 10*"]
    lines += (top10_lines or ["- 데이터 없음"])
    lines += ["", "*🔥 급상승*"] + (rising_lines or ["- 해당 없음"])
    lines += ["", "*🆕 뉴랭커*"] + (newcomer_lines or ["- 해당 없음"])
    lines += ["", "*📉 급하락*"] + (falling_lines or ["- 해당 없음"])
    lines += (out_lines or [])
    lines += ["", "*↔ 랭크 인&아웃*", f"{inout_count}개의 제품이 인&아웃 되었습니다."]
    return "\n".join(lines)

# ---------------- Slack
def send_slack_text(text):
    if not SLACK_WEBHOOK:
        logging.warning("No SLACK_WEBHOOK configured.")
        return False
    try:
        res = requests.post(SLACK_WEBHOOK, json={"text": text}, timeout=10)
        return res.status_code // 100 == 2
    except Exception:
...
                for fmeta in files:
                    if fmeta.get("name") != fname_today:
                        y_file = fmeta
                        break
            except Exception as e:
                logging.exception("백업 검색 실패: %s", e)

        if y_file:
            prev_csv_text = download_file_from_drive(drive_service, y_file.get("id"))
            if prev_csv_text:
                prev_items = []
                try:
                    import csv
                    sio = StringIO(prev_csv_text)
                    rdr = csv.DictReader(sio)
                    for r in rdr:
                        try:
                            prev_items.append({
                                "rank": int(r.get("rank") or 0),
                                "name": r.get("name"),
                                "raw_name": r.get("raw_name"),
                                "brand": r.get("brand"),
                            })
                        except Exception:
                            continue
                except Exception as e:
                    logging.exception("CSV parse failed: %s", e)

    
    # 5) (글로벌 규칙) 슬랙 메시지 생성
    text = build_slack_message_global(items_filled, prev_items or [], now_kst)

    # 전송
    send_slack_text(text)

    logging.info("Done.")
    return 0


if __name__ == "__main__":
    exit(main())
