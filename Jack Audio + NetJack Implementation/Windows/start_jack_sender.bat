@echo off
setlocal

REM Configuration
set MAC_IP=192.168.0.125
set SAMPLE_RATE=48000
set PERIOD_SIZE=64
set NETJACK_PORT=19000

set "JACK_DIR=C:\Program Files\JACK2"
set PATH=%PATH%;%JACK_DIR%;%JACK_DIR%\tools

REM Start JACK server (audio engine)
start "JACKD" /B jackd.exe -R -P99 -d portaudio -r %SAMPLE_RATE% -p %PERIOD_SIZE% -i 2 -o 0

timeout /t 5 /nobreak >nul

REM Start NetJack sender (streams audio to Mac)
start "NETJACK" /B jack_netsource.exe -H %MAC_IP% -p %NETJACK_PORT% -r %SAMPLE_RATE% -i 2 -n 2

timeout /t 5 /nobreak >nul

REM Connect Windows audio input to NetJack network ports
jack_connect.exe system:capture_1 netjack:capture_1
jack_connect.exe system:capture_2 netjack:capture_2

echo JACK sender active. Press any key to stop...
pause

REM Cleanup
taskkill /F /IM jackd.exe 2>nul
taskkill /F /IM jack_netsource.exe 2>nul