#!/bin/bash

# For much lower latency
ffplay -protocol_whitelist file,udp,rtp -i stream.sdp -nodisp \
  -buffer_size 11k \
  -fflags nobuffer+discardcorrupt \
  -flags low_delay \
  -framedrop \
  -sync ext \
  -avioflags direct \
  -probesize 32 \
  -analyzeduration 0