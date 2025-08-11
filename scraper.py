name: OliveYoung Ranking Scraper

on:
  schedule:
    - cron: "0 0 * * *"  # 매일 00:00 UTC (한국 09:00)
  workflow_dispatch:

jobs:
  scrape:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: "3.10"

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          playwright install

      - name: Run Scraper
        run: python main.py

      - name: Send to Slack
        env:
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
        run: python slack.py
