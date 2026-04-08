@echo off
REM Energy Context Engine — scheduled local run
REM Set up in Windows Task Scheduler to run daily.
REM All Claude calls route through claude CLI (no API billing).

set PROJECT_DIR=C:\Users\Topam\Documents\Claude-Sandboxes\Green-Context-Engine-Sandbox\green-context-engine
set LOG_DIR=%PROJECT_DIR%\logs
set PIPELINE_MODE=local

cd /d %PROJECT_DIR%
call venv\Scripts\activate.bat

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

set TIMESTAMP=%date:~-4%%date:~4,2%%date:~7,2%_%time:~0,2%%time:~3,2%
set TIMESTAMP=%TIMESTAMP: =0%
set LOG_FILE=%LOG_DIR%\run_%TIMESTAMP%.log

echo [%date% %time%] Starting scheduled pipeline run >> "%LOG_FILE%"

REM Step 1: Run the pipeline (find stories, enrich, draft)
echo [%date% %time%] Running pipeline... >> "%LOG_FILE%"
python scripts\run_pipeline.py --source mongabay --max-stories 3 >> "%LOG_FILE%" 2>&1

REM Step 2: Publish any approved drafts from Notion
echo [%date% %time%] Checking for approved drafts... >> "%LOG_FILE%"
python scripts\publish_approved.py >> "%LOG_FILE%" 2>&1

echo [%date% %time%] Scheduled run complete >> "%LOG_FILE%"
