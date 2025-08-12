import os
import requests
import json
import datetime
import glob

def send_to_slack(data):
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("❌ SLACK_WEBHOOK_URL 환경변수가 설정되지 않았습니다.")
        return False
    
    today = datetime.date.today().isoformat()

    message = f"*📊 {today} 올리브영 랭킹 TOP10*\n"
    
    if isinstance(data, list) and len(data) > 0:
        for item in data[:10]:
            rank = item.get('rank', 'N/A')
            title = item.get('title', '제목 없음')
            price = item.get('price', '가격 정보 없음')
            link = item.get('link', '')
            
            if link:
                message += f"{rank}. <{link}|{title}> — {price}\n"
            else:
                message += f"{rank}. {title} — {price}\n"
    else:
        message += "수집된 데이터가 없습니다."

    payload = {"text": message}
    
    try:
        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        print("✅ Slack 메시지 전송 성공")
        return True
    except requests.exceptions.RequestException as e:
        print(f"❌ Slack 메시지 전송 실패: {e}")
        return False

def find_latest_ranking_file():
    """가장 최근의 랭킹 파일을 찾습니다."""
    pattern = "ranking_*.json"
    files = glob.glob(pattern)
    
    if not files:
        print("❌ 랭킹 파일을 찾을 수 없습니다.")
        return None
    
    # 파일명에서 날짜 추출하여 가장 최근 파일 찾기
    latest_file = max(files, key=lambda x: x.replace("ranking_", "").replace(".json", ""))
    print(f"📁 가장 최근 랭킹 파일: {latest_file}")
    return latest_file

if __name__ == "__main__":
    try:
        # 가장 최근 랭킹 파일 찾기
        ranking_file = find_latest_ranking_file()
        
        if not ranking_file:
            print("❌ 랭킹 파일이 없습니다. 먼저 main.py나 app.py를 실행하여 데이터를 수집하세요.")
            exit(1)
        
        # 파일 읽기
        try:
            with open(ranking_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            print(f"✅ {ranking_file}에서 {len(data)}개 상품 데이터 로드 완료")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"❌ 파일 읽기 오류: {e}")
            exit(1)
        
        # Slack으로 전송
        if send_to_slack(data):
            print("🎉 모든 작업이 완료되었습니다!")
        else:
            print("⚠️ Slack 전송에 실패했습니다.")
            
    except Exception as e:
        print(f"❌ 예상치 못한 오류: {e}")
        exit(1)
