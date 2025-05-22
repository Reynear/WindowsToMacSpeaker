@echo off
setlocal enabledelayedexpansion

set "MAC_IP=192.168.0.125"
set "AUDIO_DEV=CABLE Output (VB-Audio Virtual Cable)"
set "PRIMARY_PORT=5004"
set "BACKUP_PORT=5005"

echo Starting redundant audio stream...
echo Primary: %MAC_IP%:%PRIMARY_PORT%
echo Backup: %MAC_IP%:%BACKUP_PORT%

REM Start primary stream with FEC
start "Primary_Stream" ffmpeg -f dshow -i audio="%AUDIO_DEV%" ^
  -acodec libopus ^
  -ar 48000 -ac 2 ^
  -b:a 128k ^
  -application lowdelay ^
  -frame_duration 20 ^
  -packet_loss 15 ^
  -fec on ^
  -dtx off ^
  -max_delay 50000 ^
  -muxdelay 0 ^
  -f rtp "rtp://%MAC_IP%:%PRIMARY_PORT%"

REM Start backup stream with delay
timeout /t 2 /nobreak >nul
start "Backup_Stream" ffmpeg -f dshow -i audio="%AUDIO_DEV%" ^
  -acodec libopus ^
  -ar 48000 -ac 2 ^
  -b:a 96k ^
  -application lowdelay ^
  -frame_duration 40 ^
  -packet_loss 20 ^
  -fec on ^
  -max_delay 100000 ^
  -f rtp "rtp://%MAC_IP%:%BACKUP_PORT%"

echo Both streams started.
echo Primary stream: Higher quality, lower latency
echo Backup stream: More robust, higher latency tolerance
pause
