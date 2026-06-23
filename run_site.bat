@echo off
title Asymmetric Allocator - live site
cd /d "C:\Users\ranvi\stock"
set PYTHONUTF8=1
echo.
echo  Starting the Asymmetric Allocator live site...
echo  It will open in your browser at http://127.0.0.1:8765
echo.
echo  KEEP THIS WINDOW OPEN while using the site. Close it (or Ctrl+C) to stop.
echo.
".venv\Scripts\python.exe" webapp.py
pause
