#!/usr/bin/env python3
"""
올리브영 스크래퍼 테스트 스크립트
"""

import os
import sys
import subprocess
import json
from datetime import datetime

def test_main_scraper():
    """main.py 테스트"""
    print("🧪 main.py 테스트 시작...")
    try:
        result = subprocess.run(
            ["python", "main.py"], 
            capture_output=True, 
            text=True, 
            cwd="/workspace",
            env={"PATH": "/workspace/venv/bin:" + os.environ.get("PATH", "")}
        )
        
        if result.returncode == 0:
            print("✅ main.py 테스트 성공")
            print("출력:", result.stdout)
            return True
        else:
            print("❌ main.py 테스트 실패")
            print("오류:", result.stderr)
            return False
    except Exception as e:
        print(f"❌ main.py 테스트 중 예외 발생: {e}")
        return False

def test_app_scraper():
    """app.py 테스트"""
    print("\n🧪 app.py 테스트 시작...")
    try:
        result = subprocess.run(
            ["python", "app.py"], 
            capture_output=True, 
            text=True, 
            cwd="/workspace",
            env={"PATH": "/workspace/venv/bin:" + os.environ.get("PATH", "")}
        )
        
        if result.returncode == 0:
            print("✅ app.py 테스트 성공")
            print("출력:", result.stdout)
            return True
        else:
            print("❌ app.py 테스트 실패")
            print("오류:", result.stderr)
            return False
    except Exception as e:
        print(f"❌ app.py 테스트 중 예외 발생: {e}")
        return False

def test_slack_sender():
    """slack.py 테스트"""
    print("\n🧪 slack.py 테스트 시작...")
    
    # 먼저 랭킹 파일이 있는지 확인
    ranking_files = [f for f in os.listdir(".") if f.startswith("ranking_") and f.endswith(".json")]
    
    if not ranking_files:
        print("⚠️ 랭킹 파일이 없습니다. 먼저 스크래퍼를 실행하세요.")
        return False
    
    try:
        result = subprocess.run(
            ["python", "slack.py"], 
            capture_output=True, 
            text=True, 
            cwd="/workspace",
            env={"PATH": "/workspace/venv/bin:" + os.environ.get("PATH", "")}
        )
        
        if result.returncode == 0:
            print("✅ slack.py 테스트 성공")
            print("출력:", result.stdout)
            return True
        else:
            print("❌ slack.py 테스트 실패")
            print("오류:", result.stderr)
            return False
    except Exception as e:
        print(f"❌ slack.py 테스트 중 예외 발생: {e}")
        return False

def check_files():
    """생성된 파일들 확인"""
    print("\n📁 생성된 파일들 확인...")
    
    files = os.listdir(".")
    ranking_files = [f for f in files if f.startswith("ranking_") and f.endswith(".json")]
    csv_files = [f for f in files if f.startswith("oliveyoung_") and f.endswith(".csv")]
    
    print(f"📊 랭킹 JSON 파일: {len(ranking_files)}개")
    for f in ranking_files:
        print(f"  - {f}")
    
    print(f"📋 CSV 파일: {len(csv_files)}개")
    for f in csv_files:
        print(f"  - {f}")
    
    return len(ranking_files) > 0

def main():
    """메인 테스트 함수"""
    print("🚀 올리브영 스크래퍼 통합 테스트 시작\n")
    
    # 가상환경 활성화 확인
    if not os.path.exists("/workspace/venv"):
        print("❌ 가상환경이 설정되지 않았습니다.")
        return False
    
    # 테스트 실행
    main_success = test_main_scraper()
    app_success = test_app_scraper()
    
    # 파일 생성 확인
    files_exist = check_files()
    
    # Slack 테스트 (파일이 있을 때만)
    slack_success = False
    if files_exist:
        slack_success = test_slack_sender()
    else:
        print("\n⚠️ Slack 테스트를 건너뜁니다 (랭킹 파일이 없음)")
    
    # 결과 요약
    print("\n" + "="*50)
    print("📊 테스트 결과 요약")
    print("="*50)
    print(f"✅ main.py: {'성공' if main_success else '실패'}")
    print(f"✅ app.py: {'성공' if app_success else '실패'}")
    print(f"✅ 파일 생성: {'성공' if files_exist else '실패'}")
    print(f"✅ slack.py: {'성공' if slack_success else '실패'}")
    
    if main_success and app_success and files_exist:
        print("\n🎉 모든 테스트가 성공했습니다!")
        return True
    else:
        print("\n⚠️ 일부 테스트가 실패했습니다.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)