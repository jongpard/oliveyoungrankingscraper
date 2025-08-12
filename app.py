#!/usr/bin/env python3
# app.py
# OliveYoung total ranking scraper
# Strategy: try lightweight HTTP endpoints -> fallback to Playwright render -> save JSON -> send Slack

import os
import sys
import time
import json
import logging
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

# Slack webhook (set as repo secret SLACK_WEBHOOK_URL)
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
OUT_DIR = "rankings"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)

def make_session():
    s = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[429,500,502,503,504])
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.mount("http://", HTTPAdapter(max_retries=retries))
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.oliveyoung.co.kr/",
    })
    return s

def parse_html_products(html):
    """Try multiple selectors to find product blocks and extract normalized dicts."""
    soup = BeautifulSoup(html, "html.parser")
    candidate_selectors = [
        "ul.cate_prd_list li",
        ".cate_prd_list li",
        ".prd_info",
        ".prd_box",
        "ul.prd_list li",
        ".ranking_list li",
        ".rank_item",
    ]
    for sel in candidate_selectors:
        els = soup.select(sel)
        if not els:
            continue
        results = []
        for idx, el in enumerate(els, start=1):
            # name
            name = None
            for name_sel in [".tx_name", ".prd_name .tx_name", ".prd_name", "a"]:
                node = el.select_one(name_sel)
                if node and node.get_text(strip=True):
                    name = node.get_text(strip=True)
                    break
            if not name:
                continue
            brand_node = el.select_one(".tx_brand")
            price_node = el.select_one(".tx_cur .tx_num") or el.select_one(".tx_cur") or el.select_one(".prd_price .tx_num") or el.select_one(".prd_price")
            link_node = el.select_one("a")
            href = link_node.get("href") if link_node else None
            if href and href.startswith("/"):
                href = "https://www.oliveyoung.co.kr" + href
            results.append({
                "rank": idx,
                "name": name,
                "brand": brand_node.get_text(strip=True) if brand_node else "",
                "price": price_node.get_text(strip=True) if price_node else "",
                "url": href
            })
        if results:
            logging.info("parse_html_products: found %d items using selector '%s'", len(results), sel)
            return results
    return []

def try_http_candidates():
    """Try a series of lightweight HTTP endpoints (HTML or JSON) and parse."""
    session = make_session()
    candidates = [
        # primary: getBestList.do (HTML fragment)
        ("getBestList_default", "https://www.oliveyoung.co.kr/store/main/getBestList.do", {"rowsPerPage":"100","pageIdx":"0"}),
        # try with a common dispCatNo for total (some blogs use similar identifiers)
        ("getBestList_disp_total", "https://www.oliveyoung.co.kr/store/main/getBestList.do", {"dispCatNo":"90000010001","rowsPerPage":"100","pageIdx":"0"}),
        # alternative endpoints historically used
        ("getTopSellerList", "https://www.oliveyoung.co.kr/store/main/getTopSellerList.do", {"rowsPerPage":"100","pageIdx":"0"}),
    ]
    for name, url, params in candidates:
        try:
            logging.info("HTTP try: %s %s %s", name, url, params)
            r = session.get(url, params=params, timeout=15, allow_redirects=True)
            logging.info(" -> status=%s, final_url=%s, content-type=%s, length=%d", r.status_code, r.url, r.headers.get("Content-Type"), len(r.text or ""))
            if r.status_code != 200:
                continue
            ct = r.headers.get("Content-Type","")
            text_head = (r.text or "")[:800]
            # If JSON-like
            if "application/json" in ct or (r.text.strip().startswith("{") or r.text.strip().startswith("[")):
                try:
                    data = r.json()
                except Exception:
                    logging.warning("Response appears JSON but json() failed; skipping JSON parse.")
                    data = None
                if isinstance(data, dict):
                    # heuristics: look for common keys that contain arrays
                    list_keys = ["BestProductList","items","list","result","rows","data","bestList"]
                    for k in list_keys:
                        if k in data and isinstance(data[k], list) and data[k]:
                            arr = data[k]
                            out = []
                            for idx, it in enumerate(arr, start=1):
                                name_val = it.get("prdNm") or it.get("prodName") or it.get("goodsNm") or it.get("name") or it.get("itemName")
                                price_val = it.get("price") or it.get("salePrice") or it.get("onlinePrice") or it.get("priceAmt")
                                brand_val = it.get("brandNm") or it.get("brand")
                                url_val = it.get("goodsUrl") or it.get("prdUrl") or it.get("url")
                                if url_val and isinstance(url_val, str) and url_val.startswith("/"):
                                    url_val = "https://www.oliveyoung.co.kr" + url_val
                                out.append({"rank": idx, "name": name_val, "brand": brand_val, "price": str(price_val), "url": url_val})
                            if out:
                                logging.info("HTTP JSON parse succeeded via key '%s' (%d items)", k, len(out))
                                return out, text_head
                # if JSON present but not in expected shape, continue to next candidate
            # else HTML — try parse
            items = parse_html_products(r.text)
            if items:
                return items, text_head
        except Exception as e:
            logging.exception("HTTP candidate failed: %s %s", url, e)
    return None, None

def try_playwright_render(url="https://www.oliveyoung.co.kr/store/main/getBestList.do"):
    """Fallback: render with Playwright (headless Chromium) and parse produced HTML."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        logging.warning("Playwright not available (import failed): %s", e)
        return None, None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage","--disable-gpu"])
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
                locale="ko-KR",
                timezone_id="Asia/Seoul"
            )
            page = context.new_page()
            logging.info("Playwright: navigating to %s", url)
            page.goto(url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(2500)
            html = page.content()
            items = parse_html_products(html)
            browser.close()
            if items:
                logging.info("Playwright render succeeded, found %d items", len(items))
                return items, html[:800]
            else:
                logging.warning("Playwright render did not find products (page rendered).")
                return None, html[:800]
    except Exception as e:
        logging.exception("Playwright render exception: %s", e)
        return None, None

def save_json(items):
    os.makedirs(OUT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = os.path.join(OUT_DIR, f"ranking_{ts}.json")
    with open(fname, "w", encoding="utf-8") as f:
        json.dump({"scraped_at": datetime.now().isoformat(), "items": items}, f, ensure_ascii=False, indent=2)
    return fname

def send_slack(message):
    if not SLACK_WEBHOOK:
        logging.warning("SLACK_WEBHOOK_URL not configured. Skipping Slack.")
        return False
    try:
        res = requests.post(SLACK_WEBHOOK, json={"text": message}, timeout=10)
        if res.status_code // 100 == 2:
            logging.info("Slack message sent.")
            return True
        else:
            logging.warning("Slack returned %s: %s", res.status_code, res.text[:200])
            return False
    except Exception as e:
        logging.exception("Slack send error: %s", e)
        return False

def main():
    logging.info("🔍 OliveYoung total ranking scraper start")
    items, sample_head = try_http_candidates()
    if not items:
        logging.info("HTTP attempts failed -> falling back to Playwright render")
        items, sample_head = try_playwright_render()
    if not items:
        logging.error("❌ Scraping failed. No product list found.")
        body = sample_head or "no response"
        short = (body[:1000] + "...") if len(body) > 1000 else body
        send_slack(f"❌ OliveYoung scraping failed. Could not find product list.\nSample head:\n{short}")
        sys.exit(1)

    # Save
    fname = save_json(items)
    # Slack top10
    topn = items[:10]
    lines = [f"📊 OliveYoung Total Ranking ({datetime.now().strftime('%Y-%m-%d')})"]
    for it in topn:
        name = it.get("name","").strip()
        price = it.get("price","")
        url = it.get("url","")
        if url:
            lines.append(f"{it.get('rank')}. <{url}|{name}> — {price}")
        else:
            lines.append(f"{it.get('rank')}. {name} — {price}")
    send_slack("\n".join(lines))
    logging.info("✅ Success. Saved to %s", fname)

if __name__ == "__main__":
    main()
