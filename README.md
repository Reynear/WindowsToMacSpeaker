# Windows to Mac Speaker

Stream audio from Windows PC to macOS device using multiple protocols with low latency.

## Features

- **Custom UDP + Python**: High-performance UDP streaming with Opus codec and CSV metrics
- **FFmpeg + RTP**: Alternative implementation using FFmpeg RTP streaming
- **Real-time monitoring**: CSV logging for performance analysis
- **Configurable**: JSON-based configuration for all settings
- **Cross-platform**: Windows sender, macOS receiver

## Implementations

### 1. Custom UDP Configuration (Recommended)

High-performance Python implementation with advanced features:
- Direct UDP packet streaming
- Opus audio compression
- Real-time performance metrics
- CSV logging for analysis
- Configurable audio devices and network settings

### 2. FFmpeg-RTP Implementation

Alternative implementation using FFmpeg:
- RTP protocol streaming
- SDP session description
- Built-in FFmpeg error handling

## Quick Start

### Prerequisites

**Windows:**
- Python 3.7+ with packages: `sounddevice`, `opuslib`, `numpy`
- [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) for audio routing
- For FFmpeg implementation: [FFmpeg](https://ffmpeg.org/download.html)

**macOS:**
- Python 3.7+ with packages: `sounddevice`, `opuslib`, `numpy`
- For FFmpeg implementation: `brew install ffmpeg`

### Installation

Install Python dependencies:
```bash
pip install sounddevice opuslib numpy
```

### Configuration

Edit `Custom UDP Configuration/Python/config.json`:
```json
{
  "network": {
    "ip": "192.168.0.125",     // Mac's IP address
    "port": 5004,
    "socket_buffer_size": 8192
  },
  "audio": {
    "sample_rate": 48000,
    "channels": 2,
    "chunk_size": 1024,
    "input_device_name": "VB-Audio",    // Windows: VB-Cable
    "output_device_name": "default"     // Mac: speakers/headphones
  },
  "opus": {
    "bitrate": 128000,
    "frame_duration": 20
  },
  "logging": {
    "enable_csv": true,
    "verbose": true,
    "stats_interval": 1000
  }
}
```

### Usage

#### Custom UDP Implementation (Recommended)

1. **Start receiver on Mac:**
   ```bash
   cd "Custom UDP Configuration/Python"
   python receiver.py
   ```

2. **Start sender on Windows:**
   ```cmd
   cd "Custom UDP Configuration\Python"
   python sender.py
   ```

#### FFmpeg Implementation

1. **Start receiver on Mac:**
   ```bash
   cd "FFmpeg-RTP Implementation/MacOS"
   chmod +x playback.sh
   ./playback.sh
   ```

2. **Start sender on Windows:**
   ```cmd
   cd "FFmpeg-RTP Implementation\Windows"
   start_audio_stream.bat
   ```

## Performance Monitoring

The Custom UDP implementation automatically generates CSV files:
- `sender_metrics.csv`: Compression ratios, packet rates, network stats
- `receiver_metrics.csv`: Packet loss, buffer status, audio quality

Example metrics:
```csv
timestamp,packet_count,packet_rate,compression_ratio,loss_rate_percent
2024-01-01T12:00:00,1000,50.2,8.7,0.1
```

## Advanced Configuration

### Audio Device Selection

List available devices:
```python
import sounddevice as sd
print(sd.query_devices())
```

Update config with specific device IDs:
```json
{
  "audio": {
    "input_device_id": 5,    // Specific Windows input device
    "output_device_id": 2    // Specific Mac output device
  }
}
```

### Network Optimization

For lower latency:
```json
{
  "network": {
    "socket_buffer_size": 4096  // Smaller buffer = lower latency
  },
  "opus": {
    "frame_duration": 10        // Shorter frames = lower latency
  }
}
```

For better quality:
```json
{
  "opus": {
    "bitrate": 256000,          // Higher bitrate = better quality
    "frame_duration": 40        // Longer frames = more compression
  }
}
```

## Troubleshooting

### No Audio Received
- Check network connectivity: `ping <mac_ip>`
- Verify VB-Cable is installed and active on Windows
- Check firewall settings (allow UDP port 5004)
- Ensure both devices use the same `config.json`

### Audio Quality Issues
- Increase `opus.bitrate` in config (128000 → 256000)
- Check network bandwidth and packet loss in CSV logs
- Verify audio device sample rates match (48kHz recommended)

### High Latency
- Reduce `opus.frame_duration` (20ms → 10ms)
- Decrease `network.socket_buffer_size`
- Use wired network connection instead of WiFi

### Device Detection Issues
- Run `python -c "import sounddevice; print(sounddevice.query_devices())"` to list devices
- Update device names in config to match exactly
- Try using device IDs instead of names

### Python Package Issues
- Windows: Install Microsoft Visual C++ Build Tools for opuslib compilation
- macOS: Install Xcode command line tools: `xcode-select --install`
- Use conda for easier dependency management: `conda install sounddevice`

## Implementation Comparison

| Feature | Custom UDP Python | FFmpeg-RTP |
|---------|------------------|-------------|
| Latency | ~5-20ms | ~10-50ms |
| CPU Usage | Low | Medium |
| Setup Complexity | Medium | Easy |
| Monitoring | Extensive CSV logs | Basic logs |
| Customization | High | Limited |
| Stability | High | High |
| Dependencies | Python packages | FFmpeg only |

## License

GPL v3 License - see [LICENSE](LICENSE) file.

## Contributing

This project is open source under GPL v3. You can:
- Use and modify the code freely
- Distribute modified versions under GPL v3
- Contribute improvements back to the project

For commercial use or alternative licensing, please contact the author.