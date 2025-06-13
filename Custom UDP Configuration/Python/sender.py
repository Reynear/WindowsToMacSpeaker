"""
UDP Audio Sender with Opus Compression

Packet Format:
    packet_count: 4 bytes (unsigned long, network byte order)
    timestamp: 8 bytes (unsigned long long, network byte order) 
    opus_length: 4 bytes (unsigned long, network byte order)
    opus_data: variable length (compressed audio)

Total header size: 16 bytes + opus_data
Compatible with UDPAudioReceiver
"""

import socket
import sounddevice as sd
import threading
import time
import struct
import numpy as np
import sys
import opuslib
import json
import os
import csv
from datetime import datetime

class UDPAudioSender:
    def __init__(self, config_file="config.json"):
        # Load configuration from JSON file with defaults
        self.config = self.load_config(config_file)
        
        # Network configuration
        self.target_ip = self.config['network']['ip']
        self.target_port = self.config['network']['port']
        
        # Audio configuration
        self.chunk_size = self.config['audio']['chunk_size']
        self.channels = self.config['audio']['channels']
        self.sample_rate = self.config['audio']['sample_rate']
        self.dtype = np.int16
        
        # Opus encoder configuration
        self.opus_bitrate = self.config['opus']['bitrate']
        self.opus_frame_duration = self.config['opus']['frame_duration']
        
        # Initialize Opus encoder
        self.opus_encoder = opuslib.Encoder(
            fs=self.sample_rate,
            channels=self.channels,
            application=opuslib.APPLICATION_RESTRICTED_LOWDELAY
        )
        self.opus_encoder.bitrate = self.opus_bitrate
        
        # Calculate samples per Opus frame
        self.opus_frame_samples = int(self.sample_rate * self.opus_frame_duration / 1000)
        
        # Find VB-Cable or use specified device
        device_id = self.config['audio'].get('input_device_id', None)
        self.input_device = self.find_input_device(device_id)
        
        # UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Minimize socket buffer for low latency
        buffer_size = self.config['network']['socket_buffer_size']
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, buffer_size)
        
        # Control flags
        self.streaming = False
        self.packet_count = 0
        self.start_time = None
        
        # Audio buffer for Opus frame accumulation
        self.audio_buffer = np.array([], dtype=np.int16).reshape(0, self.channels)
        
        # CSV logging setup
        self.csv_file = self.config['logging'].get('sender_csv_file', 'sender_metrics.csv')
        self.csv_writer = None
        self.csv_file_handle = None
        self.init_csv_logging()
        
    def load_config(self, config_file):
        """Load configuration from JSON file with defaults"""
        default_config = {
            "network": {
                "ip": "192.168.0.125",
                "port": 5004,
                "socket_buffer_size": 8192
            },
            "audio": {
                "sample_rate": 48000,
                "channels": 2,
                "chunk_size": 1024,
                "input_device_id": None,
                "input_device_name": "VB-Audio",
                "output_device_id": None,
                "output_device_name": "default"
            },
            "opus": {
                "bitrate": 128000,
                "frame_duration": 20
            },
            "logging": {
                "stats_interval": 1000,
                "verbose": True,
                "sender_csv_file": "sender_metrics.csv",
                "receiver_csv_file": "receiver_metrics.csv",
                "enable_csv": True
            }
        }
        
        # Try to load config file
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    file_config = json.load(f)
                    
                # Merge configs (file config overrides defaults)
                config = default_config.copy()
                for section, values in file_config.items():
                    if section in config:
                        config[section].update(values)
                    else:
                        config[section] = values
                        
                print(f"Loaded configuration from {config_file}")
                return config
                
            except Exception as e:
                print(f"Error loading config file {config_file}: {e}")
                print("Using default configuration")
                
        else:
            print(f"Config file {config_file} not found, using defaults")
            # Create default config file
            self.save_config(config_file, default_config)
            
        return default_config
    
    def save_config(self, config_file, config):
        """Save configuration to JSON file"""
        try:
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=2)
            print(f"Default configuration saved to {config_file}")
        except Exception as e:
            print(f"Error saving config file: {e}")
    
    def init_csv_logging(self):
        """Initialize CSV logging"""
        if not self.config['logging']['enable_csv']:
            return
        
        try:
            # Check if file exists to determine if we need to write headers
            file_exists = os.path.exists(self.csv_file)
            
            self.csv_file_handle = open(self.csv_file, 'a', newline='')
            self.csv_writer = csv.writer(self.csv_file_handle)
            
            # Write headers if file is new
            if not file_exists:
                headers = [
                    'timestamp',
                    'session_start', 
                    'packet_count',
                    'elapsed_time',
                    'packet_rate',
                    'compression_ratio',
                    'raw_bytes',
                    'compressed_bytes',
                    'target_ip',
                    'target_port',
                    'sample_rate',
                    'channels',
                    'opus_bitrate',
                    'frame_duration'
                ]
                self.csv_writer.writerow(headers)
                self.csv_file_handle.flush()
                
            print(f"CSV logging enabled: {self.csv_file}")
            
        except Exception as e:
            print(f"Error initializing CSV logging: {e}")
            # Clean up on error
            if self.csv_file_handle:
                self.csv_file_handle.close()
            self.csv_writer = None
            self.csv_file_handle = None

    def log_metrics_to_csv(self, elapsed, rate, compression_ratio, raw_bytes, compressed_bytes):
        """Log metrics to CSV file"""
        if not self.csv_writer:
            return
            
        try:
            row = [
                datetime.now().isoformat(),
                datetime.fromtimestamp(self.start_time).isoformat() if self.start_time else "Unknown",
                self.packet_count,
                elapsed,
                rate,
                compression_ratio,
                raw_bytes,
                compressed_bytes,
                self.target_ip,
                self.target_port,
                self.sample_rate,
                self.channels,                self.opus_bitrate,
                self.opus_frame_duration
            ]
            self.csv_writer.writerow(row)
            if self.csv_file_handle:
                self.csv_file_handle.flush()  # Ensure data is written immediately
            
        except Exception as e:
            print(f"Error writing to CSV: {e}")
        
    def find_input_device(self, device_id=None):
        """Find VB-Cable or best input device"""
        devices = sd.query_devices()
        
        # If specific device ID provided, use it
        if device_id is not None:
            try:
                device_info = sd.query_devices(device_id)
                max_channels = getattr(device_info, 'max_input_channels', 0)
                name = getattr(device_info, 'name', 'Unknown')
                if max_channels > 0:
                    print(f"Using specified device {device_id}: {name}")
                    return device_id
            except:
                print(f"Device {device_id} not found, searching for alternatives")
        
        # Look for VB-Cable or configured device name
        device_name = self.config['audio']['input_device_name']
        for i, device in enumerate(devices):
            device_name_attr = getattr(device, 'name', '')
            max_channels = getattr(device, 'max_input_channels', 0)
            if device_name.lower() in device_name_attr.lower():
                if max_channels > 0:
                    print(f"Found audio device: {device_name_attr}")
                    return i
        
        # Fallback to default input
        try:
            default_input = sd.default.device[0]
            if default_input is not None:
                device_info = sd.query_devices(default_input)
                name = getattr(device_info, 'name', 'Unknown')
                print(f"Using default input: {name}")
                return default_input
        except:
            pass
            
        print("Error: No suitable input device found.")
        print("Available devices:")
        self.list_audio_devices()
        sys.exit(1)
    
    def audio_callback(self, indata, frames, time_info, status):
        """Callback function for audio stream"""
        if status and self.config['logging']['verbose']:
            print(f"Audio status: {status}")
        
        if self.streaming:
            try:
                # Convert float32 to int16
                audio_data = (indata * 32767).astype(np.int16)
                
                # Add to buffer
                self.audio_buffer = np.vstack([self.audio_buffer, audio_data])
                
                # Process complete Opus frames
                while len(self.audio_buffer) >= self.opus_frame_samples:
                    # Extract one Opus frame
                    frame_data = self.audio_buffer[:self.opus_frame_samples]
                    self.audio_buffer = self.audio_buffer[self.opus_frame_samples:]
                    
                    # Encode with Opus
                    pcm_bytes = frame_data.flatten().tobytes()
                    opus_data = self.opus_encoder.encode(pcm_bytes, self.opus_frame_samples)
                    
                    # Create packet header (sequence number + timestamp + opus data length)
                    timestamp = int(time.time() * 1000000)  # microseconds
                    opus_length = len(opus_data)
                    header = struct.pack('!LQL', self.packet_count, timestamp, opus_length)
                    
                    # Send UDP packet
                    packet = header + opus_data
                    self.sock.sendto(packet, (self.target_ip, self.target_port))
                    
                    self.packet_count += 1
                    
                    # Print stats and log to CSV based on config interval
                    stats_interval = self.config['logging']['stats_interval']
                    if self.packet_count % stats_interval == 0:
                        elapsed = time.time() - (self.start_time or time.time())
                        rate = self.packet_count / elapsed
                        compression_ratio = len(pcm_bytes) / len(opus_data)
                        
                        # Console output
                        if self.config['logging']['verbose']:
                            print(f"Sent {self.packet_count} packets, {rate:.1f} pkt/sec, "
                                  f"compression: {compression_ratio:.1f}x")
                        
                        # CSV logging
                        self.log_metrics_to_csv(elapsed, rate, compression_ratio, 
                                              len(pcm_bytes), len(opus_data))
                    
            except Exception as e:
                print(f"Error in audio callback: {e}")
    
    def start_streaming(self):
        """Start audio capture and UDP transmission"""
        print(f"Starting audio stream to {self.target_ip}:{self.target_port}")
        print(f"Audio: {self.sample_rate}Hz, {self.channels} channels")
        print(f"Opus: {self.opus_bitrate} bps, {self.opus_frame_duration}ms frames")
        print(f"Capture chunks: {self.chunk_size} samples")
        
        try:
            self.streaming = True
            self.packet_count = 0
            self.start_time = time.time()
            
            print("Streaming started. Press Ctrl+C to stop...")
            
            # Start audio stream with callback
            with sd.InputStream(
                device=self.input_device,
                channels=self.channels,
                samplerate=self.sample_rate,
                blocksize=self.chunk_size,
                dtype=np.float32,  # sounddevice uses float32 internally
                callback=self.audio_callback,
                latency='low'  # Request low latency mode
            ):
                # Keep the stream alive
                while self.streaming:
                    time.sleep(0.1)
            
        except Exception as e:
            print(f"Failed to start audio stream: {e}")
        finally:
            self.cleanup()
    
    def stop_streaming(self):
        """Stop audio streaming"""
        self.streaming = False
    
    def cleanup(self):
        """Clean up resources"""
        self.sock.close()
        
        # Close CSV file
        if self.csv_file_handle:
            try:
                self.csv_file_handle.close()
                print(f"Metrics saved to: {self.csv_file}")
            except:
                pass
            self.csv_file_handle = None
            
        print("Audio sender stopped.")

    def list_audio_devices(self):
        """List available audio devices"""
        print("Available audio devices:")
        devices = sd.query_devices()
        for i, device in enumerate(devices):
            max_channels = getattr(device, 'max_input_channels', 0)
            name = getattr(device, 'name', 'Unknown')
            if max_channels > 0:
                print(f"  {i}: {name} (inputs: {max_channels})")


if __name__ == "__main__":
    sender = UDPAudioSender()

    try:
        sender.start_streaming()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        sender.stop_streaming()