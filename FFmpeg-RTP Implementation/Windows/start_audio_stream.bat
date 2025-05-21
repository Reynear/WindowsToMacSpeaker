@echo off 
setlocal

set MAC_IP=192.168.0.125
set AUDIO_DEV=CABLE Output (VB-Audio Virtual Cable)

echo Starting audio stream to %MAC_IP% on device %AUDIO_DEV%

REM Start the audio stream using ffmpeg
ffmpeg -f dshow -i audio="%AUDIO_DEV%" ^
-acodec libopus ^
-ar 48000 -ac 2 ^
-b:a 128k ^
-application lowdelay ^
-frame_duration 2.5 ^
-packet_loss 5 ^
-fflags nobuffer ^
-flags low_delay ^
-max_delay 0 ^
-flush_packets 1 ^
-analyzeduration 0 ^
-f rtp "rtp://%MAC_IP%:5004"

echo Audio stream ended. Press any key to stop...
pause
