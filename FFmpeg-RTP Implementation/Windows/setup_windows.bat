@echo off
echo Windows Audio Streaming Setup
echo =============================

echo Checking requirements...

REM Check FFmpeg
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo MISSING: FFmpeg
    echo Please download from: https://ffmpeg.org/download.html
    echo Add to PATH or place in this directory
) else (
    echo FOUND: FFmpeg
)

REM Check VB-Cable
ffmpeg -f dshow -list_devices true -i dummy 2>&1 | findstr /C:"VB-Audio Virtual Cable" >nul
if errorlevel 1 (
    echo MISSING: VB-Audio Virtual Cable
    echo Please download from: https://vb-audio.com/Cable/
) else (
    echo FOUND: VB-Audio Virtual Cable
)

echo.
echo Setup complete. Run start_audio_stream.bat to begin streaming.
pause