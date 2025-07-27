name: Run OliveYoung Scraper

on:
  schedule:
    - cron: "0 23 * * *"  # 매일 자정 직전 UTC 기준 실행 (한국 기준 오전 8시)
  workflow_dispatch:     # 수동 실행 버튼 추가

jobs:
  scrape:
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

      - name: Run scraper and analysis
        env:
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
        run: python app.py

      - name: Commit and push if data changed
        run: |
          git config --global user.name 'GitHub Actions Bot'
          git config --global user.email 'actions@github.com'
          git add data/
          # 변경 사항이 있을 때만 커밋하고 푸시합니다.
          if ! git diff --staged --quiet; then
            git commit -m "📊 Update rankings data for $(date +'%Y-%m-%d')"
            git push
          else
            echo "No changes in ranking data."
          fi
