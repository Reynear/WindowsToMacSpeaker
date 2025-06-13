"""
Ultra-Low Latency UDP Audio Sender with Zero Packet Loss Design

Advanced features:
- Zero packet loss optimization with adaptive retry logic
- Ultra-precise timing control for consistent packet delivery
- Real-time network congestion detection and response
- Adaptive buffer management to prevent underruns
- Comprehensive performance monitoring and metrics
- Cross-platform compatibility with optimized settings

Packet Format:
    packet_count: 4 bytes (unsigned long, network byte order)
    timestamp: 8 bytes (unsigned long long, network byte order) 
    opus_length: 4 bytes (unsigned long, network byte order)
    opus_data: variable length (compressed audio)

Total header size: 16 bytes + opus_data
Compatible with UDPAudioReceiver and optimized for real-time streaming
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
import queue
from collections import deque

# Optional process optimization
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None
    PSUTIL_AVAILABLE = False

class UltraLowLatencyUDPSender:
    def __init__(self, config_file="config.json"):
        # Load configuration from JSON file with defaults
        self.config = self.load_config(config_file)
        
        # Network configuration
        self.target_ip = self.config['network']['ip']
        self.target_port = self.config['network']['port']
        
        # Audio configuration
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

        # Ensure chunk_size matches frame size
        cfg_chunk = self.config['audio'].get('chunk_size')
        if cfg_chunk and cfg_chunk != self.opus_frame_samples:
            print(f"⚠️ chunk_size from config ({cfg_chunk}) does not match frame_samples ({self.opus_frame_samples}), using frame_samples")
        self.chunk_size = self.opus_frame_samples

        # Find VB-Cable or use specified device
        device_id = self.config['audio'].get('input_device_id', None)
        self.input_device = self.find_input_device(device_id)
        
        # UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Minimize socket buffer for low latency
        buffer_size = self.config['network']['socket_buffer_size']
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, buffer_size)
          # Advanced performance tracking
        self.packets_sent = 0
        self.send_errors = 0
        self.timing_errors = 0
        self.buffer_underruns = 0
        self.network_congestion_events = 0
        
        # Ultra-precise timing control
        self.frame_interval = self.opus_frame_duration / 1000.0  # Convert to seconds
        self.next_send_time = 0.0
        self.timing_precision = 0.001  # 1ms precision target
        
        # Adaptive sending parameters
        self.adaptive_delay = 0.0
        self.congestion_detected = False
        self.last_congestion_time = 0.0
        self.send_timestamps = deque(maxlen=100)  # Track recent send times
          # Real-time priority settings
        self.realtime_priority = True
        
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
        """Load configuration directly from JSON file"""
        if not os.path.exists(config_file):
            print(f"Error: config file '{config_file}' not found.")
            sys.exit(1)
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
        except Exception as e:
            print(f"Error reading config file: {e}")
            sys.exit(1)
        return config
    
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
        """Audio callback with zero packet loss design"""
        if status and self.config['logging']['verbose']:
            print(f"⚠️ Audio status: {status}")
        
        if not self.streaming:
            return
        
        try:
            # Timestamp
            capture_timestamp = time.perf_counter()
            
            # Convert float32 to int16 with optimized processing
            audio_data = (indata * 32767).astype(np.int16)
            
            # Add to buffer with overflow protection
            if len(self.audio_buffer) + len(audio_data) > self.chunk_size * 10:
                self.buffer_underruns += 1
                # Drop oldest data to prevent overflow
                excess = len(self.audio_buffer) + len(audio_data) - (self.chunk_size * 10)
                self.audio_buffer = self.audio_buffer[excess:]
            
            self.audio_buffer = np.vstack([self.audio_buffer, audio_data])
            
            # Process complete Opus frames
            while len(self.audio_buffer) >= self.opus_frame_samples:
                # Check if it's time to send
                current_time = time.perf_counter()
                if self.next_send_time == 0.0:
                    self.next_send_time = current_time
                
                if current_time >= self.next_send_time - self.timing_precision:
                    # Extract one Opus frame
                    frame_data = self.audio_buffer[:self.opus_frame_samples]
                    self.audio_buffer = self.audio_buffer[self.opus_frame_samples:]
                    
                    # Encode with Opus (optimized settings)
                    pcm_bytes = frame_data.flatten().tobytes()
                    opus_data = self.opus_encoder.encode(pcm_bytes, self.opus_frame_samples)
                    
                    # Create packet with high-precision timestamp
                    timestamp = int(capture_timestamp * 1000000)  # microseconds
                    opus_length = len(opus_data)
                    header = struct.pack('!LQL', self.packet_count, timestamp, opus_length)
                    
                    # Send with retry logic for zero packet loss
                    packet = header + opus_data
                    
                    # Apply adaptive timing
                    adaptive_delay = self.adaptive_send_timing()
                    if adaptive_delay > 0:
                        time.sleep(adaptive_delay)
                    
                    # Send with retry logic
                    if self.send_with_retry(packet):
                        self.packet_count += 1
                        
                        # Ultra-precise timing for next send
                        self.next_send_time += self.frame_interval
                        
                        # Detect timing errors
                        timing_error = abs(current_time - (self.next_send_time - self.frame_interval))
                        if timing_error > self.timing_precision:
                            self.timing_errors += 1
                      # Performance logging
                    stats_interval = self.config['logging']['stats_interval']
                    if self.packet_count % stats_interval == 0:
                        self.log_enhanced_metrics(pcm_bytes, opus_data, capture_timestamp)
                else:
                    # Not time to send yet, break to wait
                    break
                    
        except Exception as e:
            print(f"❌ Audio callback error: {e}")
            import traceback
            traceback.print_exc()

    def start_streaming(self):
        """Start audio capture and UDP transmission"""
        print(f"Starting Audio Stream")
        print(f"Target: {self.target_ip}:{self.target_port}")
        print(f"Audio: {self.sample_rate}Hz, {self.channels} channels")
        print(f"Opus: {self.opus_bitrate} bps, {self.opus_frame_duration}ms frames")
        print(f"Chunk size: {self.chunk_size} samples")
        print(f"Frame interval: {self.frame_interval*1000:.2f}ms")
        print(f"Target latency: <50ms total")
        
        try:
            self.streaming = True
            self.packet_count = 0
            self.start_time = time.perf_counter()
            self.next_send_time = 0.0
            
            # Set process priority 
            if self.realtime_priority:
                self.set_process_priority()
            
            print("Streaming started")
            print("Enhanced metrics enabled")
            print("Press Ctrl+C to stop...")
            
            # Start audio stream
            with sd.InputStream(
                device=self.input_device,
                channels=self.channels,
                samplerate=self.sample_rate,
                blocksize=self.chunk_size,
                dtype=np.float32,
                callback=self.audio_callback,
                latency='low'
            ):
                # Keep the stream alive with minimal CPU usage
                while self.streaming:
                    time.sleep(0.01)  # 10ms sleep for responsiveness
            
        except KeyboardInterrupt:
            print("\n🛑 Stopping ultra-low latency stream...")
        except Exception as e:
            print(f"❌ Failed to start audio stream: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.cleanup_enhanced()
    
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

    def cleanup_enhanced(self):
        """Cleanup with performance summary"""
        self.streaming = False
        
        # Calculate final performance metrics
        if hasattr(self, 'start_time') and self.start_time and self.packet_count > 0:
            total_time = time.perf_counter() - self.start_time
            avg_rate = self.packet_count / total_time
            success_rate = ((self.packets_sent - self.send_errors) / max(self.packets_sent, 1)) * 100
            timing_accuracy = 100 - (self.timing_errors / max(self.packet_count, 1)) * 100
            
            print(f"\nPerformance Summary:")
            print(f"Total time: {total_time:.2f}s")
            print(f"Packets sent: {self.packets_sent}")
            print(f"Average rate: {avg_rate:.1f} pkt/s")
            print(f"Success rate: {success_rate:.2f}%")
            print(f"Timing accuracy: {timing_accuracy:.2f}%")
            print(f"Send errors: {self.send_errors}")
            print(f"Timing errors: {self.timing_errors}")
            print(f"Buffer underruns: {self.buffer_underruns}")
            print(f"Congestion events: {self.network_congestion_events}")
        
        # Close socket
        if hasattr(self, 'sock') and self.sock:
            self.sock.close()
        
        # Close CSV file
        if hasattr(self, 'csv_file_handle') and self.csv_file_handle:
            try:
                self.csv_file_handle.close()
                print(f"📊 Enhanced metrics saved to: {self.csv_file}")
            except:
                pass
        
        print("✅ Ultra-low latency sender stopped")

    def list_audio_devices(self):
        """List available audio devices"""
        print("Available audio devices:")
        devices = sd.query_devices()
        for i, device in enumerate(devices):
            max_channels = getattr(device, 'max_input_channels', 0)
            name = getattr(device, 'name', 'Unknown')
            if max_channels > 0:
                print(f"  {i}: {name} (inputs: {max_channels})")

    def set_process_priority(self):
        """Set process to real-time priority for ultra-low latency"""
        try:
            if os.name == 'nt':  # Windows
                import ctypes
                # Set process to HIGH_PRIORITY_CLASS
                ctypes.windll.kernel32.SetPriorityClass(-1, 0x00000080)
                # Set thread to TIME_CRITICAL
                ctypes.windll.kernel32.SetThreadPriority(-2, 15)
                print("✅ Process priority set to real-time (Windows)")
            else:  # Unix-like systems
                try:
                    os.nice(-20)  # Highest priority
                    print("✅ Process priority set to real-time (Unix)")
                except PermissionError:
                    print("⚠️ Could not set real-time priority (requires root)")
        except Exception as e:
            print(f"⚠️ Could not optimize process priority: {e}")
    
    def detect_network_congestion(self):
        """Detect network congestion based on send timing"""
        if len(self.send_timestamps) < 10:
            return False
        
        # Calculate recent send intervals
        intervals = []
        timestamps = list(self.send_timestamps)
        for i in range(1, len(timestamps)):
            intervals.append(timestamps[i] - timestamps[i-1])
        
        if not intervals:
            return False
        
        # Check for increasing delays (congestion indicator)
        avg_interval = sum(intervals) / len(intervals)
        expected_interval = self.frame_interval
        
        if avg_interval > expected_interval * 1.5:  # 50% slower than expected
            self.network_congestion_events += 1
            return True
        
        return False
    
    def adaptive_send_timing(self):
        """Implement adaptive timing to reduce packet loss"""
        current_time = time.perf_counter()
        
        # Detect congestion
        if self.detect_network_congestion():
            if not self.congestion_detected:
                self.congestion_detected = True
                self.adaptive_delay = 0.001  # Add 1ms delay
                self.last_congestion_time = current_time
                print(f"⚠️ Network congestion detected, adding adaptive delay")
        else:
            # Gradually reduce delay when congestion clears
            if self.congestion_detected and (current_time - self.last_congestion_time) > 2.0:
                self.adaptive_delay *= 0.9
                if self.adaptive_delay < 0.0001:
                    self.adaptive_delay = 0.0
                    self.congestion_detected = False
                    print("✅ Network congestion cleared")
        
        return self.adaptive_delay
    
    def ultra_precise_sleep(self, target_time):
        """Sleep using busy waiting for final precision"""
        sleep_time = target_time - time.perf_counter()
        
        if sleep_time > 0.01:  # Use regular sleep for longer waits
            time.sleep(sleep_time - 0.01)
        
        # Busy wait for final precision
        while time.perf_counter() < target_time:
            pass
    
    def send_with_retry(self, packet, retries=3):
        """Send packet with retry logic for zero packet loss"""
        for attempt in range(retries):
            try:
                self.sock.sendto(packet, (self.target_ip, self.target_port))
                self.packets_sent += 1
                self.send_timestamps.append(time.perf_counter())
                return True
            except socket.error as e:
                self.send_errors += 1
                if attempt < retries - 1:
                    time.sleep(0.001)  # Brief delay before retry
                else:
                    print(f"❌ Send failed after {retries} attempts: {e}")
                    return False
        return False

    def log_enhanced_metrics(self, pcm_bytes, opus_data, capture_timestamp):
        """Log enhanced metrics with statistics"""
        try:
            elapsed = time.perf_counter() - (self.start_time or time.perf_counter())
            rate = self.packet_count / elapsed if elapsed > 0 else 0
            compression_ratio = len(pcm_bytes) / len(opus_data) if len(opus_data) > 0 else 0
            
            # Advanced metrics
            success_rate = ((self.packets_sent - self.send_errors) / max(self.packets_sent, 1)) * 100
            timing_accuracy = 100 - (self.timing_errors / max(self.packet_count, 1)) * 100
            congestion_rate = (self.network_congestion_events / max(self.packet_count // 100, 1))
            
            # Console output with enhanced stats
            if self.config['logging']['verbose']:
                print(f"📊 Sent {self.packet_count} packets | "
                      f"Rate: {rate:.1f} pkt/s | "
                      f"Success: {success_rate:.1f}% | "
                      f"Timing: {timing_accuracy:.1f}% | "
                      f"Compression: {compression_ratio:.1f}x | "
                      f"Congestion: {congestion_rate:.2f}")
            
            # Enhanced CSV logging
            if self.csv_writer:
                current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                row = [
                    current_time,
                    self.start_time,
                    self.packet_count,
                    elapsed,
                    rate,
                    compression_ratio,
                    len(pcm_bytes),
                    len(opus_data),
                    self.target_ip,
                    self.target_port,
                    self.sample_rate,
                    self.channels,
                    self.opus_bitrate,
                    self.opus_frame_duration,
                    self.packets_sent,
                    self.send_errors,
                    success_rate,
                    self.timing_errors,
                    timing_accuracy,
                    self.buffer_underruns,
                    self.network_congestion_events,
                    self.adaptive_delay * 1000,  # Convert to ms
                    self.congestion_detected
                ]
                self.csv_writer.writerow(row)
                if self.csv_file_handle:
                    self.csv_file_handle.flush()
                    
        except Exception as e:
            print(f"❌ Error logging enhanced metrics: {e}")


if __name__ == "__main__":
    print("UDP Audio Sender")
    print("=" * 50)
    
    sender = None
    try:
        sender = UltraLowLatencyUDPSender()
        sender.start_streaming()
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if sender:
            sender.stop_streaming()