# main.py
from scraper import scrape
from notifier import send_slack_message

if __name__ == "__main__":
    print("🔍 랭킹 수집 시작")
    try:
        rankings = scrape()
        print(f"✅ 수집된 랭킹: {len(rankings)}")

        if rankings:
            message = "📊 올리브영 랭킹 TOP 10\n\n"
            for i, item in enumerate(rankings, start=1):
                message += f"{i}. {item['title']} - {item['price']}\n"
        else:
            message = "❗️랭킹 데이터를 불러오지 못했습니다."

        send_slack_message(message)
    except Exception as e:
        print(f"🚨 에러: {e}")
