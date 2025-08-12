name: OliveYoung Daily (GDrive + Slack)

on:
  schedule:
    - cron: "1 5 * * *" # 매일 KST 14:01 (UTC 05:01)
  workflow_dispatch:

jobs:
  scrape-and-upload:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    concurrency:
      group: oy-daily
      cancel-in-progress: false

    # ✅ GitHub Secrets → ENV 매핑 (OAuth 전용)
    env:
      SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
      GDRIVE_FOLDER_ID:  ${{ secrets.GDRIVE_FOLDER_ID }}
      GOOGLE_CLIENT_ID:  ${{ secrets.GOOGLE_CLIENT_ID }}
      GOOGLE_CLIENT_SECRET: ${{ secrets.GOOGLE_CLIENT_SECRET }}
      GOOGLE_REFRESH_TOKEN: ${{ secrets.GOOGLE_REFRESH_TOKEN }}

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.10"
          cache: "pip"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt || true
          pip install requests beautifulsoup4 urllib3 playwright \
                      google-api-python-client google-auth google-auth-httplib2 google-auth-oauthlib
          python -m playwright install chromium

      # 🔎 시크릿 주입 확인(앱 실행 전 확인용)
      - name: Debug env presence
        run: |
          python - << 'PY'
          import os
          keys = [
            "GDRIVE_FOLDER_ID",
            "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET",
            "GOOGLE_REFRESH_TOKEN",
            "SLACK_WEBHOOK_URL"
          ]
          for k in keys:
              v = os.getenv(k)
              print(k, "=", "SET" if v else "MISSING", "| length =", (len(v) if v else 0))
          PY

      - name: Run app
        run: python app.py

      # 실패 시 디버깅 자료 보존
      - name: Upload debug artifacts on failure
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: oy-debug
          path: |
            rankings/**
            artifacts/**
          if-no-files-found: ignore
