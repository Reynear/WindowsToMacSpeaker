#!/bin/zsh

echo "macOS Audio Receiver Setup"
echo "=========================="

echo "Checking requirements..."

# Check FFmpeg
if command -v ffplay &> /dev/null; then
    echo "FOUND: FFmpeg/ffplay"
    ffplay -version | head -1
else
    echo "MISSING: FFmpeg"
    echo "Install with: brew install ffmpeg"
fi

# Check network configuration
echo
echo "Network Configuration:"
echo "Local IP addresses:"
ifconfig | grep -E "inet [0-9]" | grep -v 127.0.0.1

echo
echo "Setup complete. Run ./playback.sh to start receiving audio."