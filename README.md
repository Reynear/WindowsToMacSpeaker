# Windows to Mac Speaker

Stream audio from Windows PC to macOS device using multiple protocols with low-ish latency.

## Features

- **FFmpeg + RTP**: Low-latency audio streaming using Opus codec
- **JACK + NetJack**: Professional audio routing (planned)
- **Error handling**: Robust validation and troubleshooting
- **Cross-platform**: Windows sender, macOS receiver

## Quick Start

### Prerequisites

**Windows:**
- [FFmpeg](https://ffmpeg.org/download.html) installed and in PATH
- [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) for audio routing

**macOS:**
- FFmpeg: `brew install ffmpeg`

### Setup

1. **Windows Setup:**
   ```cmd
   setup_windows.bat
   ```

2. **macOS Setup:**
   ```zsh
   chmod +x setup_macos.sh
   ./setup_macos.sh
   ```

### Usage

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

## Configuration

Edit `config.json` to customize:
- IP addresses
- Audio devices
- Quality settings
- Network parameters

## Troubleshooting

### No Audio Received
- Check network connectivity: `ping <mac_ip>`
- Verify audio device is active on Windows
- Check firewall settings (UDP port 5004)

### Audio Quality Issues
- Increase bitrate in config
- Check network bandwidth
- Verify audio device sample rate

### Connection Failures
- Ensure both devices on same network
- Check IP address configuration
- Verify FFmpeg installation

## Protocol Comparison

| Feature | FFmpeg-RTP |
|---------|------------|
| Latency | ~10-50ms | 
| Setup | Easy | 
| Quality | Good | 
| Stability | High |

## License

MIT License - see [LICENSE](LICENSE) file.