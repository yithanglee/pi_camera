# Pi Camera Streaming Server

A Flask-based camera streaming server for Raspberry Pi with LCD display integration. This project combines physical button controls on a 128x128 LCD HAT with web-based video streaming, making the camera accessible to other web applications.

## Features

- **Dual Interface**: Control via physical LCD buttons or web interface
- **MJPEG Streaming**: Real-time video streaming over HTTP
- **Multi-client Support**: Multiple web applications can consume the stream
- **LCD Display**: Shows camera feed on 128x128 LCD with button controls
- **RESTful API**: Simple API endpoints for remote control
- **Auto-reconnection**: Web interface handles connection drops gracefully

## Hardware Requirements

- Raspberry Pi Zero 2 (or compatible)
- Pi Camera Module
- 1.44" LCD HAT with ST7735S controller (128x128 resolution)
- Buttons connected as per ST7735S pinout

### Button Mapping (GPIO BCM)
- **KEY1 (GPIO 21)**: Start video streaming
- **KEY2 (GPIO 20)**: Exit program
- **KEY3 (GPIO 16)**: Stop video streaming

## Software Requirements

- Python 3.7+
- Flask
- OpenCV
- picamera2
- RPi.GPIO
- Pillow
- NumPy

## Installation

1. **Clone or download the project files to your Pi**

2. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Ensure camera is enabled**:
   ```bash
   sudo raspi-config
   # Navigate to Interface Options > Camera > Enable
   ```

4. **Place LCD library files**:
   Make sure `LCD_1in44.py` and `LCD_Config.py` are in the project directory.

## Usage

### Method 1: Using the run script (Recommended)
```bash
python3 run_stream.py
```

### Method 2: Direct execution
```bash
python3 app.py
```

## Web Interface

Once running, access the web interface at:
- **Local**: http://localhost:5000
- **Network**: http://YOUR_PI_IP:5000

The web interface provides:
- Live video stream display
- Start/stop controls
- Real-time status monitoring
- API endpoint documentation

## API Endpoints

### GET /video_feed
Returns MJPEG video stream for embedding in other applications.

```html
<img src="http://YOUR_PI_IP:5000/video_feed" alt="Pi Camera Stream">
```

### POST /start_stream
Start the camera streaming.

```bash
curl -X POST http://YOUR_PI_IP:5000/start_stream
```

### POST /stop_stream
Stop the camera streaming.

```bash
curl -X POST http://YOUR_PI_IP:5000/stop_stream
```

### GET /status
Get current streaming status.

```bash
curl http://YOUR_PI_IP:5000/status
```

Response:
```json
{
  "streaming": true,
  "lcd_streaming": true,
  "web_streaming": true,
  "camera_active": true
}
```

## Using in Other Applications

### Example 1: Embed in HTML
```html
<img src="http://YOUR_PI_IP:5000/video_feed" 
     alt="Pi Camera Stream" 
     style="width: 640px; height: 480px;">
```

### Example 2: Python Client
Use the provided `client_example.py`:

```bash
python3 client_example.py
```

Or create your own client:
```python
import requests

# Check if stream is active
response = requests.get("http://YOUR_PI_IP:5000/status")
status = response.json()

if not status['streaming']:
    # Start streaming
    requests.post("http://YOUR_PI_IP:5000/start_stream")

# Use the video feed
stream_url = "http://YOUR_PI_IP:5000/video_feed"
```

### Example 3: JavaScript/Web Integration
```javascript
// Control streaming via JavaScript
async function startStream() {
    const response = await fetch('/start_stream', { method: 'POST' });
    const result = await response.json();
    console.log(result);
}

// Display video stream
document.getElementById('videoStream').src = '/video_feed';
```

## File Structure

```
pi_camera/
├── app.py              # Main Flask application
├── main.py             # Original LCD-only implementation
├── run_stream.py       # Startup script with checks
├── client_example.py   # Example client implementation
├── requirements.txt    # Python dependencies
├── templates/
│   └── index.html     # Web interface template
├── LCD_1in44.py       # LCD driver (hardware specific)
├── LCD_Config.py      # LCD configuration (hardware specific)
└── README.md          # This file
```

## Configuration

### Video Settings
Edit `app.py` to modify video settings:

```python
# For web streaming (in start_camera method)
config = self.picam2.create_preview_configuration(
    main={"size": (640, 480), "format": "RGB888"}  # Adjust resolution
)

# For LCD display (in lcd_stream_loop method)
frame_resized = cv2.resize(frame, (128, 128))  # LCD size

# Frame rates
time.sleep(0.033)  # ~30 FPS for web
time.sleep(0.05)   # ~20 FPS for LCD
```

### Network Settings
Change the server port in `app.py`:

```python
app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
```

## Troubleshooting

### Camera Not Detected
```bash
# Check if camera is connected
vcgencmd get_camera

# Test camera directly
libcamera-hello --timeout 2000
```

### LCD Not Working
- Verify LCD_1in44.py and LCD_Config.py are present
- Check SPI is enabled: `sudo raspi-config` > Interface Options > SPI
- Verify wiring matches ST7735S pinout

### Web Interface Not Accessible
- Check firewall settings
- Ensure Pi is connected to network
- Try accessing via Pi's IP address instead of localhost

### Performance Issues
- Reduce video resolution in configuration
- Lower frame rates
- Check CPU usage: `htop`

## Integration Examples

### With Home Assistant
Add to your `configuration.yaml`:

```yaml
camera:
  - platform: mjpeg
    mjpeg_url: http://YOUR_PI_IP:5000/video_feed
    name: "Pi Camera"
```

### With Node-RED
Use an HTTP request node pointing to:
- URL: `http://YOUR_PI_IP:5000/video_feed`
- Method: GET

### With OBS Studio
Add a Browser Source with URL:
`http://YOUR_PI_IP:5000`

## License

This project is open source. Feel free to modify and distribute.

## Contributing

Contributions are welcome! Please feel free to submit pull requests or open issues for bugs and feature requests. 