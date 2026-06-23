@echo off
title Asymmetric Allocator - weekly run
cd /d "C:\Users\ranvi\stock"
set PYTHONUTF8=1
echo.
echo  Asymmetric Allocator - refreshing data and building this week's book.
echo  This takes a few minutes (it re-pulls ~500 prices + macro). Please wait...
echo.
".venv\Scripts\python.exe" scripts\weekly_run.py
echo.
echo  Done. The report should have opened in your browser.
echo  (It is also saved at reports\latest.html)
echo.
pause
