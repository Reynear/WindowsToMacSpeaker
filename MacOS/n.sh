#!/bin/bash
ffplay -protocol_whitelist file,udp,rtp -i stream.sdp -nodisp -buffer_size 30k