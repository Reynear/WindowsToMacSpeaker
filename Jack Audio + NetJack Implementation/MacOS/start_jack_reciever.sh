#!/bin/zsh
# start_jack_receiver.sh

SAMPLE_RATE=48000
PERIOD_SIZE=64

# Start JACK server (CoreAudio driver)
jackd -R -d coreaudio -r $SAMPLE_RATE -p $PERIOD_SIZE &

sleep 5

# Load NetJack manager (auto-discovers sender)
jack_load netmanager

echo "JACK receiver ready. Use QjackCtl or jack_connect to route netmanager:capture_X to system:playback_X"