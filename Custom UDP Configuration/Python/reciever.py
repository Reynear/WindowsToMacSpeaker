"""
UDP Audio Receiver with Opus Decompression

Compatible with UDPAudioSender
Receives compressed audio over UDP and plays it back in real-time

Packet Format Expected:
    packet_count: 4 bytes (unsigned long, network byte order)
    timestamp: 8 bytes (unsigned long long, network byte order)
    opus_length: 4 bytes (unsigned long, network byte order) 
    opus_data: variable length (compressed audio)
"""

import socket
import sounddevice as sd
import threading
import time
import struct
import numpy as np
import sys
import json
import os
import csv
from datetime import datetime

# Try to import opuslib with error handling
try:
    import opuslib
    OPUS_AVAILABLE = True
except ImportError:
    opuslib = None  # type: ignore
    OPUS_AVAILABLE = False
    print("Warning: opuslib not available. Install with: pip install opuslib")

class UDPAudioReceiver:
    def __init__(self, config_file="config.json"):
        # Load configuration
        self.config = self.load_config(config_file)
        
        # Network configuration
        self.listen_ip = "0.0.0.0"  # Listen on all interfaces
        self.listen_port = self.config['network']['port']
        
        # Audio configuration
        self.sample_rate = self.config['audio']['sample_rate']
        self.channels = self.config['audio']['channels']
        self.chunk_size = self.config['audio']['chunk_size']        # UDP packet configuration (instead of RTP)
        self.packet_header_size = 16  # packet_count(4) + timestamp(8) + opus_length(4)
          # Initialize Opus decoder
        if OPUS_AVAILABLE and opuslib is not None:
            try:
                self.opus_decoder = opuslib.Decoder(
                    fs=self.sample_rate,
                    channels=self.channels
                )
                print(f"Opus decoder initialized: {self.sample_rate}Hz, {self.channels} channels")
            except Exception as e:
                print(f"Error initializing Opus decoder: {e}")
                sys.exit(1)
        else:
            print("Error: Opus decoder not available")
            sys.exit(1)
        
        # Find output device
        device_id = self.config['audio'].get('output_device_id', None)
        self.output_device = self.find_output_device(device_id)
        
        # Initialize socket
        self.sock = None
        self.init_socket()
        
        # Control flags
        self.receiving = False
        self.packet_count = 0
        self.start_time = None
        
        # Audio playback buffer
        self.audio_queue = []
        self.queue_lock = threading.Lock()
        self.max_queue_size = self.config['audio']['buffer_frames']
        
        # RTP packet tracking
        self.lost_packets = 0
        self.last_sequence = None
        self.out_of_order_packets = 0
        self.duplicate_packets = 0
        self.received_sequences = set()
        
        # Jitter calculation
        self.transit_times = []
        self.jitter = 0.0
        
        # Threading
        self.receive_thread = None
          # CSV logging
        self.csv_file = self.config['logging'].get('csv_file', 'udp_receiver_metrics.csv')
        self.csv_writer = None
        self.csv_file_handle = None
        self.init_csv_logging()
        
    def load_config(self, config_file):
        """Load configuration from JSON file with defaults"""
        default_config = {
            "network": {
                "port": 5004,
                "socket_buffer_size": 65536
            },
            "audio": {
                "sample_rate": 48000,
                "channels": 2,
                "chunk_size": 1024,
                "buffer_frames": 10,
                "output_device_id": None,
                "output_device_name": "default"
            },
            "opus": {
                "bitrate": 128000,
                "frame_duration": 20
            },
            "logging": {
                "stats_interval": 100,
                "verbose": True,
                "csv_file": "udp_receiver_metrics.csv",
                "enable_csv": True
            }
        }
        
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    file_config = json.load(f)
                    
                # Merge configs
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
            print(f"Config file {config_file} not found, creating default")
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
    
    def init_socket(self):
        """Initialize UDP socket"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            
            # Set socket options
            buffer_size = self.config['network']['socket_buffer_size']
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, buffer_size)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # Bind to port
            self.sock.bind((self.listen_ip, self.listen_port))
            print(f"Socket bound to {self.listen_ip}:{self.listen_port}")
            
        except Exception as e:
            print(f"Error initializing socket: {e}")
            if self.sock:
                self.sock.close()
                self.sock = None
            raise
    
    def init_csv_logging(self):
        """Initialize CSV logging"""
        if not self.config['logging']['enable_csv']:
            return
            
        try:
            file_exists = os.path.exists(self.csv_file)
            
            self.csv_file_handle = open(self.csv_file, 'a', newline='', encoding='utf-8')
            self.csv_writer = csv.writer(self.csv_file_handle)
            
            if not file_exists:
                headers = [
                    'timestamp',
                    'session_start',
                    'packet_count',
                    'elapsed_time',
                    'packet_rate',
                    'packets_lost',
                    'loss_rate_percent',
                    'out_of_order',
                    'duplicates',
                    'jitter_ms',
                    'queue_size',
                    'listen_port',
                    'sample_rate',
                    'channels'
                ]
                self.csv_writer.writerow(headers)
                self.csv_file_handle.flush()
                
            print(f"CSV logging enabled: {self.csv_file}")
            
        except Exception as e:
            print(f"Error initializing CSV logging: {e}")
            self.csv_writer = None
            if self.csv_file_handle:
                try:
                    self.csv_file_handle.close()
                except:
                    pass
                self.csv_file_handle = None

    def log_metrics_to_csv(self, elapsed, rate, loss_rate, queue_size):
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
                self.lost_packets,
                loss_rate,
                self.out_of_order_packets,
                self.duplicate_packets,
                self.jitter * 1000,  # Convert to milliseconds
                queue_size,
                self.listen_port,
                self.sample_rate,                self.channels
            ]
            self.csv_writer.writerow(row)
            if self.csv_file_handle:
                self.csv_file_handle.flush()
            
        except Exception as e:
            print(f"Error writing to CSV: {e}")
    
    def find_output_device(self, device_id=None):
        """Find best output device"""
        try:
            devices = sd.query_devices()
        except Exception as e:
            print(f"Error querying audio devices: {e}")
            return None
        
        # If specific device ID provided, use it
        if device_id is not None:
            try:
                device_info = sd.query_devices(device_id)
                max_channels = getattr(device_info, 'max_output_channels', 0)
                name = getattr(device_info, 'name', 'Unknown')
                if max_channels > 0:
                    print(f"Using specified device {device_id}: {name}")
                    return device_id
            except Exception as e:
                print(f"Device {device_id} not found: {e}")
        
        # Look for configured device name
        device_name = self.config['audio']['output_device_name']
        if device_name != "default":
            for i, device in enumerate(devices):
                device_name_attr = getattr(device, 'name', '')
                max_channels = getattr(device, 'max_output_channels', 0)
                if device_name.lower() in device_name_attr.lower():
                    if max_channels > 0:
                        print(f"Found audio device: {device_name_attr}")
                        return i
        
        # Fallback to default output
        try:
            default_output = sd.default.device[1]
            if default_output is not None:
                device_info = sd.query_devices(default_output)
                name = getattr(device_info, 'name', 'Unknown')
                print(f"Using default output: {name}")
                return default_output
        except Exception as e:
            print(f"Error getting default device: {e}")
            
        print("Error: No suitable output device found.")
        self.list_audio_devices()
        return None

    def parse_udp_packet(self, packet):
        """Parse simple UDP packet: packet_count(4) + timestamp(8) + opus_length(4) + opus_data"""
        if len(packet) < self.packet_header_size:
            return None
            
        # Parse header: packet_count(4) + timestamp(8) + opus_length(4)
        header = struct.unpack('!LQL', packet[:self.packet_header_size])
        
        packet_count = header[0]
        timestamp = header[1]
        opus_length = header[2]
        
        # Validate opus_length
        expected_total_length = self.packet_header_size + opus_length
        if len(packet) != expected_total_length:
            return None
            
        opus_data = packet[self.packet_header_size:self.packet_header_size + opus_length]
        
        return {
            'packet_count': packet_count,
            'timestamp': timestamp,
            'opus_length': opus_length,
            'opus_data': opus_data
        }
    
    def calculate_jitter(self, rtp_timestamp, arrival_time):
        """Calculate inter-arrival jitter (RFC 3550)"""
        # Convert RTP timestamp to seconds (assuming 48kHz sample rate)
        rtp_time_seconds = rtp_timestamp / self.sample_rate
        
        # Calculate transit time
        transit = arrival_time - rtp_time_seconds
        self.transit_times.append(transit)
        
        # Calculate jitter using RFC 3550 formula
        if len(self.transit_times) > 1:
            d = abs(transit - self.transit_times[-2])
            self.jitter += (d - self.jitter) / 16.0
        
        # Keep only recent transit times
        if len(self.transit_times) > 100:
            self.transit_times = self.transit_times[-50:]
    
    def audio_callback(self, outdata, frames, time_info, status):
        """Audio playback callback"""
        if status and self.config['logging']['verbose']:
            print(f"Audio status: {status}")
        
        outdata.fill(0)
        
        try:
            with self.queue_lock:
                if len(self.audio_queue) > 0:
                    audio_data = self.audio_queue.pop(0)
                    
                    # Ensure proper shape
                    if audio_data.ndim == 1:
                        if self.channels == 2:
                            audio_data = np.column_stack([audio_data, audio_data])
                        else:
                            audio_data = audio_data.reshape(-1, 1)
                    
                    samples_to_copy = min(len(audio_data), frames)
                    outdata[:samples_to_copy] = audio_data[:samples_to_copy]
                    
                    # Buffer underrun warning
                    if len(self.audio_queue) < 2:
                        if self.config['logging']['verbose']:
                            print(f"Buffer underrun: {len(self.audio_queue)} frames queued")
                            
        except Exception as e:
            if self.config['logging']['verbose']:
                print(f"Error in audio callback: {e}")
    
    def receive_packets(self):
        """Receive and process RTP packets"""
        print(f"Listening for RTP packets on {self.listen_ip}:{self.listen_port}")
        
        while self.receiving:
            try:
                if not self.sock:
                    break
                    
                # Receive packet
                packet, addr = self.sock.recvfrom(65536)
                arrival_time = time.time()
                  # Parse UDP packet
                udp_info = self.parse_udp_packet(packet)
                if not udp_info:
                    continue
                
                # Track packet statistics
                packet_count = udp_info['packet_count']
                
                # Check for duplicates
                if packet_count in self.received_sequences:
                    self.duplicate_packets += 1
                    continue                    
                self.received_sequences.add(packet_count)
                
                # Check for lost packets
                if self.last_sequence is not None:
                    expected_sequence = self.last_sequence + 1
                    if packet_count != expected_sequence:
                        if packet_count < expected_sequence:
                            # Out of order packet
                            self.out_of_order_packets += 1
                        else:
                            # Lost packets
                            lost = packet_count - expected_sequence
                            self.lost_packets += lost
                            if self.config['logging']['verbose']:
                                print(f"Lost {lost} packets (expected {expected_sequence}, got {packet_count})")
                
                self.last_sequence = packet_count
                
                # Calculate jitter
                self.calculate_jitter(udp_info['timestamp'], arrival_time)
                
                # Decode Opus payload
                try:
                    opus_data = udp_info['opus_data']
                    # Calculate frame size from opus frame duration (default 20ms)
                    frame_size = int(self.sample_rate * 0.02)  # 20ms frame
                    pcm_data = self.opus_decoder.decode(opus_data, frame_size=frame_size)
                    
                    # Convert to numpy array
                    audio_array = np.frombuffer(pcm_data, dtype=np.int16)
                    audio_float = audio_array.astype(np.float32) / 32767.0
                    
                    # Add to playback queue
                    with self.queue_lock:
                        if len(self.audio_queue) < self.max_queue_size:
                            self.audio_queue.append(audio_float)
                        else:
                            # Drop oldest frame
                            self.audio_queue.pop(0)
                            self.audio_queue.append(audio_float)
                            
                except Exception as e:
                    if self.config['logging']['verbose']:
                        print(f"Opus decode error: {e}")
                    continue
                
                self.packet_count += 1
                  # Statistics and logging
                stats_interval = self.config['logging']['stats_interval']
                if self.packet_count % stats_interval == 0:
                    elapsed = time.time() - (self.start_time or time.time())
                    rate = self.packet_count / elapsed if elapsed > 0 else 0
                    total_packets = self.packet_count + self.lost_packets
                    loss_rate = (self.lost_packets / total_packets) * 100 if total_packets > 0 else 0
                    
                    with self.queue_lock:
                        queue_size = len(self.audio_queue)
                    
                    if self.config['logging']['verbose']:
                        print(f"RTP: {self.packet_count} pkts, {rate:.1f} pkt/s, "
                              f"loss: {loss_rate:.2f}%, jitter: {self.jitter*1000:.1f}ms, "
                              f"queue: {queue_size}")
                    
                    self.log_metrics_to_csv(elapsed, rate, loss_rate, queue_size)
                  # Clean up old sequence numbers to prevent memory growth
                if len(self.received_sequences) > 1000:
                    # Keep only recent sequences
                    recent_sequences = set()
                    for seq in self.received_sequences:
                        if abs(seq - packet_count) < 500:
                            recent_sequences.add(seq)
                    self.received_sequences = recent_sequences
                
            except socket.timeout:
                continue
            except OSError as e:
                if self.receiving:
                    print(f"Socket error: {e}")
                break
            except Exception as e:
                if self.receiving:
                    print(f"Error receiving packet: {e}")
                continue
    
    def start_receiving(self):
        """Start RTP reception and audio playback"""
        print(f"Starting RTP audio receiver")
        print(f"Listen: {self.listen_ip}:{self.listen_port}")
        print(f"Audio: {self.sample_rate}Hz, {self.channels} channels")
        print(f"Codec: Opus (compressed UDP)")
        
        if self.output_device is None:
            print("Cannot start without valid audio output device")
            return False
            
        if not self.sock:
            print("Cannot start without valid socket")
            return False
        
        try:
            self.receiving = True
            self.packet_count = 0
            self.lost_packets = 0
            self.out_of_order_packets = 0
            self.duplicate_packets = 0
            self.last_sequence = None
            self.received_sequences.clear()
            self.start_time = time.time()
            
            # Set socket timeout
            self.sock.settimeout(1.0)
            
            print("Reception started. Press Ctrl+C to stop...")
            
            # Start packet reception thread
            self.receive_thread = threading.Thread(target=self.receive_packets)
            self.receive_thread.daemon = True
            self.receive_thread.start()
            
            # Start audio playback
            with sd.OutputStream(
                device=self.output_device,
                channels=self.channels,
                samplerate=self.sample_rate,
                blocksize=self.chunk_size,
                dtype=np.float32,
                callback=self.audio_callback,
                latency='low'
            ):
                while self.receiving:
                    time.sleep(0.1)
            
            return True
            
        except Exception as e:
            print(f"Failed to start RTP receiver: {e}")
            return False
        finally:
            self.cleanup()
    
    def stop_receiving(self):
        """Stop reception"""
        self.receiving = False
        
        if self.receive_thread and self.receive_thread.is_alive():
            self.receive_thread.join(timeout=2.0)
    
    def cleanup(self):
        """Clean up resources"""
        self.receiving = False
        
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None
        
        if self.csv_file_handle:
            try:
                self.csv_file_handle.close()
                print(f"Metrics saved to: {self.csv_file}")
            except:
                pass
            self.csv_file_handle = None
            self.csv_writer = None
            
        print("RTP audio receiver stopped.")

    def list_audio_devices(self):
        """List available audio devices"""
        try:
            print("Available audio devices:")
            devices = sd.query_devices()
            for i, device in enumerate(devices):
                max_channels = getattr(device, 'max_output_channels', 0)
                name = getattr(device, 'name', 'Unknown')
                if max_channels > 0:
                    print(f"  {i}: {name} (outputs: {max_channels})")
        except Exception as e:
            print(f"Error listing audio devices: {e}")

if __name__ == "__main__":
    try:
        receiver = UDPAudioReceiver()
    except Exception as e:
        print(f"Failed to initialize RTP receiver: {e}")
        sys.exit(1)
    
    try:
        success = receiver.start_receiving()
        if not success:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\nStopping...")
    except Exception as e:
        print(f"Unexpected error: {e}")
    finally:
        receiver.stop_receiving()
        receiver.cleanup()
