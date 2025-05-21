@echo off
setlocal

set MAC_IP=192.168.0.125
set SAMPLE_RATE=48000
set PERIOD_SIZE=128
set NETJACK_PORT=19000

echo Starting JACK server with NetJack sender...

REM Start JACK server with optimal low-latency settings
start /B jackd -R -P99 -d portaudio -r %SAMPLE_RATE% -p %PERIOD_SIZE% -n 2 -D -o 2

REM Wait for JACK to initialize
timeout /t 2

REM Connect to VB-Cable output
jack_connect system:capture_1 system:playback_1
jack_connect system:capture_2 system:playback_2

REM Start NetJack sender to Mac
jack_netsource -H %MAC_IP% -p %NETJACK_PORT% -q 0 -r %SAMPLE_RATE% -p %PERIOD_SIZE% -n 2 -o 2 -a 0

REM List connections to verify
jack_lsp -c

echo NetJack sender running. Press Ctrl+C to stop...
pause