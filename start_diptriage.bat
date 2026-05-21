@echo off
cd /d "%~dp0"
echo Starting DipTriage...
start "DipTriage Server" cmd /k "uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-exclude .claude --reload-exclude *.log --reload-exclude data"
echo Waiting for server (up to 30 seconds)...
powershell -NoProfile -Command "$max=30;$i=0;while($i -lt $max){if(Test-NetConnection localhost -Port 8000 -InformationLevel Quiet -WarningAction SilentlyContinue){break};Start-Sleep -Seconds 1;$i++};if($i -eq $max){Write-Host 'Timeout: server did not start. Check the DipTriage Server window for errors.'}else{Write-Host 'Server ready.'}"
echo Opening browser...
start "" "http://localhost:8000/"
echo Done. You can close this window.
echo To stop the server, run stop_diptriage.bat
pause
