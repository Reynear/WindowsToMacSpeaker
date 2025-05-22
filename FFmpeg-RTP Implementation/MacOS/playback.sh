#!/bin/zsh


# Enhanced FFmpeg RTP Audio Receiver for macOS
# Optimized for low latency audio streaming

# Configuration
SDP_FILE="$(dirname "$0")/stream.sdp"
LOG_FILE="$(dirname "$0")/playback.log"
AUDIO_DEVICE="default"  # Can be changed to specific device

echo "FFmpeg RTP Audio Receiver"
echo "========================"
echo "SDP File: $SDP_FILE"
echo "Log File: $LOG_FILE"
echo "Audio Device: $AUDIO_DEVICE"
echo

# Validate SDP file exists
if [ ! -f "$SDP_FILE" ]; then
    echo "ERROR: SDP file not found: $SDP_FILE"
    exit 1
fi

echo "SDP Configuration:"
cat "$SDP_FILE"
echo

# Check for ffplay
if ! command -v ffplay &> /dev/null; then
    echo "ERROR: ffplay not found. Please install FFmpeg:"
    echo "brew install ffmpeg"
    exit 1
fi

echo "FFmpeg version:"
ffplay -version | head -1
echo

# List available audio devices (macOS specific)
echo "Available audio devices:"
ffplay -f avfoundation -list_devices true -i "" 2>&1 | grep -E "\[AVFoundation.*audio"
echo

# Start playback with enhanced low-latency settings
echo "Starting audio playback..."
echo "Press 'q' to quit, 'ESC' to quit"
echo

# Log startup
{
    echo "Starting FFplay audio receiver at $(date)"
    echo "SDP: $SDP_FILE"
    echo "Device: $AUDIO_DEVICE"
    echo
} > "$LOG_FILE"

# Start ffplay with low-latency settings
# Note: Adjust buffer size and latency settings as needed
ffplay -protocol_whitelist file,udp,rtp -i stream.sdp \
  -buffer_size 65536 \
  -max_delay 500000 \
  -reorder_queue_size 500 \
  -fflags +genpts+igndts \
  -flags +low_delay \
  -avoid_negative_ts make_zero \
  -use_wallclock_as_timestamps 1 \
  -thread_queue_size 1024 \
  -nodisp

FFPLAY_EXIT=$?
echo
echo "FFplay exited with code: $FFPLAY_EXIT"

if [ $FFPLAY_EXIT -ne 0 ]; then
    echo "ERROR: Audio playback failed. Check log: $LOG_FILE"
    echo "Common issues:"
    echo "- No audio stream received from Windows"
    echo "- Network connectivity problems"
    echo "- Audio device conflicts"
    echo "- Firewall blocking UDP port 5004"
fi

echo "Press Enter to exit..."
read