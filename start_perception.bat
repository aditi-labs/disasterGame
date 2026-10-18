@echo off
REM FloodShift Perception Service Startup Script
REM This script starts the camera perception pipeline with camera index 3
REM and connects it to the backend server.

echo =====================================================
echo    FloodShift Perception Service
echo =====================================================
echo.

REM Check if backend is running
echo Checking backend server...
curl -s http://localhost:8010/health >nul 2>&1
if errorlevel 1 (
    echo WARNING: Backend server not responding at http://localhost:8010
    echo Make sure to start the backend first with: uvicorn backend.main:app --port 8010
    echo.
    pause
)

echo Starting perception service with camera index 3...
echo.
echo Options:
echo   --source 3                    : Use camera index 3
echo   --observe-url                 : POST observations to backend
echo   --status-url                  : POST status updates to backend
echo   --classifier                  : Use Perceptron SDK for classification
echo.

python -m perception.service ^
    --source 3 ^
    --observe-url http://localhost:8010/perception/physical ^
    --status-url http://localhost:8010/perception/status ^
    --classifier perception.classifier:create_classifier

echo.
echo Perception service stopped.
pause
