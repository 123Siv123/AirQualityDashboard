@echo off
cd /d "%~dp0"
echo ============================================
echo   AQ Monitor - Starting from THIS folder:
echo   %CD%
echo ============================================
echo.
echo Stopping any old Flask on port 5000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5000" ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 2 /nobreak >nul
echo.
echo Starting Flask from this folder only...
start "AQ Monitor Flask" /MIN cmd /c "cd /d "%~dp0" && python app.py"
timeout /t 4 /nobreak >nul
echo.
echo Checking server build...
powershell -NoProfile -Command "try { $j = Invoke-RestMethod 'http://127.0.0.1:5000/api/build'; Write-Host ('  dashboard_tag: ' + $j.dashboard_tag); Write-Host ('  root: ' + $j.root) } catch { Write-Host '  ERROR: Flask not running yet - wait and open dashboard' }"
echo.
echo Open in browser (hard refresh Ctrl+Shift+R):
echo   http://127.0.0.1:5000/dashboard
echo   http://127.0.0.1:5000/analytics
echo.
echo Dashboard bottom-right: Build v13
echo Analytics bottom-right: Analytics Grid v4 - 60%% left
echo If wrong tags, close ALL python windows and run this bat again.
echo.
pause
