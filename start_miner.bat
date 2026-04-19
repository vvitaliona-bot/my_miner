@echo off
cd /d %~dp0
echo Запуск майнера...
xmrig.exe --config=config.json
pause
