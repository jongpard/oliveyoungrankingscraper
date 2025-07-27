# main.py

from scraper import scrape_oliveyoung
from notifier import send_slack_message

if __name__ == "__main__":
    print("🔍 랭킹 데이터 수집 시작")
    try:
        rankings = scrape_oliveyoung()
        print(f"✅ 가져온 제품 수: {len(rankings)}")

        if rankings:
            message = "📊 올리브영 랭킹 TOP 10\n\n"
            for i, item in enumerate(rankings[:10], start=1):
                message += f"{i}. {item['title']} - {item['price']}\n"
        else:
            message = "❗️랭킹 데이터를 가져오지 못했습니다."

        print("📤 슬랙 전송 시작")
        send_slack_message(message)
        print("✅ 슬랙 전송 완료")

    except Exception as e:
        print(f"🚨 에러 발생: {e}")
