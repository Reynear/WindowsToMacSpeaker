@echo off
setlocal

REM --- Configuration ---
set MAC_IP=192.168.0.125
set SAMPLE_RATE=48000
set PERIOD_SIZE=128
REM NUM_PERIODS will be used for jack_netsource's network latency option
set NUM_PERIODS=2
set NETJACK_PORT=19000

REM IMPORTANT: Based on jack_lsp -A output, the system audio source ports are "system:capture_X"
set AUDIO_SOURCE_CLIENT_NAME="system"
set AUDIO_SOURCE_PORT_1="capture_1"
set AUDIO_SOURCE_PORT_2="capture_2"

REM --- Set Path to JACK Installation ---
REM Adjust this path if JACK2 is installed in a different location.
set "JACK_INSTALL_DIR=C:\Program Files\JACK2"
if not exist "%JACK_INSTALL_DIR%\jackd.exe" (
    set "JACK_INSTALL_DIR=C:\Program Files (x86)\JACK2"
    if not exist "%JACK_INSTALL_DIR%\jackd.exe" (
        echo ERROR: jackd.exe not found in "%ProgramFiles%\JACK2" or "%ProgramFiles(x86)%\JACK2".
        echo Please install JACK2 from https://jackaudio.org/downloads/
        echo or update the JACK_INSTALL_DIR variable in this script.
        pause
        exit /b 1
    )
)

REM Check for the 'tools' directory where other executables are expected
if not exist "%JACK_INSTALL_DIR%\tools\jack_netsource.exe" (
    echo ERROR: jack_netsource.exe not found in "%JACK_INSTALL_DIR%\tools".
    echo Please ensure JACK2 tools are correctly installed in a 'tools' subdirectory.
    pause
    exit /b 1
)

REM Check for the 'jack' subdirectory where DLLs are expected
if not exist "%JACK_INSTALL_DIR%\jack\jack.dll" (
    echo ERROR: jack.dll not found in "%JACK_INSTALL_DIR%\jack".
    echo Please ensure JACK2 DLLs are correctly installed in a 'jack' subdirectory.
    pause
    exit /b 1
)

echo Using JACK from: %JACK_INSTALL_DIR%
REM Add main JACK directory (for jackd.exe), tools directory, and jack (DLL) directory to PATH
set PATH=%PATH%;%JACK_INSTALL_DIR%;%JACK_INSTALL_DIR%\tools;%JACK_INSTALL_DIR%\jack

echo Starting JACK server on Windows...
REM -R for real-time priority (if possible)
REM -P99 for high priority (Windows specific)
REM -d portaudio
REM -r sample rate
REM -p period size (buffer size for jackd)
REM -D for duplex mode (input and output)
REM -o 2 for 2 output channels (stereo) - jackd needs to know its own output channels
REM -v for verbose output (this is a general jackd option)
start "JACKD_Server" /B jackd.exe -R -P99 -v -d portaudio -r %SAMPLE_RATE% -p %PERIOD_SIZE% -D -o 2

echo Waiting for JACK server to initialize (5 seconds)...
timeout /t 5 /nobreak >nul

echo.
echo Listing available JACK ports (for reference):
jack_lsp.exe -A
echo.

echo Starting NetJack sender to Mac (%MAC_IP%)...
REM -H target host IP
REM -p target host port
REM -r sample rate (must match jackd)
REM -i number of audio channels to capture and send (stereo = 2)
REM -n network latency in JACK periods (use NUM_PERIODS from config)
start "NetJack_Sender" /B jack_netsource.exe -H %MAC_IP% -p %NETJACK_PORT% -r %SAMPLE_RATE% -i 2 -n %NUM_PERIODS%

echo Waiting for NetJack sender to initialize and create ports (5 seconds)...
timeout /t 5 /nobreak >nul

echo.
echo Attempting to connect audio source to NetJack sender ports...
echo Source: %AUDIO_SOURCE_CLIENT_NAME%:%AUDIO_SOURCE_PORT_1% and %AUDIO_SOURCE_CLIENT_NAME%:%AUDIO_SOURCE_PORT_2%
echo Destination: netjack:capture_1 and netjack:capture_2
echo.

REM Connect the system capture ports to netjack's input ports
jack_connect.exe "%AUDIO_SOURCE_CLIENT_NAME%:%AUDIO_SOURCE_PORT_1%" "netjack:capture_1"
jack_connect.exe "%AUDIO_SOURCE_CLIENT_NAME%:%AUDIO_SOURCE_PORT_2%" "netjack:capture_2"

echo.
echo Current JACK connections:
jack_lsp.exe -c
echo.
echo NetJack sender should be running.
echo If audio is not transmitting, please verify connections using a JACK patchbay
echo (like QjackCtl, Catia from Cadence, or Patchage).
echo Ensure '%AUDIO_SOURCE_CLIENT_NAME%:%AUDIO_SOURCE_PORT_1%' is connected to 'netjack:capture_1'
echo and '%AUDIO_SOURCE_CLIENT_NAME%:%AUDIO_SOURCE_PORT_2%' is connected to 'netjack:capture_2'.
echo.
echo To stop: Close the JACKD_Server and NetJack_Sender console windows, or press Ctrl+C in them.
echo Pressing any key here will exit this script, but JACK and NetJack may continue running.
pause
endlocal