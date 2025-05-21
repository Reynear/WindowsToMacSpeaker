#!/bin/bash

# JACK receiver configuration
SAMPLE_RATE=48000
PERIOD_SIZE=128
NETJACK_PORT=19000

echo "Starting JACK server on Mac..."

# Kill any existing JACK processes
killall jackd jackdmp 2>/dev/null

# Start JACK server with low-latency settings
jackd -R -d coreaudio -r $SAMPLE_RATE -p $PERIOD_SIZE -o 2 &

# Wait for JACK to initialize
sleep 2

# Start NetJack receiver
echo "Starting NetJack receiver..."
jack_load netmanager -i "-p $NETJACK_PORT -a 0"

# Automatically connect incoming audio to system output
jack_connect netjack:receive_1 system:playback_1
jack_connect netjack:receive_2 system:playback_2

# Display connections
jack_lsp -c

echo "NetJack receiver running. Press Ctrl+C to stop."