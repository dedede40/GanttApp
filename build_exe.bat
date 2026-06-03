@echo off
REM Build GanttApp.exe with PyInstaller (run on Windows)
REM Requirements: pip install pyinstaller

echo [1/2] Installing PyInstaller if missing...
pip install pyinstaller --quiet

echo [2/2] Building EXE...
pyinstaller GanttApp.spec --clean

echo.
echo Done. Output: dist\GanttApp\GanttApp.exe
echo Copy the dist\GanttApp\ folder (contains GanttApp.exe + data/) and create an empty save\ folder next to it.
pause
