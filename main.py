from scraper import scrape
from notifier import send_slack_message

if __name__ == "__main__":
    try:
        data = scrape()
        if data:
            message = "📊 올리브영 랭킹 TOP 10\n\n"
            for i, item in enumerate(data, 1):
                message += f"{i}. {item['title']} - {item['price']}\n"
        else:
            message = "❗️랭킹 데이터를 가져오지 못했습니다."
        send_slack_message(message)
    except Exception as e:
        send_slack_message(f"🚨 오류 발생: {e}")
