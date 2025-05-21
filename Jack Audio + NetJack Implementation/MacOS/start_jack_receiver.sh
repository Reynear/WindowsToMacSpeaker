#!/bin/bash

# --- Configuration ---
SAMPLE_RATE=48000
PERIOD_SIZE=128
NUM_PERIODS=2 # For jackd on macOS
NETJACK_PORT=19000
JACKD_PID=""

# --- Cleanup function ---
cleanup() {
    echo
    echo "Stopping NetJack manager and JACK server..."
    if jack_lsp -c | grep -q "netmanager"; then
        jack_unload netmanager
        echo "Netmanager unloaded."
    else
        echo "Netmanager not loaded or already unloaded."
    fi

    if [ -n "$JACKD_PID" ] && ps -p $JACKD_PID > /dev/null; then
        echo "Stopping JACK server (PID: $JACKD_PID)..."
        kill $JACKD_PID
        wait $JACKD_PID 2>/dev/null # Wait for it to terminate
        echo "JACK server stopped."
    elif pgrep -x "jackd" > /dev/null; then
        echo "JACK server PID not tracked, attempting to kill all jackd instances..."
        killall jackd
        sleep 1 # Give it a moment
        if pgrep -x "jackd" > /dev/null; then
            echo "jackd did not stop gracefully, forcing..."
            killall -9 jackd
        fi
        echo "All jackd instances should be stopped."
    else
        echo "JACK server not running or already stopped."
    fi
    echo "Cleanup complete."
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

echo "Starting JACK server on Mac..."
# Kill any existing JACK processes to ensure a clean start
killall -q jackd jackdmp netmanager # -q to suppress "no process found" errors
sleep 1 # Give a moment for processes to die

# Start JACK server with low-latency settings
# -R for real-time priority (macOS may require specific setup for this)
# -S for synchronous mode (can be more stable)
# -d coreaudio for macOS audio driver
# -r sample rate
# -p period size
# -n number of periods
# -o output channels (stereo) for jackd's own outputs
# -v for verbose output
jackd -R -S -v -d coreaudio -r $SAMPLE_RATE -p $PERIOD_SIZE -n $NUM_PERIODS -o 2 &
JACKD_PID=$!

# Wait for JACK server to be ready
echo "Waiting for JACK server to initialize (PID: $JACKD_PID)..."
if ! jack_wait -w -t 15; then # Wait up to 15 seconds for server to be ready
    echo "ERROR: JACK server failed to start or was not ready in time."
    cleanup
    exit 1
fi
echo "JACK server started successfully."

echo
echo "Listing available JACK ports (for reference):"
jack_lsp -A
echo

# Start NetJack receiver (as a JACK internal client via netmanager)
echo "Loading NetJack receiver (netmanager)..."
# -i for initial command to netmanager
# -p port for NetJack (must match sender)
# -a async mode (0=off, 1=on) - should match sender's setting. Start with 0.
if ! jack_load netmanager -i "-p $NETJACK_PORT -a 0"; then
    echo "ERROR: Failed to load netmanager."
    cleanup
    exit 1
fi
echo "NetJack manager loaded."
sleep 2 # Give netmanager a moment to establish ports and connections

echo
echo "Attempting to connect NetJack audio to system output..."
# NetJack (via netmanager) creates output ports, typically "netmanager:receive_1" and "netmanager:receive_2".
# System output ports are typically "system:playback_1", "system:playback_2".
# Use jack_lsp -c to see actual port names if connections fail.

if jack_connect "netmanager:receive_1" "system:playback_1" && \
   jack_connect "netmanager:receive_2" "system:playback_2"; then
    echo "NetJack audio successfully connected to system playback."
else
    echo "WARNING: Failed to automatically connect NetJack audio to system playback."
    echo "Please check available ports with 'jack_lsp -c' and connect manually if needed."
fi

echo
echo "Current JACK connections:"
jack_lsp -c
echo

echo "NetJack receiver should be running."
echo "If audio is not playing, verify connections using a JACK patchbay"
echo "(like QjackCtl, Catia from Cadence, or Patchage)."
echo "Ensure NetJack's output ports (e.g., 'netmanager:receive_1') are connected to 'system:playback_1'."
echo
echo "Press Ctrl+C to stop this script and shut down JACK."

# Keep script running and wait for JACK server to exit or for Ctrl+C
wait $JACKD_PID
# The trap will handle cleanup