// filepath: /Users/reyneardouglas/WindowsToMacSpeaker/Jack Audio + NetJack Implementation/Windows/start_jack_sender.bat
@echo off
setlocal

REM --- Configuration ---
set MAC_IP=192.168.0.125
set SAMPLE_RATE=48000
set PERIOD_SIZE=128
set NUM_PERIODS=2
set NETJACK_PORT=19000

REM IMPORTANT: Set this to the exact name of your Windows audio device that you want to send FROM,
REM as JACK sees it. Use "jack_lsp -A" in a separate command prompt after jackd has started
REM to list available audio ports if you are unsure.
REM VB-Audio Cable is often "CABLE Output (VB-Audio Virtual Cable)" or similar.
set AUDIO_SOURCE_JACK_CAPTURE_PREFIX="CABLE Output (VB-Audio Virtual Cable)"

REM --- Set Path to JACK Installation ---
REM Adjust this path if JACK2 is installed in a different location.
set "JACK_INSTALL_DIR=C:\Program Files\JACK2"
if not exist "%JACK_INSTALL_DIR%\bin\jackd.exe" (
    set "JACK_INSTALL_DIR=C:\Program Files (x86)\JACK2"
    if not exist "%JACK_INSTALL_DIR%\jackd.exe" (
        echo ERROR: JACK2 executables not found in "%ProgramFiles%\JACK2" or "%ProgramFiles(x86)%\JACK2\bin".
        echo Please install JACK2 from https://jackaudio.org/downloads/
        echo or update the JACK_INSTALL_DIR variable in this script.
        pause
        exit /b 1
    )
)
echo Using JACK from: %JACK_INSTALL_DIR%
set PATH=%PATH%;%JACK_INSTALL_DIR%
set PATH=%PATH%;%JACK_INSTALL_DIR%\tools

echo Starting JACK server on Windows...
REM -R for real-time priority (if possible)
REM -P99 for high priority (Windows specific)
REM -d portaudio (default, can be changed to -d dsound or -d asio -D "Your ASIO Driver Name" for potentially lower latency)
REM -r sample rate
REM -p period size (buffer size for jackd)
REM -n number of periods
REM -D for duplex mode (input and output)
REM -o 2 for 2 output channels (stereo) - jackd needs to know its own output channels
REM -v for verbose output
start "JACKD_Server" /B jackd.exe -R -P99 -v -d portaudio -r %SAMPLE_RATE% -p %PERIOD_SIZE% -n %NUM_PERIODS% -D -o 2

echo Waiting for JACK server to initialize (5 seconds)...
timeout /t 5 /nobreak >nul

echo.
echo Listing available JACK ports (for reference):
jack_lsp.exe -A
echo.

echo Starting NetJack sender to Mac (%MAC_IP%)...
REM jack_netsource will create input ports like "NetJack/send_1", "NetJack/send_2"
REM -H target host IP
REM -p target host port (lowercase 'p' for port with jack_netsource)
REM -q quality (0=raw PCM, 1=opus) - Opus might add slight latency but save bandwidth. Raw PCM for lowest latency.
REM -r sample rate (must match jackd)
REM -P period size (uppercase 'P' for period with jack_netsource, must match jackd's period size)
REM -n number of channels to send (stereo)
REM -a async mode (0=off, 1=on) - async might help with network jitter but can add latency. Start with 0.
REM -v for verbose output
start "NetJack_Sender" /B jack_netsource.exe -v -H %MAC_IP% -p %NETJACK_PORT% -q 0 -r %SAMPLE_RATE% -P %PERIOD_SIZE% -n 2 -a 0

echo Waiting for NetJack sender to initialize and create ports (3 seconds)...
timeout /t 3 /nobreak >nul

echo.
echo Attempting to connect audio source to NetJack sender ports...
echo Source Prefix: %AUDIO_SOURCE_JACK_CAPTURE_PREFIX%
echo Destination: NetJack input ports (e.g., NetJack/send_1)
echo.

REM VB-Cable output often appears as JACK capture ports.
REM NetJack sender creates input ports, typically named "NetJack/send_1" and "NetJack/send_2".
REM Use jack_lsp.exe -c to see actual port names if connections fail.
jack_connect "%AUDIO_SOURCE_JACK_CAPTURE_PREFIX%:capture_1" "NetJack/send_1"
jack_connect "%AUDIO_SOURCE_JACK_CAPTURE_PREFIX%:capture_2" "NetJack/send_2"

REM Alternative common naming for VB-Cable if the above fails
jack_connect "%AUDIO_SOURCE_JACK_CAPTURE_PREFIX%:Out 1" "NetJack/send_1"
jack_connect "%AUDIO_SOURCE_JACK_CAPTURE_PREFIX%:Out 2" "NetJack/send_2"

echo.
echo Current JACK connections:
jack_lsp -c
echo.
echo NetJack sender should be running.
echo If audio is not transmitting, please verify connections using a JACK patchbay
echo (like QjackCtl, Catia from Cadence, or Patchage).
echo Ensure your audio source (e.g., %AUDIO_SOURCE_JACK_CAPTURE_PREFIX% output ports)
echo is connected to NetJack's input ports (e.g., 'NetJack/send_1', 'NetJack/send_2').
echo.
echo To stop: Close the JACKD_Server and NetJack_Sender console windows, or press Ctrl+C in them.
echo Pressing any key here will exit this script, but JACK and NetJack may continue running.
pause
endlocal