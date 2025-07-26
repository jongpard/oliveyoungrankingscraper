from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
import json, os
from datetime import datetime

app = Flask(__name__)

# 환경 변수
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')
TOP_N = int(os.environ.get('TOP_N', 100))

categories = {
    "전체": "https://www.oliveyoung.co.kr/store/main/getBestCollection?topCategoryNo=100000&categoryDetailNo=200000"
}
HEADERS = {"User-Agent": "Mozilla/5.0"}

def scrape_category(url, top_n):
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')
    items = soup.select('.prd_list .prd_item')[:top_n]
    products = []
    for idx, item in enumerate(items, 1):
        title = item.select_one('.info_area .name').get_text(strip=True)
        price = item.select_one('.info_area .price').get_text(strip=True)
        link = item.select_one('a')['href']
        if link.startswith('/'):
            link = 'https://www.oliveyoung.co.kr' + link
        products.append({"rank": idx, "title": title, "price": price, "link": link})
    return products

def notify_slack(message):
    if not SLACK_WEBHOOK_URL:
        return
    requests.post(SLACK_WEBHOOK_URL, json={"text": message})

@app.route('/scrape', methods=['GET'])
def scrape_endpoint():
    today = datetime.now().strftime('%Y-%m-%d')
    data = {"date": today, "categories": {}}
    for name, url in categories.items():
        data['categories'][name] = scrape_category(url, TOP_N)

    os.makedirs('data', exist_ok=True)
    filename = f"data/ranking_{today}.json"
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Slack 메시지 간단 리포트
    top = data['categories']['전체'][:10]
    text = f":bar_chart: OliveYoung Top {len(top)} Ranking ({today})\n"
    for p in top:
        text += f"• {p['rank']}. {p['title']} ({p['price']})\n"

    notify_slack(text)
    return jsonify({"status": "ok", "file": filename})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
