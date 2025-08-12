# app.py
import os
import sys
import re
import base64
import json
import logging
from datetime import datetime, date
from pathlib import Path
from typing import List, Dict, Optional

import pandas as pd
from bs4 import BeautifulSoup

# Playwright sync API
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

# Google drive
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


# ---------- CONFIG ----------
TARGET_URL = "https://www.oliveyoung.co.kr/store/main/main.do"
LOCAL_BASE = Path("rankings")
TOP_N = 10
SCRAPE_TIMEOUT = 30 * 1000  # playwright timeout in ms
# ----------------------------


def ensure_dirs_for_date(d: date) -> Path:
    folder = LOCAL_BASE / d.isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def clean_title(title: str) -> str:
    if not title:
        return title
    # Remove leading bracketed tags like [푸디젠 PICK | 이벤트] possibly repeated
    cleaned = re.sub(r'^(?:\[[^\]]*\]\s*)+', '', title).strip()
    # collapse whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned


def extract_price(text: str) -> Optional[int]:
    if not text:
        return None
    # remove commas and non-digits, return int if found
    nums = re.sub(r'[^\d]', '', text)
    try:
        return int(nums) if nums else None
    except:
        return None


def try_parsers(html: str) -> List[Dict]:
    """
    Try several parsing heuristics. Return list of dict:
    { 'raw_rank': str|None, 'brand': str, 'product_name': str, 'price': int|None, 'url': str|None }
    """
    soup = BeautifulSoup(html, "lxml")
    results = []

    # Heuristic set 1: common product list items (Olive Young often uses li with class 'prd_item' or 'prd_lst')
    candidates = []
    selectors = [
        "ul.prd_lst li",              # common
        "ul.prdList li",             # alternative
        "div.goodsList li",          # alt
        "div.prd_item",              # alt
        "li.prod_item",              # alt
        "div.product_list div.item"  # generic
    ]
    for sel in selectors:
        found = soup.select(sel)
        if found and len(found) >= 5:
            candidates = found
            logger.info(f"Using selector '{sel}' with {len(found)} items")
            break

    # Heuristic set 2: search for anchors with product names
    if not candidates:
        # find patterns with product name-like text
        anchors = soup.select("a[href]")
        # heuristics: anchors that contain 'product' or long Korean names
        for a in anchors:
            t = (a.get_text() or "").strip()
            if len(t) > 8 and re.search(r'[가-힣]', t):
                # try parent li
                parent_li = a.find_parent("li")
                if parent_li:
                    candidates = [parent_li]
                    break

    if candidates:
        # parse each candidate element
        for idx, el in enumerate(candidates, start=1):
            try:
                # rank: look for explicit rank badge or number
                raw_rank = None
                rank_sel = el.select_one(".rank_num, .rank, .badge_rank")
                if rank_sel:
                    raw_rank = rank_sel.get_text(strip=True)
                else:
                    # sometimes rank is in text like "1위"
                    txt = el.get_text(" ", strip=True)
                    m = re.search(r'(\d+)\s*위', txt)
                    if m:
                        raw_rank = m.group(1)

                # brand: often in .brand or .maker or small tag
                brand = ""
                bsel = el.select_one(".brand, .prd_brand, .maker, .brand_name")
                if bsel:
                    brand = bsel.get_text(strip=True)
                else:
                    # sometimes brand is first part of product name (before space)
                    title_guess = el.get_text(" ", strip=True)
                    brand = title_guess.split()[0] if title_guess else ""

                # product name: in .prd_name, .name, .tit, a title attr
                name = ""
                nsel = el.select_one(".prd_name, .prod_name, .name, .prdTit, .tit")
                if nsel:
                    name = nsel.get_text(" ", strip=True)
                else:
                    # anchors
                    a = el.select_one("a")
                    if a:
                        name = a.get("title") or a.get_text(" ", strip=True)

                # price: .price .prc
                price = None
                psel = el.select_one(".price, .prc, .sell_price, .price_value")
                if psel:
                    price = extract_price(psel.get_text(" ", strip=True))
                else:
                    # fallback: search for '원' in text
                    t = el.get_text(" ", strip=True)
                    m = re.search(r'([\d,]+)\s*원', t)
                    if m:
                        price = extract_price(m.group(1))

                # url
                url = None
                a = el.select_one("a[href]")
                if a:
                    url = a.get("href")
                    # sometimes relative
                    if url and url.startswith("/"):
                        url = "https://www.oliveyoung.co.kr" + url

                cleaned_name = clean_title(name)
                results.append({
                    "raw_rank": raw_rank if raw_rank else None,
                    "brand": brand.strip(),
                    "product_name": cleaned_name,
                    "price": price,
                    "url": url
                })
            except Exception as e:
                logger.debug("Error parsing element", exc_info=e)
        # dedupe empty entries
        results = [r for r in results if r.get("product_name")]
        return results

    # Last resort: try to parse JSON-LD or scripts
    scripts = soup.find_all("script", {"type": "application/ld+json"})
    for s in scripts:
        try:
            j = json.loads(s.string)
            # if it's a product list
            if isinstance(j, dict) and "itemListElement" in j:
                for item in j["itemListElement"]:
                    name = item.get("name") or item.get("item", {}).get("name")
                    url = item.get("url") or item.get("item", {}).get("url")
                    results.append({
                        "raw_rank": None,
                        "brand": "",
                        "product_name": clean_title(name or ""),
                        "price": None,
                        "url": url
                    })
                return results
        except Exception:
            continue

    # nothing found
    return []


def scrape_rankings() -> List[Dict]:
    html = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page()
            page.goto(TARGET_URL, timeout=SCRAPE_TIMEOUT)
            # wait a little for dynamic content
            try:
                page.wait_for_timeout(1500)
            except Exception:
                pass
            html = page.content()
            browser.close()
    except PWTimeoutError as e:
        logger.error("Playwright timeout: %s", e)
    except Exception as e:
        logger.error("Playwright error: %s", e, exc_info=True)

    if not html:
        raise RuntimeError("Failed to fetch page content")

    parsed = try_parsers(html)
    if not parsed:
        logger.error("Could not find product list. Raw HTML head (first 500):\n%s", html[:500])
        raise RuntimeError("Could not find the product list. The page structure might have changed.")

    # ensure consistent ordering and assign computed_rank (sequential)
    final = []
    for i, item in enumerate(parsed, start=1):
        raw_rank = item.get("raw_rank")
        # if raw_rank contains non-digit (like '오특'), treat as None
        rank_note = None
        if raw_rank is None or not re.search(r'\d', str(raw_rank)):
            rank_note = "[오특]"
        # computed rank: use position order (this addresses "오특" gaps)
        computed_rank = i
        final.append({
            "computed_rank": computed_rank,
            "raw_rank": raw_rank,
            "rank_note": rank_note,
            "brand": item.get("brand", "").strip(),
            "product_name": item.get("product_name", "").strip(),
            "price": item.get("price"),
            "url": item.get("url")
        })
    return final


# ---------- Google Drive helpers ----------
def get_drive_service_from_env() -> Optional[object]:
    sa_b64 = os.environ.get("GDRIVE_SA_JSON_B64")
    folder_id = os.environ.get("GDRIVE_FOLDER_ID")
    if not sa_b64 or not folder_id:
        logger.warning("GDRIVE_SA_JSON_B64 or GDRIVE_FOLDER_ID not set. Skipping Drive upload.")
        return None
    try:
        sa_json = base64.b64decode(sa_b64).decode("utf-8")
        sa_info = json.loads(sa_json)
        creds = service_account.Credentials.from_service_account_info(sa_info, scopes=["https://www.googleapis.com/auth/drive"])
        service = build('drive', 'v3', credentials=creds, cache_discovery=False)
        return {"service": service, "folder_id": folder_id}
    except Exception as e:
        logger.error("Failed to init Google Drive client: %s", e, exc_info=True)
        return None


def upload_file_to_drive(drive_ctx, local_path: Path, mime_type: str = None) -> Optional[str]:
    """
    Uploads file and returns file id. If same-named file exists in folder, just upload new file (keeps history).
    """
    if not drive_ctx:
        return None
    service = drive_ctx["service"]
    folder_id = drive_ctx["folder_id"]
    fname = local_path.name
    media = MediaFileUpload(str(local_path), mimetype=mime_type or 'text/csv', resumable=True)
    body = {"name": fname, "parents": [folder_id]}
    try:
        created = service.files().create(body=body, media_body=media, fields="id, webViewLink").execute()
        fid = created.get("id")
        logger.info("Uploaded %s to Drive (id=%s)", local_path, fid)
        return fid
    except Exception as e:
        logger.error("Drive upload failed for %s: %s", local_path, e, exc_info=True)
        return None


# ---------- Trend analysis ----------
def load_previous_local_csv(today_folder: Path) -> Optional[pd.DataFrame]:
    # find previous folder in LOCAL_BASE
    all_folders = sorted([p for p in LOCAL_BASE.iterdir() if p.is_dir()])
    if not all_folders:
        return None
    # find folder before today's folder
    prev = None
    for p in all_folders:
        if p.name < today_folder.name:
            prev = p
    if prev is None:
        return None
    csvs = sorted(prev.glob("rankings_*.csv"), reverse=True)
    if not csvs:
        return None
    try:
        df = pd.read_csv(csvs[0], dtype=str)
        return df
    except Exception as e:
        logger.error("Failed to load previous CSV %s: %s", csvs[0], e)
        return None


def analyze_trends(today_df: pd.DataFrame, prev_df: Optional[pd.DataFrame]):
    """
    Compute rank changes by matching on product_name (cleaned).
    Return dicts: increases, decreases, new_entries, rank_out_50
    """
    # ensure types
    today = today_df.copy()
    today['product_key'] = today['product_name'].str.lower().str.replace(r'\s+', ' ', regex=True).str.strip()
    today['computed_rank'] = pd.to_numeric(today['computed_rank'], errors='coerce')

    if prev_df is None:
        return {"increases": [], "decreases": [], "new_entries": [], "dropped_from_top50": []}

    prev = prev_df.copy()
    prev['product_key'] = prev['product_name'].str.lower().str.replace(r'\s+', ' ', regex=True).str.strip()
    prev['computed_rank'] = pd.to_numeric(prev['computed_rank'], errors='coerce')

    # merge on product_key
    merged = pd.merge(today, prev[['product_key', 'computed_rank']], on='product_key', how='left', suffixes=('_today','_prev'))
    merged['computed_rank_prev'] = merged['computed_rank_prev'] = merged.get('computed_rank_prev', merged.get('computed_rank_prev'))  # noqa

    # If prev rank missing => new entry
    new_entries = merged[merged['computed_rank_prev'].isna()]

    # compute change where prev exists
    changes = merged[~merged['computed_rank_prev'].isna()].copy()
    changes['delta'] = changes['computed_rank_prev'].astype(int) - changes['computed_rank'].astype(int)
    # delta positive means moved up (e.g., 77 -> 26 delta = 51)
    increases = changes[changes['delta'] > 0].sort_values('delta', ascending=False).head(20)
    decreases = changes[changes['delta'] < 0].sort_values('delta')

    # find dropped from top50: items that existed in prev top50 but today their product_key not in today top50
    prev_top50 = prev[prev['computed_rank'] <= 50]
    today_keys = set(today['product_key'].tolist())
    dropped = []
    for _, row in prev_top50.iterrows():
        if row['product_key'] not in today_keys:
            dropped.append(row.to_dict())
        else:
            # if present but now >50
            trow = today[today['product_key'] == row['product_key']]
            if not trow.empty and int(trow.iloc[0]['computed_rank']) > 50:
                dropped.append(row.to_dict())

    # convert DataFrames to list of dicts for output
    def df_to_list(df):
        out = []
        for _, r in df.iterrows():
            out.append({
                "product_name": r['product_name'],
                "brand": r.get('brand', ''),
                "rank_today": int(r['computed_rank']),
                "rank_prev": int(r['computed_rank_prev']),
                "delta": int(r['delta'])
            })
        return out

    inc_list = df_to_list(increases)
    dec_list = []
    # decreases: delta negative (moved down) but present
    for _, r in decreases.iterrows():
        dec_list.append({
            "product_name": r['product_name'],
            "brand": r.get('brand', ''),
            "rank_today": int(r['computed_rank']),
            "rank_prev": int(r['computed_rank_prev']),
            "delta": int(r['delta'])
        })

    new_list = []
    for _, r in new_entries.iterrows():
        new_list.append({
            "product_name": r['product_name'],
            "brand": r.get('brand', ''),
            "rank_today": int(r['computed_rank']),
            "note": '[new]'
        })

    dropped_list = []
    for r in dropped:
        dropped_list.append({
            "product_name": r.get('product_name'),
            "brand": r.get('brand', ''),
            "prev_rank": int(r.get('computed_rank')) if r.get('computed_rank') else None
        })

    return {
        "increases": inc_list,
        "decreases": dec_list,
        "new_entries": new_list,
        "dropped_from_top50": dropped_list
    }


# ---------- Formatting outputs ----------
def format_top10(today_df: pd.DataFrame) -> str:
    lines = []
    header = f":bar_chart: 올리브영 전체 랭킹(국내) ({datetime.now().date().isoformat()})"
    lines.append(header)
    # top10 rows ordered by computed_rank
    top10 = today_df.sort_values('computed_rank').head(TOP_N)
    for _, r in top10.iterrows():
        # avoid duplicate brand printing: if product_name already starts with brand, don't repeat
        brand = (r['brand'] or "").strip()
        pname = r['product_name'].strip()
        price = r['price'] if not pd.isna(r['price']) else ""
        rank_note = r['rank_note'] if not pd.isna(r['rank_note']) and r['rank_note'] else ""
        # Check duplication: if pname starts with brand, only show once
        display_line = ""
        if brand and pname.startswith(brand):
            display_line = f"{int(r['computed_rank'])}. {pname} {rank_note} — {price}"
        elif brand:
            display_line = f"{int(r['computed_rank'])}. {brand} {pname} {rank_note} — {price}"
        else:
            display_line = f"{int(r['computed_rank'])}. {pname} {rank_note} — {price}"
        lines.append(display_line)
    return "\n".join(lines)


def format_trend_analysis(trends: Dict) -> str:
    lines = []
    lines.append("🔥 급상승 브랜드")
    for it in trends.get("increases", [])[:10]:
        # show: - 브랜드: prev → today (+delta)
        brand = it.get('brand') or ""
        name = it.get('product_name')
        lines.append(f"- {brand}: {it['rank_prev']} → {it['rank_today']} (+{it['delta']})")
        lines.append(f" ▶ {name}")
    lines.append("\n📉 급하락/랭크아웃")
    for it in trends.get("dropped_from_top50", [])[:20]:
        brand = it.get('brand') or ""
        name = it.get('product_name')
        prev = it.get('prev_rank')
        lines.append(f"- {brand}: {prev} → Rank Out/50+")
        lines.append(f" ▶ {name}")
    # newly appeared
    if trends.get("new_entries"):
        lines.append("\n🆕 새로 등장")
        for it in trends.get("new_entries", [])[:10]:
            lines.append(f"- {it.get('brand')}: 첫 등장 {it.get('rank_today')}")
            lines.append(f" ▶ {it.get('product_name')}")
    return "\n".join(lines)


# ---------- Main ----------
def main():
    logger.info("올리브영 랭킹 수집 시작")
    today = date.today()
    out_dir = ensure_dirs_for_date(today)
    try:
        scraped = scrape_rankings()
    except Exception as e:
        logger.exception("Scraping failed: %s", e)
        return

    # create DataFrame
    df = pd.DataFrame(scraped)
    if df.empty:
        logger.error("No items parsed.")
        return

    # normalize price -> keep as int or empty
    df['price'] = df['price'].apply(lambda x: int(x) if pd.notna(x) else "")
    # ensure types
    df['computed_rank'] = df['computed_rank'].astype(int)
    # Save CSV and JSON locally
    csv_path = out_dir / f"rankings_{today.isoformat()}.csv"
    json_path = out_dir / f"rankings_{today.isoformat()}.json"
    df.to_csv(csv_path, index=False)
    df.to_json(json_path, orient='records', force_ascii=False, indent=2)
    logger.info("Saved local CSV: %s", csv_path)

    # ensure top100 saved (if parsed more than 100 entries, trim; if fewer, still save)
    # If we have more items and want only top100, slice
    if len(df) > 100:
        df_top100 = df.sort_values('computed_rank').head(100)
    else:
        df_top100 = df.sort_values('computed_rank')
    top100_path = out_dir / f"rankings_top100_{today.isoformat()}.csv"
    df_top100.to_csv(top100_path, index=False)
    logger.info("Saved top100 CSV: %s", top100_path)

    # Load previous CSV for trend analysis
    prev_df = load_previous_local_csv(out_dir)
    trends = analyze_trends(df_top100, prev_df)

    # Format outputs
    top10_text = format_top10(df)
    trend_text = format_trend_analysis(trends)
    analysis_path = out_dir / f"analysis_{today.isoformat()}.txt"
    with open(analysis_path, "w", encoding="utf-8") as f:
        f.write(top10_text + "\n\n" + trend_text)
    logger.info("Saved analysis text: %s", analysis_path)

    # Upload files to Google Drive if configured
    drive_ctx = get_drive_service_from_env()
    if drive_ctx:
        upload_file_to_drive(drive_ctx, csv_path, mime_type='text/csv')
        upload_file_to_drive(drive_ctx, top100_path, mime_type='text/csv')
        upload_file_to_drive(drive_ctx, json_path, mime_type='application/json')
        upload_file_to_drive(drive_ctx, analysis_path, mime_type='text/plain')

    # Print summary to console (could be used by CI logs)
    logger.info("Top10:\n%s", top10_text)
    logger.info("Trend Analysis:\n%s", trend_text)

    logger.info("작업 완료.")


if __name__ == "__main__":
    main()
