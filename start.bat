@echo off
cd /d "%~dp0"
start "" pythonw watch.py
echo 입고 감시를 백그라운드로 시작했습니다. 로그: watch.log
