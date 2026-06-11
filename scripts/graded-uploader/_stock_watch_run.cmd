@echo off
REM Sake Kitty — 6-hourly TCGplayer stock watch (Windows Task Scheduler).
REM Verifies the top-50 raw singles on the website are still in stock on
REM TCGplayer (newest MyPricing CSV in Downloads); delists any that sold.
cd /d "C:\Users\lunar\OneDrive\Desktop\sake-kitty-cards-site\scripts\graded-uploader"
"C:\Python314\python.exe" _stock_watch.py >> _stock_watch_cron.out 2>&1
