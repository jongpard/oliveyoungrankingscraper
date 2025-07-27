name: Run OliveYoung Scraper

on:
  schedule:
    - cron: "0 0 * * *"  # 매일 자정 UTC 기준 실행 (한국 기준 오전 9시)
  workflow_dispatch:     # 수동 실행 버튼 추가

jobs:
  run:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.10"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run scraper
        env:
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
          SCRAPER_API_KEY: ${{ secrets.SCRAPER_API_KEY }}
        run: python app.py
