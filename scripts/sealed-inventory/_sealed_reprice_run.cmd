@echo off
REM Sake Kitty — hourly sealed reprice from tcgsearch (Windows Task Scheduler).
cd /d "C:\Users\lunar\OneDrive\Desktop\sake-kitty-cards-site\scripts\sealed-inventory"
"C:\Python314\python.exe" _sealed_reprice.py >> _sealed_reprice_cron.out 2>&1
