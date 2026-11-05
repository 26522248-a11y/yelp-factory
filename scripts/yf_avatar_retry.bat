@echo off
cd /d C:\Users\Administrator\.paseo\hihicuti
set PYTHONIOENCODING=utf-8
echo [%date% %time%] avatar retry>> data\avatar_retry.log
.venv\Scripts\yf.exe avatar --missing --concurrency 1 >> data\avatar_retry.log 2>&1
