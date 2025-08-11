import os
import requests
import json
import datetime

def send_to_slack(data):
    webhook_url = os.environ["SLACK_WEBHOOK_URL"]
    today = datetime.date.today().isoformat()

    message = f"*📊 {today} 올리브영 랭킹 TOP10*\n"
    for item in data[:10]:
        message += f"{item['rank']}. <{item['link']}|{item['title']}> — {item['price']}\n"

    payload = {"text": message}
    requests.post(webhook_url, json=payload)

if __name__ == "__main__":
    today = datetime.date.today().isoformat()
    with open(f"ranking_{today}.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    send_to_slack(data)
