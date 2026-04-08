@echo off
REM Publish approved drafts to website, then process rejection feedback
REM to improve future drafts. Run daily in the afternoon via Task Scheduler.

set PROJECT_DIR=C:\Users\Topam\Documents\Mini-Projects\Github\green-context-engine
set PIPELINE_MODE=local
cd /d %PROJECT_DIR%
call venv\Scripts\activate.bat

if not exist "logs" mkdir logs
set TIMESTAMP=%date:~-4%%date:~4,2%%date:~7,2%_%time:~0,2%%time:~3,2%
set TIMESTAMP=%TIMESTAMP: =0%
set LOG=logs\publish_and_learn_%TIMESTAMP%.log

echo [%date% %time%] Starting publish and learn >> "%LOG%"

REM Step 1: Publish approved drafts to website
echo [%date% %time%] Publishing approved drafts... >> "%LOG%"
python scripts\publish_approved.py >> "%LOG%" 2>&1

REM Step 2: Process rejected drafts and extract writing rules from feedback
echo [%date% %time%] Processing rejection feedback... >> "%LOG%"
python scripts\process_feedback.py >> "%LOG%" 2>&1

echo [%date% %time%] Publish and learn complete >> "%LOG%"
