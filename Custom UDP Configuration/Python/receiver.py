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

class UDPAudioReceiver:
    def __init__(self, config_file="config.json"):
        # Load configuration from JSON file with defaults
        self.config = self.load_config(config_file)
        
        # Network configuration
        self.listen_ip = "0.0.0.0"  # Always listen on all interfaces
        self.listen_port = self.config['network']['port']
        
        # Audio configuration
        self.chunk_size = self.config['audio']['chunk_size']
        self.channels = self.config['audio']['channels']
        self.sample_rate = self.config['audio']['sample_rate']
        self.dtype = np.int16
        
        # Opus decoder configuration
        self.opus_frame_duration = self.config['opus']['frame_duration']
        
        # Initialize Opus decoder
        self.opus_decoder = opuslib.Decoder(
            fs=self.sample_rate,
            channels=self.channels
        )
        
        # Calculate samples per Opus frame
        self.opus_frame_samples = int(self.sample_rate * self.opus_frame_duration / 1000)
        
        # Find output device
        device_id = self.config['audio'].get('output_device_id', None)
        self.output_device = self.find_output_device(device_id)
        
        # UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Set receive buffer size
        buffer_size = self.config['network']['socket_buffer_size']
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, buffer_size)
        
        # Bind to listen address
        self.sock.bind((self.listen_ip, self.listen_port))
        
        # Control flags
        self.receiving = False
        self.packet_count = 0
        self.start_time = None
        
        # Audio playback buffer and threading
        self.audio_queue = []
        self.queue_lock = threading.Lock()
        self.playback_thread = None
        
        # Packet statistics
        self.lost_packets = 0
        self.last_sequence = -1
        
        # CSV file for logging metrics
        self.csv_file = self.config['logging'].get('receiver_csv_file', 'receiver_metrics.csv')
        self.csv_writer = None
        self.csv_file_handle = None
        self.init_csv_logging()
        
    def load_config(self, config_file):
        """Load configuration from JSON file with defaults"""
        default_config = {
            "network": {
                "ip": "192.168.0.125",
                "port": 5004,
                "socket_buffer_size": 65536
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
                    'packets_lost',
                    'loss_rate_percent',
                    'queue_size',
                    'listen_ip',
                    'listen_port',
                    'sample_rate',
                    'channels',
                    'frame_duration',
                    'buffer_size'
                ]
                self.csv_writer.writerow(headers)
                self.csv_file_handle.flush()
                
            print(f"CSV logging enabled: {self.csv_file}")
            
        except Exception as e:
            print(f"Error initializing CSV logging: {e}")
            self.csv_writer = None
            self.csv_file_handle = None

    def log_metrics_to_csv(self, elapsed, rate, loss_rate, queue_size):
        """Log metrics to CSV file"""
        if not self.csv_writer:
            return
            
        try:
            row = [
                datetime.now().isoformat(),
                datetime.fromtimestamp(self.start_time).isoformat(),
                self.packet_count,
                elapsed,
                rate,
                self.lost_packets,
                loss_rate,
                queue_size,
                self.listen_ip,
                self.listen_port,
                self.sample_rate,
                self.channels,
                self.opus_frame_duration,
                self.config['network']['socket_buffer_size']
            ]
            self.csv_writer.writerow(row)
            self.csv_file_handle.flush()
            
        except Exception as e:
            print(f"Error writing to CSV: {e}")
        
    def find_output_device(self, device_id=None):
        """Find best output device"""
        devices = sd.query_devices()
        
        # If specific device ID provided, use it
        if device_id is not None:
            try:
                device_info = sd.query_devices(device_id)
                if device_info['max_output_channels'] > 0:
                    print(f"Using specified device {device_id}: {device_info['name']}")
                    return device_id
            except:
                print(f"Device {device_id} not found, searching for alternatives")
        
        # Look for configured device name
        device_name = self.config['audio']['output_device_name']
        if device_name != "default":
            for i, device in enumerate(devices):
                if device_name.lower() in device['name'].lower():
                    if device['max_output_channels'] > 0:
                        print(f"Found audio device: {device['name']}")
                        return i
        
        # Fallback to default output
        try:
            default_output = sd.default.device[1]  # Output device
            if default_output is not None:
                device_info = sd.query_devices(default_output)
                print(f"Using default output: {device_info['name']}")
                return default_output
        except:
            pass
            
        print("Error: No suitable output device found.")
        print("Available devices:")
        self.list_audio_devices()
        return None
    
    def audio_callback(self, outdata, frames, time_info, status):
        """Callback function for audio playback"""
        if status and self.config['logging']['verbose']:
            print(f"Audio status: {status}")
        
        # Initialize output with silence
        outdata.fill(0)
        
        with self.queue_lock:
            if len(self.audio_queue) > 0:
                # Get audio data from queue
                audio_data = self.audio_queue.pop(0)
                
                # Ensure we don't exceed the output buffer size
                samples_to_copy = min(len(audio_data), frames)
                
                # Copy audio data to output buffer
                outdata[:samples_to_copy] = audio_data[:samples_to_copy].reshape(-1, self.channels)
                
                # Check for buffer underrun
                if len(self.audio_queue) < 2:
                    if self.config['logging']['verbose']:
                        print(f"Buffer underrun warning: {len(self.audio_queue)} frames queued")
    
    def receive_packets(self):
        """Receive and process UDP packets"""
        print(f"Listening for audio packets on {self.listen_ip}:{self.listen_port}")
        
        while self.receiving:
            try:
                # Receive UDP packet
                packet, addr = self.sock.recvfrom(65536)
                
                if len(packet) < 16:  # Header is 16 bytes
                    continue
                
                # Parse packet header
                sequence, timestamp, opus_length = struct.unpack('!LQL', packet[:16])
                opus_data = packet[16:16+opus_length]
                
                # Check for lost packets
                if self.last_sequence != -1:
                    expected_sequence = self.last_sequence + 1
                    if sequence != expected_sequence:
                        lost = sequence - expected_sequence
                        self.lost_packets += lost
                        if self.config['logging']['verbose']:
                            print(f"Lost {lost} packets (expected {expected_sequence}, got {sequence})")
                
                self.last_sequence = sequence
                
                # Decode Opus data
                pcm_data = self.opus_decoder.decode(opus_data, self.opus_frame_samples)
                
                # Convert bytes to numpy array
                audio_array = np.frombuffer(pcm_data, dtype=np.int16)
                
                # Convert to float32 for sounddevice
                audio_float = audio_array.astype(np.float32) / 32767.0
                
                # Add to playback queue
                with self.queue_lock:
                    if len(self.audio_queue) < 10:  # Hardcoded queue size
                        self.audio_queue.append(audio_float)
                    else:
                        # Queue full, drop oldest frame
                        self.audio_queue.pop(0)
                        self.audio_queue.append(audio_float)
                        if self.config['logging']['verbose']:
                            print("Audio queue full, dropping frame")
                
                self.packet_count += 1
                
                # Print stats and log to CSV
                stats_interval = self.config['logging']['stats_interval']
                if self.packet_count % stats_interval == 0:
                    elapsed = time.time() - self.start_time
                    rate = self.packet_count / elapsed
                    total_packets = self.packet_count + self.lost_packets
                    loss_rate = (self.lost_packets / total_packets) * 100 if total_packets > 0 else 0
                    queue_size = len(self.audio_queue)
                    
                    # Console output
                    if self.config['logging']['verbose']:
                        print(f"Received {self.packet_count} packets, {rate:.1f} pkt/sec, "
                              f"loss: {loss_rate:.2f}%, queue: {queue_size}")
                    
                    # CSV logging
                    self.log_metrics_to_csv(elapsed, rate, loss_rate, queue_size)
                
            except socket.timeout:
                continue
            except Exception as e:
                if self.receiving:
                    print(f"Error receiving packet: {e}")
                break
    
    def start_receiving(self):
        """Start audio reception and playback"""
        print(f"Starting audio receiver on {self.listen_ip}:{self.listen_port}")
        print(f"Audio: {self.sample_rate}Hz, {self.channels} channels")
        print(f"Opus: {self.opus_frame_duration}ms frames")
        
        if self.output_device is None:
            print("Cannot continue without a valid audio output device.")
            return False
        
        try:
            self.receiving = True
            self.packet_count = 0
            self.lost_packets = 0
            self.last_sequence = -1
            self.start_time = time.time()
            
            # Set socket timeout for clean shutdown
            self.sock.settimeout(1.0)
            
            print("Reception started. Press Ctrl+C to stop...")
            
            # Start packet reception thread
            self.receive_thread = threading.Thread(target=self.receive_packets)
            self.receive_thread.daemon = True
            self.receive_thread.start()
            
            # Start audio playback stream
            with sd.OutputStream(
                device=self.output_device,
                channels=self.channels,
                samplerate=self.sample_rate,
                blocksize=self.chunk_size,
                dtype=np.float32,
                callback=self.audio_callback,
                latency='low'
            ):
                # Keep the stream alive
                while self.receiving:
                    time.sleep(0.1)
            
            return True
            
        except Exception as e:
            print(f"Failed to start audio receiver: {e}")
            return False
        finally:
            self.cleanup()
    
    def stop_receiving(self):
        """Stop audio reception"""
        self.receiving = False
    
    def cleanup(self):
        """Clean up resources"""
        self.receiving = False
        self.sock.close()
        
        # Close CSV file
        if self.csv_file_handle:
            self.csv_file_handle.close()
            print(f"Metrics saved to: {self.csv_file}")
            
        print("Audio receiver stopped.")
    
    def list_audio_devices(self):
        """List available audio devices"""
        print("Available audio devices:")
        devices = sd.query_devices()
        for i, device in enumerate(devices):
            if device['max_output_channels'] > 0:
                print(f"  {i}: {device['name']} (outputs: {device['max_output_channels']})")

if __name__ == "__main__":
    # Create receiver instance with default config file
    receiver = UDPAudioReceiver()
    
    try:
        success = receiver.start_receiving()
        if not success:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        receiver.stop_receiving()
        receiver.cleanup()