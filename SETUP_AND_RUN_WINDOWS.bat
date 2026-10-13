@echo off
title CAC Explainable AI System
cd /d "%~dp0"
echo ============================================================
echo  CAC Sierra Leone - Explainable AI System (first-time setup)
echo ============================================================
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Please install Python 3.10 or newer from python.org
  echo and tick "Add python.exe to PATH" during installation. Then run this file again.
  pause
  exit /b
)
if not exist venv (
  echo Creating the virtual environment ...
  python -m venv venv
)
call venv\Scripts\activate.bat
echo Installing the required packages (needs internet the first time) ...
python -m pip install --upgrade pip
pip install -r requirements.txt
echo.
echo Starting the system. Open your browser at  http://127.0.0.1:5000
echo Username: cac-explainable-ai      Password: explainable_aigrp
echo (Keep this window open. Press Ctrl+C to stop.)
python app.py
pause
