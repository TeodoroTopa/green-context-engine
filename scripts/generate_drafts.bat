@echo off
REM Generate one energy brief per news source for review in Notion.
REM Run daily in the morning via Windows Task Scheduler.

set PROJECT_DIR=C:\Users\Topam\Documents\Mini-Projects\Github\green-context-engine
set PIPELINE_MODE=local
cd /d %PROJECT_DIR%
call venv\Scripts\activate.bat

if not exist "logs" mkdir logs
set TIMESTAMP=%date:~-4%%date:~4,2%%date:~7,2%_%time:~0,2%%time:~3,2%
set TIMESTAMP=%TIMESTAMP: =0%
set LOG=logs\generate_drafts_%TIMESTAMP%.log

echo [%date% %time%] Starting draft generation >> "%LOG%"
for %%s in (mongabay carbonbrief pvmagazine cleantechnica electrek) do (
    echo [%date% %time%] Processing %%s... >> "%LOG%"
    python scripts\run_pipeline.py --source %%s --max-stories 1 >> "%LOG%" 2>&1
)
echo [%date% %time%] Draft generation complete >> "%LOG%"
