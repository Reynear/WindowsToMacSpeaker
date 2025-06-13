"""
Zero Packet Loss UDP Audio Receiver - Optimized for Glitch-Free Playback

Key improvements:
1. Adaptive jitter buffer to handle network variations
2. Packet loss detection and concealment
3. Out-of-order packet reordering
4. Smooth audio playback with gap filling
5. Real-time latency monitoring
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
import queue
from collections import deque

# Import opuslib with fallback
try:
    import opuslib
    OPUS_AVAILABLE = True
except ImportError:
    opuslib = None
    OPUS_AVAILABLE = False
    print("Warning: opuslib not available")

class ZeroLossUDPReceiver:
    def __init__(self, config_file="config.json"):
        self.config = self.load_config(config_file)
        
        # Network settings
        self.listen_port = self.config['network']['port']
        
        # Audio settings
        self.sample_rate = self.config['audio']['sample_rate']
        self.channels = self.config['audio']['channels']
        self.frame_duration = 20  # 20ms
        self.frame_samples = int(self.sample_rate * self.frame_duration / 1000)
          # Initialize Opus decoder
        if OPUS_AVAILABLE and opuslib is not None:
            self.opus_decoder = opuslib.Decoder(
                fs=self.sample_rate,
                channels=self.channels
            )
        else:
            self.opus_decoder = None
            print("Running without Opus decoding")
        
        # UDP socket setup
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
        self.sock.bind(("0.0.0.0", self.listen_port))
        self.sock.settimeout(0.1)  # 100ms timeout for responsive shutdown
        
        # Adaptive jitter buffer
        self.jitter_buffer = {}  # packet_count -> (timestamp, audio_data)
        self.jitter_buffer_size = 5  # Start with 5 packet buffer (100ms)
        self.max_jitter_buffer = 10  # Max 10 packets (200ms)
        
        # Packet ordering
        self.expected_packet = 1
        self.last_played_packet = 0
        
        # Audio playback buffer
        self.playback_queue = queue.Queue(maxsize=20)
        
        # Performance tracking
        self.packets_received = 0
        self.packets_lost = 0
        self.packets_late = 0
        self.packets_duplicate = 0
        self.buffer_underruns = 0
        
        # Timing
        self.receiving = False
        self.start_time = 0.0
        
        # CSV logging
        self.setup_logging()
        
    def load_config(self, config_file):
        """Load configuration"""
        defaults = {
            "network": {"port": 5004},
            "audio": {"sample_rate": 48000, "channels": 2},
            "logging": {"csv_file": "zero_loss_receiver_metrics.csv"}
        }
        
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                user_config = json.load(f)
                defaults.update(user_config)
        
        return defaults
    
    def setup_logging(self):
        """Setup CSV logging"""
        try:
            self.csv_file = open(self.config['logging']['csv_file'], 'w', newline='')
            self.csv_writer = csv.writer(self.csv_file)
            self.csv_writer.writerow([
                'timestamp', 'packets_received', 'packets_lost', 'loss_percentage',
                'packets_late', 'duplicates', 'buffer_underruns', 'jitter_buffer_size',
                'playback_queue_size', 'expected_packet'
            ])
        except Exception as e:
            print(f"CSV logging disabled: {e}")
            self.csv_writer = None
    
    def audio_callback(self, outdata, frames, time_info, status):
        """Audio output callback with underrun protection"""
        if status:
            print(f"Audio status: {status}")
        
        try:
            # Get audio data from playback queue
            audio_data = self.playback_queue.get_nowait()
            
            # Ensure correct length
            if len(audio_data) == frames:
                outdata[:] = audio_data
            else:
                # Pad or truncate as needed
                if len(audio_data) < frames:
                    padded = np.zeros((frames, self.channels), dtype=np.float32)
                    padded[:len(audio_data)] = audio_data
                    outdata[:] = padded
                else:
                    outdata[:] = audio_data[:frames]
                    
        except queue.Empty:
            # Buffer underrun - output silence
            outdata.fill(0)
            self.buffer_underruns += 1
            if self.buffer_underruns % 10 == 1:
                print(f"Buffer underrun #{self.buffer_underruns}")
    
    def decode_audio(self, opus_data):
        """Decode Opus audio data"""
        if self.opus_decoder and opus_data:
            try:
                decoded = self.opus_decoder.decode(opus_data, self.frame_samples)
                # Convert to float32 and reshape
                audio_array = np.frombuffer(decoded, dtype=np.int16)
                audio_array = audio_array.reshape(-1, self.channels)
                return audio_array.astype(np.float32) / 32768.0
            except Exception as e:
                print(f"Decode error: {e}")
                return None
        else:
            # Generate silence if no decoder
            return np.zeros((self.frame_samples, self.channels), dtype=np.float32)
    
    def handle_packet_loss(self, missing_packet):
        """Handle missing packets with concealment"""
        # Generate silence for missing packet
        silence = np.zeros((self.frame_samples, self.channels), dtype=np.float32)
        
        try:
            self.playback_queue.put_nowait(silence)
        except queue.Full:
            # Queue full - skip this concealment
            pass
        
        self.packets_lost += 1
        print(f"Packet loss concealment for packet {missing_packet}")
    
    def process_jitter_buffer(self):
        """Process jitter buffer and output packets in order"""
        while self.receiving:
            current_time = time.time()
            
            # Check if we have the next expected packet
            if self.expected_packet in self.jitter_buffer:
                # Found expected packet
                timestamp, audio_data = self.jitter_buffer.pop(self.expected_packet)
                
                # Decode and queue for playback
                decoded_audio = self.decode_audio(audio_data)
                if decoded_audio is not None:
                    try:
                        self.playback_queue.put_nowait(decoded_audio)
                        self.last_played_packet = self.expected_packet
                    except queue.Full:
                        # Playback queue full - drop packet
                        pass
                
                self.expected_packet += 1
                
            else:
                # Missing packet - check if we should wait or concealment
                buffer_delay = len(self.jitter_buffer) * self.frame_duration / 1000.0
                
                if buffer_delay > self.jitter_buffer_size * self.frame_duration / 1000.0:
                    # Waited long enough - do packet loss concealment
                    self.handle_packet_loss(self.expected_packet)
                    self.expected_packet += 1
                else:
                    # Wait a bit more
                    time.sleep(0.005)  # 5ms
            
            # Adaptive jitter buffer sizing
            if len(self.jitter_buffer) > self.jitter_buffer_size:
                # Increase buffer size if we consistently have many packets
                if self.jitter_buffer_size < self.max_jitter_buffer:
                    self.jitter_buffer_size += 1
                    print(f"Increased jitter buffer to {self.jitter_buffer_size}")
            elif len(self.jitter_buffer) == 0 and self.jitter_buffer_size > 3:
                # Decrease buffer size if consistently empty
                self.jitter_buffer_size = max(3, self.jitter_buffer_size - 1)
                print(f"Decreased jitter buffer to {self.jitter_buffer_size}")
    
    def receive_packets(self):
        """Receive and buffer UDP packets"""
        print("Starting packet reception...")
        
        while self.receiving:
            try:
                data, addr = self.sock.recvfrom(1024)
                self.packets_received += 1
                
                # Parse packet
                if len(data) < 16:  # Minimum header size
                    continue
                
                # Unpack header: packet_count(4) + timestamp(8) + opus_length(4)
                header = struct.unpack('!LQL', data[:16])
                packet_count = header[0]
                timestamp = header[1]
                opus_length = header[2]
                
                # Extract opus data
                if len(data) >= 16 + opus_length:
                    opus_data = data[16:16+opus_length]
                else:
                    continue  # Malformed packet
                
                # Handle packet ordering
                if packet_count < self.expected_packet:
                    # Late packet
                    self.packets_late += 1
                    continue
                elif packet_count in self.jitter_buffer:
                    # Duplicate packet
                    self.packets_duplicate += 1
                    continue
                else:
                    # New packet - add to jitter buffer
                    self.jitter_buffer[packet_count] = (timestamp, opus_data)
                
                # Log metrics every 100 packets
                if self.packets_received % 100 == 0:
                    self.log_metrics()
                
            except socket.timeout:
                continue  # Normal timeout for responsive shutdown
            except Exception as e:
                if self.receiving:  # Only log errors if still receiving
                    print(f"Receive error: {e}")
    
    def log_metrics(self):
        """Log performance metrics"""
        if not self.csv_writer:
            return
        
        try:
            elapsed = time.time() - self.start_time
            total_expected = self.packets_received + self.packets_lost
            loss_percentage = (self.packets_lost / max(total_expected, 1)) * 100
            
            self.csv_writer.writerow([
                datetime.now().isoformat(),
                self.packets_received,
                self.packets_lost,
                loss_percentage,
                self.packets_late,
                self.packets_duplicate,
                self.buffer_underruns,
                len(self.jitter_buffer),
                self.playback_queue.qsize(),
                self.expected_packet
            ])
            self.csv_file.flush()
            
        except Exception as e:
            print(f"Logging error: {e}")
    
    def start_receiving(self):
        """Start zero-loss receiving"""
        if self.receiving:
            print("Already receiving!")
            return
        
        print("🎯 Starting Zero-Loss Audio Receiving")
        print(f"Listening on port: {self.listen_port}")
        print(f"Audio: {self.sample_rate}Hz, {self.channels}ch")
        print(f"Jitter buffer: {self.jitter_buffer_size} packets")
        
        # Reset counters
        self.receiving = True
        self.packets_received = 0
        self.packets_lost = 0
        self.packets_late = 0
        self.packets_duplicate = 0
        self.buffer_underruns = 0
        self.expected_packet = 1
        self.last_played_packet = 0
        self.start_time = time.time()
        
        # Clear buffers
        self.jitter_buffer.clear()
        while not self.playback_queue.empty():
            try:
                self.playback_queue.get_nowait()
            except queue.Empty:
                break
        
        # Start threads
        self.rx_thread = threading.Thread(target=self.receive_packets, daemon=True)
        self.buffer_thread = threading.Thread(target=self.process_jitter_buffer, daemon=True)
        
        self.rx_thread.start()
        self.buffer_thread.start()
        
        # Start audio output
        try:
            self.stream = sd.OutputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                callback=self.audio_callback,
                blocksize=self.frame_samples,
                dtype=np.float32,
                latency='low'
            )
            self.stream.start()
            print("✅ Zero-loss receiving started!")
            
        except Exception as e:
            print(f"❌ Failed to start: {e}")
            self.receiving = False
            raise
    
    def stop_receiving(self):
        """Stop receiving and show statistics"""
        if not self.receiving:
            return
        
        print("Stopping receiving...")
        self.receiving = False
        
        # Stop audio
        if hasattr(self, 'stream'):
            self.stream.stop()
            self.stream.close()
        
        # Close socket
        self.sock.close()
        
        # Wait for threads
        if hasattr(self, 'rx_thread'):
            self.rx_thread.join(timeout=2.0)
        if hasattr(self, 'buffer_thread'):
            self.buffer_thread.join(timeout=2.0)
        
        # Show final statistics
        elapsed = time.time() - self.start_time
        if self.packets_received > 0:
            loss_rate = (self.packets_lost / (self.packets_received + self.packets_lost)) * 100
            
            print(f"\n📊 Final Statistics:")
            print(f"  Packets received: {self.packets_received}")
            print(f"  Packets lost: {self.packets_lost}")
            print(f"  Loss rate: {loss_rate:.3f}%")
            print(f"  Late packets: {self.packets_late}")
            print(f"  Duplicates: {self.packets_duplicate}")
            print(f"  Buffer underruns: {self.buffer_underruns}")
            print(f"  Average rate: {self.packets_received/elapsed:.1f} pkt/s")
        
        # Close CSV
        if self.csv_writer:
            self.csv_file.close()
        
        print("✅ Stopped")

def main():
    """Main function"""
    receiver = None
    try:
        receiver = ZeroLossUDPReceiver("config.json")
        receiver.start_receiving()
        
        print("\n🎵 Zero-Loss Receiving Active!")
        print("Optimized for glitch-free audio playback")
        print("Press Ctrl+C to stop...")
        
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n⏹️  Stopping...")
        if receiver:
            receiver.stop_receiving()
    except Exception as e:
        print(f"❌ Error: {e}")
        if receiver:
            receiver.stop_receiving()
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
