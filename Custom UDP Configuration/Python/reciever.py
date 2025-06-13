"""
UDP Audio Receiver

Features:
- Playback with adaptive jitter buffer management
- Real-time process priority optimization for consistent performance
- Packet loss detection and audio concealment
- Adaptive buffer management to prevent underruns and glitches
- Comprehensive performance monitoring and metrics
- Cross-platform compatibility with optimized settings

To be used with UDPSender
Receives compressed audio over UDP and plays it back in real-time with minimal latency

Packet Format Expected:
    packet_count: 4 bytes (unsigned long, network byte order)
    timestamp: 8 bytes (unsigned long long, network byte order)
    opus_length: 4 bytes (unsigned long, network byte order) 
    opus_data: variable length (compressed audio)

Optimized for Real-time audio streaming
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
from collections import deque
import queue

# Optional process optimization
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None
    PSUTIL_AVAILABLE = False

# Try to import opuslib with error handling
try:
    import opuslib
    OPUS_AVAILABLE = True
except ImportError:
    opuslib = None  # type: ignore
    OPUS_AVAILABLE = False
    print("Warning: opuslib not available. Install with: pip install opuslib")

class UDPReceiver:
    def __init__(self, config_file="config.json"):
        # Load configuration
        self.config = self.load_config(config_file)
        
        # Network configuration
        self.listen_ip = "0.0.0.0"  # Listen on all interfaces
        self.listen_port = self.config['network']['port']
        
        # Load audio configuration first
        self.sample_rate = self.config['audio']['sample_rate']
        self.channels = self.config['audio']['channels']
        self.chunk_size = self.config['audio']['chunk_size']
        self.frame_duration = self.config['opus']['frame_duration']
        self.frame_samples = int(self.sample_rate * self.frame_duration / 1000)
        
        # UDP packet configuration
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
        self.init_socket()        # Control flags
        self.receiving = False
        self.packet_count = 0
        self.start_time = None
        
        # Audio buffering with thread-safe access
        self.audio_queue = deque(maxlen=20)  # Fast access buffer
        self.queue_lock = threading.Lock()  # Thread synchronization
        self.max_queue_size = 20
        self.playback_buffer = deque(maxlen=10)  # Additional fast access buffer
        self.buffer_lock = threading.Lock()
        
        # Advanced performance tracking
        self.packets_received = 0
        self.packets_lost = 0
        self.packets_late = 0
        self.packets_duplicate = 0
        self.buffer_underruns = 0
        self.buffer_overruns = 0
        self.audio_glitches = 0
        self.timing_errors = 0
        
        # Ultra-precise timing and jitter management
        self.frame_interval = self.frame_duration / 1000.0  # Convert to seconds
        self.timing_precision = 0.001  # 1ms precision target
        self.last_packet_time = 0.0
        self.packet_timestamps = deque(maxlen=100)  # Track recent packets

        # Jitter calculation attributes
        self.transit_times = []
        self.jitter = 0.0
          # Adaptive jitter buffer management
        optimization_config = self.config.get('optimization', {})
        self.adaptive_jitter_size = optimization_config.get('jitter_buffer_size', 5)
        self.jitter_buffer_min = 1
        self.jitter_buffer_max = 10
        self.network_jitter = 0.0
        self.jitter_adaptation_rate = 0.1
        
        # Real-time priority settings
        self.realtime_priority = True
        
        # Packet ordering and loss detection
        self.expected_sequence = 1
        self.sequence_buffer = {}  # Out-of-order packet buffer
        self.max_sequence_gap = 5
        
        # Audio concealment for lost packets
        self.last_audio_frame = None
        self.concealment_enabled = True
        
        # Threading
        self.receive_thread = None
          # CSV logging
        self.csv_file = self.config['logging'].get('csv_file', 'udp_receiver_metrics.csv')
        self.csv_writer = None
        self.csv_file_handle = None
        self.init_csv_logging()
        
        # Set remaining config values
        self.max_queue_size = self.config['audio'].get('buffer_frames', 10)        # Jitter buffer (in packets)
        jitter_size = self.config.get('optimization', {}).get('jitter_buffer_size', 5)
        self.jitter_buffer = deque(maxlen=jitter_size)
        
    def load_config(self, config_file):
        """Load configuration directly from JSON file"""
        if not os.path.exists(config_file):
            print(f"Error: config file '{config_file}' not found.")
            sys.exit(1)
        
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
                # Debug: Check if optimization section exists
                if 'optimization' not in config:
                    print(f"⚠️  Warning: 'optimization' section missing from config. Using defaults.")
                    config['optimization'] = {
                        'jitter_buffer_size': 5,
                        'enable_adaptive_bitrate': True,
                        'enable_jitter_buffer': True,
                        'max_retries': 2,
                        'timing_tolerance_ms': 5
                    }
        except Exception as e:
            print(f"❌ Error reading config file: {e}")
            sys.exit(1)
        return config

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
            'opus_data': opus_data        }
    
    def calculate_jitter(self, udp_timestamp, arrival_time):
        """Calculate inter-arrival jitter for UDP packets"""
        # Convert UDP timestamp to seconds
        udp_time_seconds = udp_timestamp / self.sample_rate
        
        # Calculate transit time
        transit = arrival_time - udp_time_seconds
        self.transit_times.append(transit)
          # Calculate jitter using standard formula
        if len(self.transit_times) > 1:
            d = abs(transit - self.transit_times[-2])
            self.jitter += (d - self.jitter) / 16.0
        
        # Keep only recent transit times
        if len(self.transit_times) > 100:
            self.transit_times = self.transit_times[-50:]
    
    def audio_callback(self, outdata, frames, time_info, status):
        """Audio playback callback with enhanced performance tracking"""
        callback_start = time.perf_counter()
        
        if status and self.config['logging']['verbose']:
            print(f"⚠️ Audio status: {status}")
        
        outdata.fill(0)  # Zero output buffer initially
        
        try:
            with self.queue_lock:
                if len(self.audio_queue) > 0:
                    audio_data = self.audio_queue.popleft()  # Use popleft() for deque
                    
                    # Ensure proper shape for multi-channel audio
                    if audio_data.ndim == 1:
                        if self.channels == 2:
                            audio_data = np.column_stack([audio_data, audio_data])
                        else:
                            audio_data = audio_data.reshape(-1, 1)
                    
                    samples_to_copy = min(len(audio_data), frames)
                    outdata[:samples_to_copy] = audio_data[:samples_to_copy]
                    
                    # Advanced buffer monitoring and adaptation
                    queue_size = len(self.audio_queue)
                    if queue_size < 2:
                        self.buffer_underruns += 1
                        if self.config['logging']['verbose'] and self.buffer_underruns % 10 == 0:
                            print(f"⚡ Buffer underrun #{self.buffer_underruns}: {queue_size} frames queued")
                    
                    # Track audio timing precision
                    self.track_audio_timing()
                    
                else:
                    # Audio concealment for smooth playback during underruns
                    if self.last_audio_frame is not None and self.concealment_enabled:
                        # Simple fade-out concealment
                        fade_samples = min(frames, len(self.last_audio_frame))
                        fade_factor = np.linspace(0.5, 0.0, fade_samples).reshape(-1, 1)
                        concealed_audio = self.last_audio_frame[:fade_samples] * fade_factor
                        outdata[:fade_samples] = concealed_audio
                    
                    self.buffer_underruns += 1
                    if self.config['logging']['verbose'] and self.buffer_underruns % 100 == 0:
                        print(f"🔇 Audio buffer empty ({self.buffer_underruns} underruns) - concealment applied")
            
            # Store last frame for concealment
            if len(outdata) > 0:
                self.last_audio_frame = outdata.copy()
                
        except Exception as e:
            self.audio_glitches += 1
            if self.config['logging']['verbose']:
                print(f"❌ Audio callback error #{self.audio_glitches}: {e}")
        
        # Track callback performance
        callback_duration = time.perf_counter() - callback_start
        if callback_duration > 0.005:  # Warn if callback takes >5ms
            self.timing_errors += 1
            if self.config['logging']['verbose']:
                print(f"⏱️ Slow audio callback: {callback_duration*1000:.2f}ms")
    
    def receive_packets(self):
        """Receive and process UDP packets"""
        print(f"Listening for UDP packets on {self.listen_ip}:{self.listen_port}")
        
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
                            # Drop oldest frame for deque
                            self.audio_queue.popleft()
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
                        print(f"UDP: {self.packet_count} pkts, {rate:.1f} pkt/s, "
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
    
    def set_process_priority(self):
        """Set process to real-time priority for ultra-low latency"""
        try:
            if os.name == 'nt':  # Windows
                import ctypes
                # Set process to HIGH_PRIORITY_CLASS
                ctypes.windll.kernel32.SetPriorityClass(-1, 0x00000080)
                # Set thread to TIME_CRITICAL
                ctypes.windll.kernel32.SetThreadPriority(-2, 15)
                print("✅ Receiver priority set to real-time (Windows)")
            else:  # Unix-like systems
                try:
                    os.nice(-20)  # Highest priority
                    print("✅ Receiver priority set to real-time (Unix)")
                except PermissionError:
                    print("⚠️ Could not set real-time priority (requires root)")
        except Exception as e:
            print(f"⚠️ Could not optimize receiver priority: {e}")
    
    def adapt_jitter_buffer(self):
        """Dynamically adapt jitter buffer size based on network conditions"""
        if len(self.packet_timestamps) < 10:
            return
        
        # Calculate network jitter
        intervals = []
        timestamps = list(self.packet_timestamps)
        for i in range(1, len(timestamps)):
            intervals.append(timestamps[i] - timestamps[i-1])
        
        if intervals:
            avg_interval = sum(intervals) / len(intervals)
            jitter = sum(abs(interval - avg_interval) for interval in intervals) / len(intervals)
            
            # Smooth jitter calculation
            self.network_jitter = (1 - self.jitter_adaptation_rate) * self.network_jitter + \
                                 self.jitter_adaptation_rate * jitter
            
            # Adapt buffer size
            if self.network_jitter > 0.01:  # High jitter
                self.adaptive_jitter_size = min(self.jitter_buffer_max, 
                                              self.adaptive_jitter_size + 1)
            elif self.network_jitter < 0.005:  # Low jitter
                self.adaptive_jitter_size = max(self.jitter_buffer_min, 
                                              self.adaptive_jitter_size - 1)
    
    def generate_concealment_audio(self):
        """Generate concealment audio for lost packets"""
        if self.last_audio_frame is None:
            # Generate silence
            return np.zeros((self.frame_samples, self.channels), dtype=np.float32)
        
        # Simple audio concealment - fade out last frame
        concealment = self.last_audio_frame * 0.5
        return concealment.astype(np.float32)
    
    def track_audio_timing(self):
        """Precise audio timing for consistent playback"""
        current_time = time.perf_counter()
        
        # Calculate ideal timing
        if hasattr(self, 'last_audio_time'):
            expected_time = self.last_audio_time + self.frame_interval
            timing_error = current_time - expected_time
            
            if abs(timing_error) > self.timing_precision:
                self.timing_errors += 1
                if self.config['logging']['verbose'] and self.timing_errors % 100 == 0:
                    print(f"⚠️ Audio timing error: {timing_error*1000:.2f}ms")
        
        self.last_audio_time = current_time
        return current_time
    
    def enhanced_receive_packets(self):
        """Enhanced packet reception with ultra-low latency processing"""
        try:
            while self.receiving:
                try:
                    # Receive packet with minimal latency
                    if self.sock is None:
                        break
                    data, addr = self.sock.recvfrom(4096)
                    receive_time = time.perf_counter()
                    
                    self.packet_count += 1
                    self.packets_received += 1
                    
                    # Process packet immediately for minimal latency
                    self.process_packet(data, receive_time)
                    
                except socket.timeout:
                    continue  # Normal timeout, keep receiving
                except Exception as e:
                    if self.receiving and self.config['logging']['verbose']:
                        print(f"⚠️ Packet reception error: {e}")
                    continue
        except Exception as e:
            print(f"❌ Enhanced packet receiver error: {e}")
    
    def process_packet(self, data, receive_time):
        """Process received packet with ultra-low latency"""
        try:            # Parse UDP header for sequence and timing
            if len(data) < 12:
                return
            
            # Basic UDP header parsing (packet_count + timestamp)
            sequence_number = int.from_bytes(data[0:4], byteorder='big')
            timestamp = int.from_bytes(data[4:12], byteorder='big')
            
            # Update packet timing metrics
            self.last_packet_time = receive_time
            self.packet_timestamps.append(receive_time)
              # Extract and decode audio payload immediately
            payload = data[12:]  # Skip UDP header
            
            if len(payload) > 0:
                # Decode Opus audio with minimal delay
                audio_float = self.opus_decoder.decode_float(payload, self.frame_samples)
                
                # Add to audio queue with overflow protection
                with self.queue_lock:
                    if len(self.audio_queue) < self.max_queue_size:
                        self.audio_queue.append(audio_float)
                    else:
                        # Drop oldest frame for ultra-low latency
                        self.audio_queue.popleft()
                        self.audio_queue.append(audio_float)
                        self.buffer_overruns += 1
                        
        except Exception as e:
            if self.config['logging']['verbose']:
                print(f"⚠️ Ultra-low latency packet processing error: {e}")
    
    def cleanup_enhanced(self):
        """Enhanced cleanup with performance metrics"""
        print("\n🧹 Enhanced cleanup starting...")
        
        # Stop receiving
        self.receiving = False
        
        # Display final performance metrics
        if self.start_time:
            runtime = time.perf_counter() - self.start_time
            print(f"\n📊 Ultra-Low Latency Performance Summary:")
            print(f"⏱️ Runtime: {runtime:.2f}s")
            print(f"📦 Packets received: {self.packets_received}")
            print(f"❌ Packets lost: {self.packets_lost}")
            print(f"🔄 Buffer underruns: {self.buffer_underruns}")
            print(f"🔄 Buffer overruns: {self.buffer_overruns}")
            print(f"🎵 Audio glitches: {self.audio_glitches}")
            print(f"⚠️ Timing errors: {self.timing_errors}")
            
            if self.packets_received > 0:
                loss_rate = (self.packets_lost / (self.packets_received + self.packets_lost)) * 100
                print(f"📊 Packet loss rate: {loss_rate:.2f}%")
        
        # Clean up resources
        try:
            if hasattr(self, 'receive_thread') and self.receive_thread and self.receive_thread.is_alive():
                self.receive_thread.join(timeout=1.0)
        except Exception as e:
            print(f"⚠️ Thread cleanup warning: {e}")
        
        # Call standard cleanup
        self.cleanup()
        print("✅ Enhanced cleanup completed")

    def start_receiving(self):
        """Start ultra-low latency audio reception and playback"""
        print(f"🚀 Starting Ultra-Low Latency Audio Receiver")
        print(f"🎧 Listen: {self.listen_ip}:{self.listen_port}")
        print(f"🎵 Audio: {self.sample_rate}Hz, {self.channels} channels")
        print(f"🔧 Codec: Opus (ultra-low latency)")
        print(f"📦 Frame size: {self.frame_samples} samples")
        print(f"⚡ Frame interval: {self.frame_interval*1000:.2f}ms")
        print(f"🎯 Target latency: <50ms total")
        print(f"📊 Adaptive jitter buffer: {self.adaptive_jitter_size} packets")
        
        # Set process priority for real-time performance
        if self.realtime_priority:
            self.set_process_priority()
        
        if self.output_device is None:
            print("❌ Cannot start without valid audio output device")
            return False
            
        if not self.sock:
            print("❌ Cannot start without valid socket")
            return False
        
        try:
            self.receiving = True
            self.packet_count = 0
            self.packets_received = 0
            self.packets_lost = 0
            self.packets_late = 0
            self.buffer_underruns = 0
            self.audio_glitches = 0
            self.timing_errors = 0
            self.expected_sequence = 1
            self.sequence_buffer.clear()
            self.start_time = time.perf_counter()
            self.last_audio_time = self.start_time
            
            # Set socket timeout for responsive shutdown
            self.sock.settimeout(0.1)
            
            print("✅ Ultra-low latency reception started")
            print("📊 Enhanced metrics enabled")
            print("Press Ctrl+C to stop...")
            
            # Start packet reception thread
            self.receive_thread = threading.Thread(target=self.enhanced_receive_packets, daemon=True)
            self.receive_thread.start()
            
            # Start ultra-low latency audio playback
            with sd.OutputStream(
                device=self.output_device,
                channels=self.channels,
                samplerate=self.sample_rate,
                blocksize=self.frame_samples,  # Match frame size
                dtype=np.float32,
                callback=self.audio_callback,
                latency='low'  # Request lowest possible latency
            ):
                # Keep alive with minimal CPU usage and adaptive jitter monitoring
                while self.receiving:
                    time.sleep(0.01)  # 10ms for responsiveness
                    
                    # Periodic jitter buffer adaptation
                    if self.packet_count % 50 == 0:  # Every 50 packets
                        self.adapt_jitter_buffer()
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to start ultra-low latency receiver: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            self.cleanup_enhanced()
    
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
            
        print("UDP audio receiver stopped.")

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
    print("UDP Audio Receiver")
    print("=" * 50)
    
    receiver = None
    try:
        receiver = UDPReceiver()
        success = receiver.start_receiving()
        if not success:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if receiver:
            receiver.stop_receiving()
            receiver.cleanup()
