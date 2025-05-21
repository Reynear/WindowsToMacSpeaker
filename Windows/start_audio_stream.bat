@echo off 
setlocal

set MAC_IP=192.168.0.125

set AUDIO_DEV=Cable Output (VB-Audio Virtual Cable)

echo Starting audio stream to %MAC_IP% on device %AUDIO_DEV%

REM Start the audio stream using ffmpeg
ffmpeg -f dshow -i audio="%AUDIO_DEV%" ^
-acodec libopus -b:a 128k ^
-ar 48000 -ac 2 ^
-b:a 128k ^
-f rtp "rtp://%MAC_IP%:5004" ^
-nobuffer -re -loglevel error ^