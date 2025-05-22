@echo off
setlocal enabledelayedexpansion

REM ============================================================================
REM FFmpeg Audio Stream Sender for Windows
REM Single stream, same window execution
REM ============================================================================

title FFmpeg Audio Sender

echo ============================================================================
echo                     FFMPEG AUDIO STREAM SENDER
echo ============================================================================

REM --- Configuration ---
set "MAC_IP=192.168.0.125"
set "AUDIO_DEV=CABLE Output (VB-Audio Virtual Cable)"
set "RTP_PORT=5004"
set "BITRATE=128k"
set "LOG_DIR=%~dp0logs"

REM Create logs directory
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set "LOG_FILE=%LOG_DIR%\audio_stream.log"

echo Configuration:
echo - Target Mac: %MAC_IP%:%RTP_PORT%
echo - Audio Device: %AUDIO_DEV%
echo - Bitrate: %BITRATE%
echo - Log File: %LOG_FILE%
echo ============================================================================
echo.

REM --- Check FFmpeg ---
echo [1/4] Checking FFmpeg installation...
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo ERROR: FFmpeg not found in PATH
    echo.
    echo Please install FFmpeg:
    echo 1. Download from https://ffmpeg.org/download.html
    echo 2. Extract and add bin folder to PATH
    echo 3. Or place ffmpeg.exe in this directory
    echo.
    pause
    exit /b 1
)

echo   FFmpeg found successfully
ffmpeg -version 2>nul | findstr "ffmpeg version" >nul && echo   Version check OK
echo.

REM --- Test Network ---
echo [2/4] Testing network connectivity...
ping -n 1 -w 3000 %MAC_IP% >nul 2>&1
if errorlevel 1 (
    echo   WARNING: Cannot reach %MAC_IP%
    echo   This is normal if Mac receiver is not started yet
) else (
    echo   Network connectivity OK
)
echo.

REM --- Check Audio Device ---
echo [3/4] Checking audio device...
echo   Scanning for: %AUDIO_DEV%

ffmpeg -f dshow -list_devices true -i dummy 2>&1 | findstr /C:"%AUDIO_DEV%" >nul 2>&1
if errorlevel 1 (
    echo   ERROR: Audio device not found
    echo.
    echo   Available audio devices:
    ffmpeg -f dshow -list_devices true -i dummy 2>&1 | findstr /C:"[dshow" | findstr "audio"
    echo.
    echo   Please update AUDIO_DEV variable with correct device name
    pause
    exit /b 1
) else (
    echo   Audio device found successfully
)
echo.

REM --- Start Stream ---
echo [4/4] Starting audio stream...
echo.

REM Initialize log file
echo [%DATE% %TIME%] Starting FFmpeg audio stream > "%LOG_FILE%"
echo Target: %MAC_IP%:%RTP_PORT% >> "%LOG_FILE%"
echo Device: %AUDIO_DEV% >> "%LOG_FILE%"
echo Bitrate: %BITRATE% >> "%LOG_FILE%"
echo. >> "%LOG_FILE%"

echo Stream Details:
echo - Codec: Opus (low latency)
echo - Sample Rate: 48kHz
echo - Channels: Stereo
echo - Bitrate: %BITRATE%
echo - Frame Duration: 20ms
echo - Packet Loss Tolerance: 5%%
echo.

echo ============================================================================
echo                          STARTING STREAM
echo ============================================================================
echo.
echo FFmpeg will now start streaming audio from:
echo   "%AUDIO_DEV%"
echo To Mac at:
echo   %MAC_IP%:%RTP_PORT%
echo.
echo Press Ctrl+C to stop the stream
echo.
echo ============================================================================
echo.

REM Change window title to show streaming status
title Audio Streaming to %MAC_IP%:%RTP_PORT% - Press Ctrl+C to stop

REM Start FFmpeg in the same window (this will take over the console)
ffmpeg -hide_banner -f dshow -i audio="%AUDIO_DEV%" ^
-acodec libopus ^
-ar 48000 -ac 2 ^
-b:a %BITRATE% ^
-application lowdelay ^
-frame_duration 20 ^
-packet_loss 5 ^
-fflags nobuffer -flags low_delay ^
-max_delay 0 ^
-flush_packets 1 ^
-f rtp "rtp://%MAC_IP%:%RTP_PORT%" 2>>"%LOG_FILE%"

REM This will only execute if FFmpeg exits (stopped or error)
echo.
echo ============================================================================
echo                          STREAM ENDED
echo ============================================================================
echo.
echo FFmpeg has stopped. Possible reasons:
echo - User pressed Ctrl+C (normal exit)
echo - Network connection lost
echo - Audio device became unavailable
echo - FFmpeg encountered an error
echo.
echo Check the log file for details: %LOG_FILE%
echo.

REM Show last few lines of log
echo Recent log entries:
echo -------------------
if exist "%LOG_FILE%" (
    powershell "Get-Content '%LOG_FILE%' | Select-Object -Last 10"
) else (
    echo No log file found
)

echo.
echo Press any key to exit...
pause >nul

endlocal