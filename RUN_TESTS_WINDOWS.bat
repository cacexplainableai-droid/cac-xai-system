@echo off
cd /d "%~dp0"
call venv\Scripts\activate.bat
python -m unittest tests.test_system -v
pause
