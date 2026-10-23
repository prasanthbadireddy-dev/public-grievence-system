@echo off
echo ============================================================
echo   AI-Powered Public Grievance Analysis System - Backend
echo ============================================================
echo.
echo Installing / checking dependencies...
pip install flask flask-cors --quiet
echo.
echo Starting Flask server on http://127.0.0.1:5000 ...
echo Press Ctrl+C to stop.
echo.
python app.py
pause
