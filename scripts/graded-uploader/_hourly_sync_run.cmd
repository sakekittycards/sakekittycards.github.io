@echo off
REM Sake Kitty hourly SITE reprice (graded + singles) — LIVE.
REM Graded: newest Sake CardLadder export -> Square (market x1.03), reprice+remove-sold, never add.
REM Singles: newest TCGplayer MyPricing export by SKU -> Square (market x1.03), price-only.
REM Sealed has its own task (SakeKitty-SealedReprice).
cd /d "C:\Users\lunar\OneDrive\Desktop\sake-kitty-cards-site\scripts\graded-uploader"
set SK_SYNC_LIVE=1
"C:\Python314\python.exe" _hourly_sync.py >> _hourly_sync_cron.out 2>&1
