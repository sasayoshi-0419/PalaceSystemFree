@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m palworld_admin setup %*
) else (
  python -m palworld_admin setup %*
)
pause
