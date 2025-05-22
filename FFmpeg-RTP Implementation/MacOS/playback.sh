#!/bin/zsh
# filepath: /Users/reyneardouglas/WindowsToMacSpeaker/FFmpeg-RTP Implementation/MacOS/playback.sh

# FFmpeg RTP Audio Receiver for macOS

# Configuration
SDP_FILE="$(dirname "$0")/stream.sdp"
LOG_FILE="$(dirname "$0")/playback.log"
RTP_PORT=5004

echo "FFmpeg RTP Audio Receiver"
echo "========================"
echo "SDP File: $SDP_FILE"
echo "RTP Port: $RTP_PORT"
echo

# Function to kill processes using the port
free_port() {
    local port=$1
    local pids=$(lsof -ti :$port 2>/dev/null)
    if [ -n "$pids" ]; then
        echo "Freeing port $port..."
        echo $pids | xargs kill -9 2>/dev/null || true
        sleep 1
    fi
}

# Cleanup function
cleanup() {
    echo "Cleaning up..."
    pkill -f "ffplay.*$SDP_FILE" 2>/dev/null || true
    free_port $RTP_PORT
    exit 0
}

# Set up signal handlers
trap cleanup INT TERM EXIT

# Free port if in use
free_port $RTP_PORT

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
    echo "ERROR: ffplay not found. Install with: brew install ffmpeg"
    exit 1
fi

echo "Starting audio playback..."
echo "Press Ctrl+C to quit"
echo

# Start ffplay
ffplay -protocol_whitelist file,udp,rtp -i "$SDP_FILE" \
  -buffer_size 32768 \
  -max_delay 200000 \
  -fflags +genpts+igndts \
  -flags +low_delay \
  -sync audio \
  -autoexit \
  -nodisp \
  -loglevel warning 2>&1 | tee "$LOG_FILE" &

FFPLAY_PID=$!
wait $FFPLAY_PID
FFPLAY_EXIT=$?

if [ $FFPLAY_EXIT -ne 0 ] && [ $FFPLAY_EXIT -ne 130 ]; then
    echo "ERROR: Playback failed. Check log: $LOG_FILE"
    echo "Common issues:"
    echo "- No stream from Windows sender"
    echo "- Network connectivity problems" 
    echo "- Firewall blocking UDP port $RTP_PORT"
fi