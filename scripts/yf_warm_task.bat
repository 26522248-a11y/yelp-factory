@echo off
cd /d C:\Users\Administrator\.paseo\hihicuti
set PYTHONIOENCODING=utf-8
echo [%date% %time%] warming pass>> data\warming_task.log
.venv\Scripts\yf.exe schedule --once --limit 4 --minutes 6 >> data\warming_task.log 2>&1
