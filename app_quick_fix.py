from flask import Flask, Response, render_template, jsonify, request
from picamera2 import Picamera2
import threading
import time
import io
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import RPi.GPIO as GPIO
import LCD_1in44
import LCD_Config
import socket
import subprocess
import requests
from datetime import datetime, timedelta

app = Flask(__name__)

# Allowed CORS origins for external domains
ALLOWED_ORIGINS = [
    'https://bookworm-scanner-vision.lovable.app',
    'https://lovable.dev',
    'http://localhost:3000',  # For local development
    'http://127.0.0.1:3000',  # For local development
    'http://localhost:5173',  # Vite dev server
    'http://127.0.0.1:5173',  # Vite dev server
]

def is_allowed_origin(origin):
    """Check if the origin is allowed for CORS"""
    if not origin:
        return True  # Allow requests without origin (direct API calls)
    
    # Allow any subdomain of lovable.dev
    if origin.endswith('.lovable.dev') or origin == 'https://lovable.dev':
        return True
    
    # Allow any subdomain of lovable.app
    if origin.endswith('.lovable.app'):
        return True
    
    # Allow specific origins
    return origin in ALLOWED_ORIGINS

def get_cors_origin(request_origin):
    """Get the appropriate CORS origin header value"""
    if is_allowed_origin(request_origin):
        return request_origin if request_origin else '*'
    return None

# Add CORS headers to all responses
@app.after_request
def after_request(response):
    try:
        from flask import request as flask_request
        origin = flask_request.headers.get('Origin')
    except:
        # Fallback for any import issues
        origin = '*'
    
    cors_origin = get_cors_origin(origin)
    
    if cors_origin:
        response.headers.add('Access-Control-Allow-Origin', cors_origin)
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-Requested-With')
        response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        response.headers.add('Access-Control-Max-Age', '3600')  # Cache preflight for 1 hour
    
    return response

# Handle preflight OPTIONS requests
@app.route('/<path:path>', methods=['OPTIONS'])
def handle_options(path):
    try:
        from flask import request as flask_request
        origin = flask_request.headers.get('Origin')
    except:
        origin = '*'
    
    cors_origin = get_cors_origin(origin)
    
    response = Response()
    if cors_origin:
        response.headers.add('Access-Control-Allow-Origin', cors_origin)
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-Requested-With')
        response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        response.headers.add('Access-Control-Max-Age', '3600')
    else:
        response.status_code = 403
    
    return response

@app.route('/cors-test')
def cors_test():
    """Test endpoint to verify CORS configuration"""
    origin = request.headers.get('Origin', 'No origin header')
    return jsonify({
        "message": "CORS test successful!",
        "origin": origin,
        "allowed": is_allowed_origin(origin),
        "timestamp": time.time(),
        "allowed_origins": ALLOWED_ORIGINS,
        "lovable_domains_supported": [
            "https://lovable.dev",
            "*.lovable.dev",
            "*.lovable.app",
            "https://bookworm-scanner-vision.lovable.app"
        ]
    })

# Pin definitions from ST7735S_buttons.txt
KEY1_PIN = 21  # Start video/streaming
KEY2_PIN = 20  # Exit program
KEY3_PIN = 16  # Stop video/streaming

class NetworkMonitor:
    def __init__(self):
        self.is_connected = True
        self.last_check = datetime.now()
        self.failed_checks = 0
        self.max_failed_checks = 3
        self.check_interval = 5  # seconds
        
    def check_internet_connection(self):
        """Check internet connectivity"""
        try:
            # Try to reach Google DNS
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            return True
        except OSError:
            return False
    
    def check_wifi_signal(self):
        """Check WiFi signal strength (Linux specific)"""
        try:
            result = subprocess.run(['iwconfig'], capture_output=True, text=True, timeout=5)
            if 'Signal level' in result.stdout:
                # Extract signal level (rough check)
                return True
            return False
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    def is_network_stable(self):
        """Check if network is stable enough for streaming"""
        now = datetime.now()
        
        # Only check every few seconds to avoid overhead
        if (now - self.last_check).seconds < self.check_interval:
            return self.is_connected
            
        self.last_check = now
        
        # Check both WiFi and internet
        wifi_ok = self.check_wifi_signal()
        internet_ok = self.check_internet_connection()
        
        if wifi_ok and internet_ok:
            self.failed_checks = 0
            self.is_connected = True
        else:
            self.failed_checks += 1
            if self.failed_checks >= self.max_failed_checks:
                self.is_connected = False
                
        return self.is_connected

# Rest of your original CameraStreamWithLCD class would go here...
# I'm including a simplified version to avoid the hardware dependency issues

class CameraStreamWithLCD:
    def __init__(self):
        self.picam2 = None
        self.streaming = False
        self.lcd_streaming = False
        self.web_streaming = False
        self.lock = threading.Lock()
        self.lcd = None
        self.network_monitor = NetworkMonitor()
        self.active_clients = 0
        self.frame_generation_active = False
        self.last_frame_time = None
        # Note: GPIO and LCD setup commented out for testing
        # self.setup_lcd()
        # self.setup_gpio()
        
    def generate_frames(self):
        """Generate test frames for MJPEG web streaming"""
        frame_count = 0
        self.frame_generation_active = True
        self.last_frame_time = datetime.now()
        
        try:
            while self.web_streaming and self.streaming and self.frame_generation_active:
                # Generate a test frame
                test_image = Image.new('RGB', (640, 480), color='blue')
                draw = ImageDraw.Draw(test_image)
                draw.text((250, 220), f"Test Frame {frame_count}", fill='white')
                draw.text((250, 240), f"Network: {'Stable' if self.network_monitor.is_network_stable() else 'Unstable'}", fill='white')
                
                img_io = io.BytesIO()
                test_image.save(img_io, format='JPEG', quality=85)
                img_io.seek(0)
                frame_bytes = img_io.read()
                
                frame_count += 1
                self.last_frame_time = datetime.now()
                
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                
                time.sleep(0.033)  # ~30 FPS
                
        except GeneratorExit:
            print("Frame generator closed by client")
        except Exception as e:
            print(f"Error in frame generation: {e}")
        finally:
            self.frame_generation_active = False

# Global camera instance
camera_stream = CameraStreamWithLCD()

@app.route('/')
def index():
    """Main page with video stream"""
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    """Video streaming route with connection monitoring"""
    # Increment active client counter
    camera_stream.active_clients += 1
    print(f"New client connected. Active clients: {camera_stream.active_clients}")
    
    # For testing, always enable streaming
    camera_stream.streaming = True
    camera_stream.web_streaming = True
    
    try:
        def generate_with_cleanup():
            try:
                for frame in camera_stream.generate_frames():
                    yield frame
            except GeneratorExit:
                print("Client disconnected")
            except Exception as e:
                print(f"Streaming error for client: {e}")
            finally:
                # Decrement client counter when connection closes
                camera_stream.active_clients = max(0, camera_stream.active_clients - 1)
                print(f"Client disconnected. Active clients: {camera_stream.active_clients}")
        
        response = Response(generate_with_cleanup(),
                           mimetype='multipart/x-mixed-replace; boundary=frame')
        
        # CORS headers are automatically added by after_request
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.headers['Connection'] = 'keep-alive'
        
        return response
        
    except Exception as e:
        # Cleanup on error
        camera_stream.active_clients = max(0, camera_stream.active_clients - 1)
        print(f"Error setting up stream for client: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/status')
def status():
    """Get streaming and network status"""
    return jsonify({
        "streaming": camera_stream.streaming,
        "web_streaming": camera_stream.web_streaming,
        "network_stable": camera_stream.network_monitor.is_network_stable(),
        "active_clients": camera_stream.active_clients,
        "frame_generation_active": camera_stream.frame_generation_active,
        "network_failed_checks": camera_stream.network_monitor.failed_checks
    })

@app.route('/start_stream', methods=['POST'])
def start_stream():
    """API endpoint to start streaming"""
    try:
        camera_stream.streaming = True
        camera_stream.web_streaming = True
        return jsonify({"status": "success", "message": "Stream started"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/stop_stream', methods=['POST'])
def stop_stream():
    """API endpoint to stop streaming"""
    try:
        camera_stream.streaming = False
        camera_stream.web_streaming = False
        camera_stream.frame_generation_active = False
        return jsonify({"status": "success", "message": "Stream stopped"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    print("🚀 Starting Pi Camera Flask app with enhanced CORS...")
    print("📋 Supported domains:")
    for origin in ALLOWED_ORIGINS:
        print(f"  ✅ {origin}")
    print("  ✅ *.lovable.dev (any subdomain)")
    print("  ✅ *.lovable.app (any subdomain)")
    app.run(host='0.0.0.0', port=5000, debug=True)
