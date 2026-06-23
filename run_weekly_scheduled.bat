@echo off
rem Used by the Windows scheduled task (Monday 07:00). Runs quietly, logs to logs\weekly.log,
rem and does NOT pop open a browser. The desktop "Latest Report" shortcut shows the result.
cd /d "C:\Users\ranvi\stock"
set PYTHONUTF8=1
if not exist "logs" mkdir "logs"
echo ==== run %DATE% %TIME% ==== >> "logs\weekly.log"
".venv\Scripts\python.exe" scripts\weekly_run.py noopen snapshot >> "logs\weekly.log" 2>&1
