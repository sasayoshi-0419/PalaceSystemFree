@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

"%PY%" -m pip install -e ".[package]"
if errorlevel 1 (
  "%PY%" "%~dp0packaging\build_windows_messages.py" pip-failed
  exit /b 1
)

if exist "dist\_pyi" (
  rmdir /s /q "dist\_pyi" 2>nul
)

"%PY%" -m PyInstaller packaging\home_server_admin.spec --noconfirm --distpath dist\_pyi --workpath build
if errorlevel 1 (
  "%PY%" "%~dp0packaging\build_windows_messages.py" pyinstaller-failed
  exit /b 1
)

"%PY%" "%~dp0packaging\prepare_windows_dist.py" dist
if errorlevel 1 (
  exit /b 1
)

if not exist "dist\HomeServerAdmin\HomeServerAdmin.exe" (
  "%PY%" "%~dp0packaging\build_windows_messages.py" exe-missing
  exit /b 1
)

"%PY%" "%~dp0packaging\build_windows_messages.py" ok
exit /b 0
