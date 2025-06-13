#!/usr/bin/env python3
"""
Test script to verify sender and receiver work together
"""

import time
import threading
import subprocess
import sys
import os

def test_packet_format():
    """Test that sender and receiver use compatible packet formats"""
    print("Testing packet format compatibility...")
    
    # Test packet creation (sender format)
    import struct
    packet_count = 12345
    timestamp = int(time.time() * 1000000)  # microseconds
    opus_data = b"test_opus_data_12345"
    opus_length = len(opus_data)
    
    # Create packet (sender format)
    header = struct.pack('!LQL', packet_count, timestamp, opus_length)
    packet = header + opus_data
    
    print(f"Created packet: {len(packet)} bytes")
    print(f"  Header: {len(header)} bytes")
    print(f"  Opus data: {opus_length} bytes")
      # Parse packet (receiver format)
    header_size = 16  # 4 + 8 + 4 bytes
    if len(packet) >= header_size:
        parsed_header = struct.unpack('!LQL', packet[:header_size])
        parsed_packet_count = parsed_header[0]
        parsed_timestamp = parsed_header[1] 
        parsed_opus_length = parsed_header[2]
        parsed_opus_data = packet[header_size:header_size + parsed_opus_length]
        
        print(f"Parsed packet:")
        print(f"  Packet count: {parsed_packet_count} (expected {packet_count})")
        print(f"  Timestamp: {parsed_timestamp} (expected {timestamp})")
        print(f"  Opus length: {parsed_opus_length} (expected {opus_length})")
        print(f"  Opus data: {parsed_opus_data} (expected {opus_data})")
        
        # Verify
        success = (
            parsed_packet_count == packet_count and
            parsed_timestamp == timestamp and  
            parsed_opus_length == opus_length and
            parsed_opus_data == opus_data
        )
        
        if success:
            print("✅ Packet format test PASSED")
            return True
        else:
            print("❌ Packet format test FAILED")
            return False
    else:
        print("❌ Packet too short")
        return False

def check_dependencies():
    """Check if required dependencies are available"""
    print("Checking dependencies...")
    
    try:
        import sounddevice as sd
        print("✅ sounddevice available")
    except ImportError:
        print("❌ sounddevice not available - install with: pip install sounddevice")
        return False
        
    try:
        import opuslib
        # Try to create an encoder to test if opus library is properly installed
        encoder = opuslib.Encoder(fs=48000, channels=2, application=opuslib.APPLICATION_RESTRICTED_LOWDELAY)
        print("✅ opuslib available and working")
    except ImportError:
        print("❌ opuslib not available - install with: pip install opuslib")
        print("   Also install Opus library:")
        print("   Windows: Download opus.dll from https://opus-codec.org/downloads/")
        print("   Or use conda: conda install opus")
        return False
    except Exception as e:
        print(f"❌ opuslib installed but Opus library not found: {e}")
        print("   Please install the Opus library:")
        print("   Windows: Download opus.dll and place in PATH or Python directory")
        print("   Or use conda: conda install opus")
        print("   Or use conda-forge: conda install -c conda-forge opus")
        return False
        
    try:
        import numpy as np
        print("✅ numpy available")
    except ImportError:
        print("❌ numpy not available - install with: pip install numpy")
        return False
        
    return True

def check_config_file():
    """Check if config file exists and is valid"""
    config_file = "config.json"
    print(f"Checking config file: {config_file}")
    
    if not os.path.exists(config_file):
        print(f"❌ Config file {config_file} not found")
        return False
        
    try:
        import json
        with open(config_file, 'r') as f:
            config = json.load(f)
            
        required_sections = ['network', 'audio', 'opus', 'logging']
        for section in required_sections:
            if section not in config:
                print(f"❌ Missing section '{section}' in config")
                return False
                
        print("✅ Config file is valid")
        print(f"  Target IP: {config['network']['ip']}")
        print(f"  Port: {config['network']['port']}")
        print(f"  Sample rate: {config['audio']['sample_rate']}")
        print(f"  Channels: {config['audio']['channels']}")
        print(f"  Opus bitrate: {config['opus']['bitrate']}")
        return True
        
    except Exception as e:
        print(f"❌ Error reading config: {e}")
        return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("UDP Audio Streaming Test")
    print("=" * 60)
    
    tests_passed = 0
    total_tests = 3
    
    # Test 1: Dependencies
    if check_dependencies():
        tests_passed += 1
        
    # Test 2: Packet format
    if test_packet_format():
        tests_passed += 1
          # Test 3: Config file
    if check_config_file():
        tests_passed += 1
        
    print("=" * 60)
    print(f"Test Results: {tests_passed}/{total_tests} passed")
    
    if tests_passed == total_tests:
        print("✅ All tests passed! Sender and receiver should work together.")
        print("\nTo use:")
        print("1. Start receiver: python reciever.py")
        print("2. Start sender: python sender.py")
    else:
        print("❌ Some tests failed. Please fix issues before running.")
        print("\nCommon fixes:")
        print("1. Install missing Python packages:")
        print("   pip install sounddevice numpy opuslib")
        print("2. Install Opus library (choose one):")
        print("   • conda install -c conda-forge opus")
        print("   • Download opus.dll from https://opus-codec.org/downloads/")
        print("   • Use Windows package manager: winget install opus-tools")
        print("3. Ensure config.json exists in this directory")
        
    return tests_passed == total_tests

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
