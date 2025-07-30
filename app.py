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
from datetime import datetime, timedelta
import json

app = Flask(__name__)

# Allowed CORS origins for external domains
ALLOWED_ORIGINS = [
    'https://c278f6f4-ba8a-4106-9667-55c7ada4b91c.lovableproject.com',
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
    origin = request.headers.get('Origin')
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
    origin = request.headers.get('Origin')
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

class CameraStreamWithLCD:
    def __init__(self):
        self.picam2 = None
        self.streaming = False
        self.lcd_streaming = False  # For LCD display
        self.web_streaming = False  # For web clients
        self.lock = threading.Lock()
        self.lcd = None
        self.setup_lcd()
        self.setup_gpio()
        self.active_clients = 0 # Track active clients for video_feed
        self.network_monitor = NetworkMonitor() # Initialize network monitor
        self.camera_error_count = 0  # Track camera errors
        self.max_camera_errors = 5   # Max errors before giving up
        self.last_camera_error = None
        self.camera_recovery_delay = 10  # Seconds to wait before retry
        
    def setup_gpio(self):
        """Sets up GPIO pins for buttons."""
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(KEY1_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(KEY2_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(KEY3_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        
    def setup_lcd(self):
        """Initialize the LCD display."""
        try:
            self.lcd = LCD_1in44.LCD()
            Lcd_ScanDir = LCD_1in44.SCAN_DIR_DFT
            self.lcd.LCD_Init(Lcd_ScanDir)
            self.lcd.LCD_Clear()
        except Exception as e:
            print(f"LCD setup error: {e}")
            self.lcd = None
        
    def display_message(self, lines):
        """Displays multi-line messages on the LCD."""
        if not self.lcd:
            return
            
        try:
            image = Image.new("RGB", (self.lcd.width, self.lcd.height), "WHITE")
            draw = ImageDraw.Draw(image)
            try:
                font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 12)
            except IOError:
                font = ImageFont.load_default()
            
            y_text = 10
            for line in lines:
                draw.text((5, y_text), line, font=font, fill="BLACK")
                y_text += 16
            self.lcd.LCD_ShowImage(image, 0, 0)
        except Exception as e:
            print(f"LCD display error: {e}")
        
    def safe_camera_operation(self, operation_func, operation_name="camera operation"):
        """Safely execute camera operations with error handling and recovery"""
        try:
            return operation_func()
        except Exception as e:
            self.camera_error_count += 1
            self.last_camera_error = datetime.now()
            error_msg = str(e)
            
            print(f"Camera error in {operation_name}: {error_msg}")
            
            # Check for specific timeout/hardware errors
            if any(keyword in error_msg.lower() for keyword in ['timeout', 'dequeue', 'frontend', 'connector']):
                print(f"Hardware timeout detected. Error count: {self.camera_error_count}")
                self.display_message([
                    "Camera Timeout!",
                    "Hardware Issue",
                    f"Errors: {self.camera_error_count}",
                    "Attempting recovery..."
                ])
                
                # Force camera cleanup and recovery
                self.force_camera_cleanup()
                
                if self.camera_error_count >= self.max_camera_errors:
                    print("Max camera errors reached. Disabling camera operations.")
                    self.display_message([
                        "Camera Failed!",
                        "Max errors reached",
                        "Check connections",
                        "Restart required"
                    ])
                    self.streaming = False
                    self.lcd_streaming = False
                    self.web_streaming = False
                    return None
                
                # Wait before retry
                time.sleep(self.camera_recovery_delay)
                
            return None
            
    def force_camera_cleanup(self):
        """Force cleanup of camera resources"""
        print("Forcing camera cleanup...")
        try:
            with self.lock:
                if self.picam2:
                    try:
                        self.picam2.stop()
                    except:
                        pass
                    try:
                        self.picam2.close()
                    except:
                        pass
                    self.picam2 = None
                    print("Camera object cleaned up")
                    
                # Small delay to let hardware reset
                time.sleep(2)
                
        except Exception as e:
            print(f"Force cleanup error: {e}")
            
    def start_camera(self):
        """Initialize and start the camera with enhanced error handling"""
        def _start_camera():
            if self.picam2 is None:
                # Check if we're in error recovery mode
                if (self.last_camera_error and 
                    (datetime.now() - self.last_camera_error).seconds < self.camera_recovery_delay):
                    print("Camera in recovery mode, skipping start")
                    return False
                    
                self.picam2 = Picamera2()
                
                # Choose resolution based on what's needed
                if self.web_streaming:
                    # Higher resolution for web streaming
                    config = self.picam2.create_preview_configuration(
                        main={"size": (640, 480)}
                    )
                else:
                    # LCD-only mode
                    config = self.picam2.create_preview_configuration(
                        main={"size": (128, 128)}
                    )
                    
                self.picam2.configure(config)
                self.picam2.start()
                time.sleep(2)  # Allow camera to warm up
                
                # Reset error count on successful start
                self.camera_error_count = 0
                print("Camera started successfully")
                return True
            return True
            
        return self.safe_camera_operation(_start_camera, "camera start")
            
    def restart_camera_if_needed(self, need_web_res=False):
        """Restart camera with different resolution if needed"""
        current_size = None
        if self.picam2:
            current_size = (640, 480) if need_web_res else (128, 128)
            
        need_restart = False
        if need_web_res and current_size == (128, 128):
            need_restart = True
        elif not need_web_res and current_size == (640, 480):
            need_restart = True
            
        if need_restart:
            print(f"Restarting camera for {'web' if need_web_res else 'LCD-only'} resolution")
            self.stop_camera()
            return self.start_camera()
        return True
                
    def stop_camera(self):
        """Stop the camera with enhanced cleanup"""
        with self.lock:
            if self.picam2:
                try:
                    self.picam2.stop()
                except Exception as e:
                    print(f"Error stopping camera: {e}")
                try:
                    self.picam2.close()
                except Exception as e:
                    print(f"Error closing camera: {e}")
                self.picam2 = None
                print("Camera stopped and cleaned up")
                
    def start_streaming(self):
        """Start both LCD and web streaming with error handling"""
        try:
            self.display_message(["Starting Stream...", "Initializing...", "Please wait..."])
            time.sleep(1)
            
            # Set streaming flags first
            self.streaming = True
            self.lcd_streaming = True
            self.web_streaming = True
            
            # Try to start camera
            if not self.start_camera():
                self.display_message(["Stream Failed!", "Camera Error", f"Errors: {self.camera_error_count}", "Check connections"])
                self.streaming = False
                self.lcd_streaming = False
                self.web_streaming = False
                return False
            
            self.display_message(["Stream Active!", "Web: Available", "LCD: Active", "Press KEY3 to stop"])
            
            # Start LCD streaming in a separate thread
            lcd_thread = threading.Thread(target=self.lcd_stream_loop)
            lcd_thread.daemon = True
            lcd_thread.start()
            
            return True
            
        except Exception as e:
            print(f"Error starting streaming: {e}")
            self.display_message(["Stream Error!", str(e)[:15], "Try again", "Check hardware"])
            self.streaming = False
            self.lcd_streaming = False
            self.web_streaming = False
            return False
        
    def lcd_stream_loop(self):
        """Stream video to LCD display with enhanced error handling"""
        consecutive_errors = 0
        max_consecutive_errors = 10
        
        try:
            while self.lcd_streaming and self.streaming:
                # Check for stop button
                if not GPIO.input(KEY3_PIN):
                    print("KEY3 pressed, stopping streams.")
                    self.stop_streaming()
                    break
                
                # Skip if too many consecutive errors
                if consecutive_errors >= max_consecutive_errors:
                    print("Too many LCD streaming errors, stopping LCD stream")
                    self.lcd_streaming = False
                    self.display_message(["LCD Error!", "Too many fails", "Web still active", "Check hardware"])
                    break
                
                def _capture_and_display():
                    nonlocal consecutive_errors
                    
                    with self.lock:
                        if self.picam2:
                            # Capture frame with timeout protection
                            frame = self.picam2.capture_array()
                            
                            # Convert numpy array to PIL Image
                            image = Image.fromarray(frame)
                            
                            # Only resize if not already 128x128
                            if image.size != (128, 128):
                                try:
                                    image = image.resize((128, 128), Image.Resampling.LANCZOS)
                                except AttributeError:
                                    try:
                                        image = image.resize((128, 128), Image.LANCZOS)
                                    except AttributeError:
                                        image = image.resize((128, 128), Image.ANTIALIAS)
                            
                            # Display on LCD
                            if self.lcd:
                                self.lcd.LCD_ShowImage(image, 0, 0)
                            
                            consecutive_errors = 0  # Reset on success
                            return True
                    return False
                
                # Execute capture with error handling
                success = self.safe_camera_operation(_capture_and_display, "LCD capture")
                
                if not success:
                    consecutive_errors += 1
                    time.sleep(1)  # Wait longer on error
                else:
                    time.sleep(0.05)  # Normal 20 FPS
                    
        except Exception as e:
            print(f"LCD streaming loop error: {e}")
            self.lcd_streaming = False
        
    def stop_streaming(self):
        """Stop all streaming with cleanup"""
        print("Stopping all streaming...")
        self.streaming = False
        self.lcd_streaming = False
        self.web_streaming = False
        
        # Give threads time to finish
        time.sleep(0.5)
        
        self.stop_camera()
        
        if self.lcd:
            self.display_message(["Stream Stopped", "Press KEY1 to start", "Press KEY2 to exit"])
        
        print("All streaming stopped")

    def generate_frames(self):
        """Generate frames for MJPEG web streaming with enhanced error handling"""
        frame_count = 0
        consecutive_errors = 0
        max_consecutive_errors = 20
        
        while self.web_streaming and self.streaming:
            # Stop if too many consecutive errors
            if consecutive_errors >= max_consecutive_errors:
                print("Too many web streaming errors, stopping web stream")
                self.web_streaming = False
                # Generate error frame and break
                error_image = Image.new('RGB', (640, 480), color='red')
                draw = ImageDraw.Draw(error_image)
                draw.text((200, 220), "Web Stream Failed:", fill='white')
                draw.text((200, 240), "Too many errors", fill='white')
                draw.text((200, 260), "Check camera hardware", fill='white')
                
                img_io = io.BytesIO()
                error_image.save(img_io, 'JPEG')
                img_io.seek(0)
                error_bytes = img_io.read()
                
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + error_bytes + b'\r\n')
                break
            
            def _capture_web_frame():
                nonlocal frame_count, consecutive_errors
                
                with self.lock:
                    if self.picam2:
                        # Capture frame as numpy array
                        frame = self.picam2.capture_array()
                        
                        # Convert numpy array to PIL Image
                        image = Image.fromarray(frame)
                        
                        # Convert RGBA to RGB if needed
                        if image.mode == 'RGBA':
                            rgb_image = Image.new('RGB', image.size, (255, 255, 255))
                            rgb_image.paste(image, mask=image.split()[-1])
                            image = rgb_image
                        elif image.mode != 'RGB':
                            image = image.convert('RGB')
                        
                        # Convert to JPEG using PIL
                        img_io = io.BytesIO()
                        image.save(img_io, format='JPEG', quality=85)
                        img_io.seek(0)
                        frame_bytes = img_io.read()
                        
                        frame_count += 1
                        consecutive_errors = 0  # Reset on success
                        
                        if frame_count % 30 == 0:  # Log every 30 frames
                            print(f"Web streaming: frame {frame_count}, size: {image.size}, mode: {image.mode}")
                        
                        return frame_bytes
                return None
            
            # Execute capture with error handling
            frame_bytes = self.safe_camera_operation(_capture_web_frame, "web frame capture")
            
            if frame_bytes:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                time.sleep(0.033)  # ~30 FPS for web
            else:
                consecutive_errors += 1
                print(f"Web frame capture failed, consecutive errors: {consecutive_errors}")
                
                # Generate error frame
                error_image = Image.new('RGB', (640, 480), color='orange')
                draw = ImageDraw.Draw(error_image)
                draw.text((200, 200), "Frame Error", fill='black')
                draw.text((200, 220), f"Consecutive: {consecutive_errors}", fill='black')
                draw.text((200, 240), "Attempting recovery...", fill='black')
                
                img_io = io.BytesIO()
                error_image.save(img_io, 'JPEG')
                img_io.seek(0)
                error_bytes = img_io.read()
                
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + error_bytes + b'\r\n')
                time.sleep(1)  # Wait longer on error
                
    def button_monitor_loop(self):
        """Monitor button presses"""
        while True:
            try:
                if not self.streaming:
                    # Display welcome menu when not streaming
                    welcome_lines = [
                        "Pi Camera Stream",
                        "KEY1: Start Stream",
                        "KEY2: Exit",
                        f"Web: {app.config.get('SERVER_NAME', 'localhost:5000')}"
                    ]
                    self.display_message(welcome_lines)
                
                # Check button presses
                if not GPIO.input(KEY1_PIN) and not self.streaming:
                    print("KEY1 pressed, starting stream.")
                    self.start_streaming()
                    time.sleep(0.5)  # Debounce
                    
                if not GPIO.input(KEY2_PIN):
                    print("KEY2 pressed, exiting program.")
                    self.display_message(["Goodbye!", "Shutting down..."])
                    time.sleep(1)
                    if self.lcd:
                        self.lcd.LCD_Clear()
                    GPIO.cleanup()
                    exit(0)
                    
                time.sleep(0.1)  # Polling delay
                
            except Exception as e:
                print(f"Button monitor error: {e}")
                time.sleep(1)

# Global camera instance
camera_stream = CameraStreamWithLCD()

@app.route('/')
def index():
    """Main page with video stream"""
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    """Video streaming route with enhanced CORS"""
    if camera_stream.streaming and camera_stream.web_streaming:
        try:
            # Track active clients
            camera_stream.active_clients = getattr(camera_stream, 'active_clients', 0) + 1
            print(f"New client connected. Active clients: {camera_stream.active_clients}")
            
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
                    camera_stream.active_clients = max(0, getattr(camera_stream, 'active_clients', 1) - 1)
                    print(f"Client disconnected. Active clients: {camera_stream.active_clients}")
            
            response = Response(generate_with_cleanup(),
                               mimetype='multipart/x-mixed-replace; boundary=frame')
            # CORS headers will be automatically added by after_request
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            response.headers['X-Accel-Buffering'] = 'no'
            response.headers['Connection'] = 'keep-alive'
            return response
            
        except Exception as e:
            # Cleanup on error
            camera_stream.active_clients = max(0, getattr(camera_stream, 'active_clients', 1) - 1)
            print(f"Error setting up stream for client: {e}")
            # Return error image
            error_image = Image.new('RGB', (640, 480), (255, 0, 0))  # Red background
            draw = ImageDraw.Draw(error_image)
            draw.text((200, 220), f"Streaming Error:", fill=(255, 255, 255))  # White text
            draw.text((200, 240), str(e)[:50], fill=(255, 255, 255))
            
            img_io = io.BytesIO()
            error_image.save(img_io, format='JPEG', quality=85)
            img_io.seek(0)
            
            response = Response(img_io.read(), mimetype='image/jpeg')
            return response
    else:
        # Return a placeholder image when not streaming
        placeholder = Image.new('RGB', (640, 480), (0, 0, 0))  # Black background
        draw = ImageDraw.Draw(placeholder)
        if not camera_stream.streaming:
            draw.text((250, 220), "Camera Stream Not Started", fill=(255, 255, 255))  # White text
            draw.text((280, 240), "Press KEY1 to start", fill=(255, 255, 255))
        elif not camera_stream.web_streaming:
            draw.text((250, 220), "Web Streaming Disabled", fill=(255, 255, 255))
        else:
            draw.text((250, 220), "Camera Not Active", fill=(255, 255, 255))
        
        img_io = io.BytesIO()
        placeholder.save(img_io, format='JPEG', quality=85)
        img_io.seek(0)
        
        response = Response(img_io.read(), mimetype='image/jpeg')
        return response

@app.route('/start_stream', methods=['POST'])
def start_stream():
    """API endpoint to start streaming"""
    try:
        if not camera_stream.streaming:
            camera_stream.start_streaming()
        return jsonify({"status": "success", "message": "Stream started"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/stop_stream', methods=['POST'])
def stop_stream():
    """API endpoint to stop streaming"""
    try:
        camera_stream.stop_streaming()
        return jsonify({"status": "success", "message": "Stream stopped"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/status')
def status():
    """Get streaming and network status with enhanced info"""
    camera_active = False
    camera_info = "No camera"
    
    # Better camera state detection
    if camera_stream.picam2 is not None:
        try:
            # Try to get camera info to verify it's actually working
            camera_active = True
            camera_info = "Active"
        except Exception as e:
            camera_info = f"Error: {str(e)}"
            camera_active = False
    
    return jsonify({
        "streaming": camera_stream.streaming,
        "lcd_streaming": camera_stream.lcd_streaming,
        "web_streaming": camera_stream.web_streaming,
        "camera_active": camera_active,
        "camera_info": camera_info,
        "camera_object_exists": camera_stream.picam2 is not None,
        "network_stable": camera_stream.network_monitor.is_network_stable(),
        "active_clients": getattr(camera_stream, 'active_clients', 0),
        "network_failed_checks": camera_stream.network_monitor.failed_checks
    })

@app.route('/network_status')
def network_status():
    """Get detailed network status"""
    return jsonify({
        "network_stable": camera_stream.network_monitor.is_network_stable(),
        "failed_checks": camera_stream.network_monitor.failed_checks,
        "max_failed_checks": camera_stream.network_monitor.max_failed_checks,
        "last_check": camera_stream.network_monitor.last_check.isoformat(),
        "check_interval": camera_stream.network_monitor.check_interval,
        "wifi_available": camera_stream.network_monitor.check_wifi_signal(),
        "internet_available": camera_stream.network_monitor.check_internet_connection()
    })

@app.route('/debug_info')
def debug_info():
    """Debug endpoint to check detailed camera state"""
    info = {
        "streaming_flags": {
            "streaming": camera_stream.streaming,
            "lcd_streaming": camera_stream.lcd_streaming, 
            "web_streaming": camera_stream.web_streaming
        },
        "camera_state": {
            "picam2_object": camera_stream.picam2 is not None,
            "camera_active": camera_stream.picam2 is not None
        },
        "lcd_state": {
            "lcd_object": camera_stream.lcd is not None
        }
    }
    
    # Try to get frame info if camera exists
    if camera_stream.picam2 is not None:
        try:
            with camera_stream.lock:
                frame = camera_stream.picam2.capture_array()
                info["last_frame"] = {
                    "shape": frame.shape if frame is not None else "None",
                    "dtype": str(frame.dtype) if frame is not None else "None"
                }
        except Exception as e:
            info["last_frame"] = {"error": str(e)}
    
    return jsonify(info)

@app.route('/capture')
def capture():
    """Capture a single frame from the camera and return as JPEG"""
    temp_camera = False  # Initialize at the start
    try:
        def _do_capture():
            nonlocal temp_camera
            
            # Check if camera is available
            if not camera_stream.streaming or camera_stream.picam2 is None:
                # If not streaming, try to start camera temporarily for capture
                if camera_stream.picam2 is None:
                    temp_camera = True
                    camera_stream.picam2 = Picamera2()
                    # Use web resolution for captures
                    config = camera_stream.picam2.create_preview_configuration(
                        main={"size": (640, 480)}
                    )
                    camera_stream.picam2.configure(config)
                    camera_stream.picam2.start()
                    time.sleep(1)  # Allow camera to stabilize
            
            with camera_stream.lock:
                if camera_stream.picam2:
                    # Capture frame as numpy array
                    frame = camera_stream.picam2.capture_array()
                    
                    # Convert numpy array to PIL Image
                    image = Image.fromarray(frame)
                    
                    # Convert RGBA to RGB if needed (JPEG doesn't support transparency)
                    if image.mode == 'RGBA':
                        rgb_image = Image.new('RGB', image.size, (255, 255, 255))
                        rgb_image.paste(image, mask=image.split()[-1])
                        image = rgb_image
                    elif image.mode != 'RGB':
                        image = image.convert('RGB')
                    
                    # Convert to JPEG
                    img_io = io.BytesIO()
                    image.save(img_io, format='JPEG', quality=90)
                    img_io.seek(0)
                    frame_bytes = img_io.read()
                    
                    # Clean up temporary camera if we started it
                    if temp_camera:
                        camera_stream.picam2.stop()
                        camera_stream.picam2 = None
                    
                    return frame_bytes
            return None
        
        # Use safe camera operation
        frame_bytes = camera_stream.safe_camera_operation(_do_capture, "single frame capture")
        
        if frame_bytes:
            # Return the image with proper headers
            response = Response(frame_bytes, mimetype='image/jpeg')
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            response.headers['Content-Disposition'] = f'inline; filename="capture_{int(time.time())}.jpg"'
            return response
        else:
            # Return error image if camera not available
            error_image = Image.new('RGB', (640, 480), (255, 0, 0))
            draw = ImageDraw.Draw(error_image)
            draw.text((200, 220), "Camera Not Available", fill=(255, 255, 255))
            draw.text((200, 240), "Check camera status", fill=(255, 255, 255))
            
            img_io = io.BytesIO()
            error_image.save(img_io, format='JPEG', quality=85)
            img_io.seek(0)
            
            response = Response(img_io.read(), mimetype='image/jpeg')
            response.status_code = 503  # Service Unavailable
            return response
                
    except Exception as e:
        print(f"Capture error: {e}")
        # Clean up temporary camera on error if we started it
        if temp_camera and camera_stream.picam2:
            try:
                camera_stream.picam2.stop()
                camera_stream.picam2 = None
            except:
                pass
        
        # Return error image
        error_image = Image.new('RGB', (640, 480), (255, 100, 100))
        draw = ImageDraw.Draw(error_image)
        draw.text((200, 200), "Capture Failed", fill=(255, 255, 255))
        draw.text((200, 220), f"Error: {str(e)[:30]}", fill=(255, 255, 255))
        draw.text((200, 240), "Try again later", fill=(255, 255, 255))
        
        img_io = io.BytesIO()
        error_image.save(img_io, format='JPEG', quality=85)
        img_io.seek(0)
        
        response = Response(img_io.read(), mimetype='image/jpeg')
        response.status_code = 500  # Internal Server Error
        return response

@app.route('/capture_base64')
def capture_base64():
    """Capture a single frame and return as base64 encoded JSON"""
    temp_camera = False  # Initialize at the start
    try:
        def _do_capture_base64():
            nonlocal temp_camera
            
            # Check if camera is available
            if not camera_stream.streaming or camera_stream.picam2 is None:
                # If not streaming, try to start camera temporarily for capture
                if camera_stream.picam2 is None:
                    temp_camera = True
                    camera_stream.picam2 = Picamera2()
                    config = camera_stream.picam2.create_preview_configuration(
                        main={"size": (640, 480)}
                    )
                    camera_stream.picam2.configure(config)
                    camera_stream.picam2.start()
                    time.sleep(1)
            
            with camera_stream.lock:
                if camera_stream.picam2:
                    # Capture frame
                    frame = camera_stream.picam2.capture_array()
                    image = Image.fromarray(frame)
                    
                    # Convert to RGB if needed
                    if image.mode == 'RGBA':
                        rgb_image = Image.new('RGB', image.size, (255, 255, 255))
                        rgb_image.paste(image, mask=image.split()[-1])
                        image = rgb_image
                    elif image.mode != 'RGB':
                        image = image.convert('RGB')
                    
                    # Convert to base64
                    img_io = io.BytesIO()
                    image.save(img_io, format='JPEG', quality=90)
                    img_io.seek(0)
                    
                    import base64
                    img_base64 = base64.b64encode(img_io.read()).decode('utf-8')
                    
                    # Clean up temporary camera if we started it
                    if temp_camera:
                        camera_stream.picam2.stop()
                        camera_stream.picam2 = None
                    
                    return {
                        "status": "success",
                        "image": f"data:image/jpeg;base64,{img_base64}",
                        "timestamp": time.time(),
                        "size": image.size,
                        "format": "JPEG"
                    }
            return None
        
        # Use safe camera operation
        result = camera_stream.safe_camera_operation(_do_capture_base64, "base64 capture")
        
        if result:
            return jsonify(result)
        else:
            return jsonify({
                "status": "error",
                "message": "Camera not available or capture failed",
                "timestamp": time.time(),
                "camera_errors": camera_stream.camera_error_count
            }), 503
                
    except Exception as e:
        print(f"Base64 capture error: {e}")
        # Clean up temporary camera on error if we started it
        if temp_camera and camera_stream.picam2:
            try:
                camera_stream.picam2.stop()
                camera_stream.picam2 = None
            except:
                pass
        
        return jsonify({
            "status": "error",
            "message": str(e),
            "timestamp": time.time(),
            "camera_errors": camera_stream.camera_error_count
        }), 500

@app.route('/video_hls')
def video_hls():
    """HLS streaming endpoint for HTML5 video compatibility"""
    # For now, we'll create a simple approach using individual frame fetching
    # This is a placeholder for future HLS implementation
    return jsonify({
        "error": "HLS streaming not yet implemented",
        "alternatives": {
            "mjpeg_stream": "/video_feed",
            "single_frame": "/capture",
            "canvas_solution": "/video_canvas_stream"
        }
    })

@app.route('/video_canvas_stream')
def video_canvas_stream():
    """Stream individual frames as JSON for canvas-based rendering in React"""
    def generate_json_frames():
        frame_count = 0
        while camera_stream.web_streaming and camera_stream.streaming:
            with camera_stream.lock:
                if camera_stream.picam2:
                    try:
                        # Capture frame
                        frame = camera_stream.picam2.capture_array()
                        image = Image.fromarray(frame)
                        
                        # Convert to RGB if needed
                        if image.mode == 'RGBA':
                            rgb_image = Image.new('RGB', image.size, (255, 255, 255))
                            rgb_image.paste(image, mask=image.split()[-1])
                            image = rgb_image
                        elif image.mode != 'RGB':
                            image = image.convert('RGB')
                        
                        # Convert to base64
                        img_io = io.BytesIO()
                        image.save(img_io, format='JPEG', quality=80)
                        img_io.seek(0)
                        
                        import base64
                        img_base64 = base64.b64encode(img_io.read()).decode('utf-8')
                        
                        frame_count += 1
                        
                        # Create JSON frame
                        frame_data = {
                            "frame": frame_count,
                            "timestamp": time.time(),
                            "image": f"data:image/jpeg;base64,{img_base64}",
                            "size": image.size
                        }
                        
                        # Send as Server-Sent Events (SSE)
                        yield f"data: {json.dumps(frame_data)}\n\n"
                        
                    except Exception as e:
                        error_data = {
                            "error": str(e),
                            "timestamp": time.time()
                        }
                        yield f"data: {json.dumps(error_data)}\n\n"
                        
            time.sleep(0.1)  # 10 FPS for canvas streaming
    
    # Import json at the top if not already imported
    import json
    
    response = Response(generate_json_frames(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Connection'] = 'keep-alive'
    response.headers['X-Accel-Buffering'] = 'no'
    return response

@app.route('/video_websocket_info')
def video_websocket_info():
    """Provide WebSocket connection info for real-time streaming"""
    return jsonify({
        "websocket_url": f"ws://{request.host}/ws/video",
        "note": "WebSocket streaming not yet implemented",
        "alternatives": {
            "server_sent_events": "/video_canvas_stream",
            "polling": "/capture",
            "mjpeg": "/video_feed"
        }
    })

@app.route('/react')
def react_example():
    """React-compatible streaming examples page"""
    return render_template('react_example.html')

def run_flask_server():
    """Run Flask server in a separate thread"""
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True, use_reloader=False)

def main():
    """Main function to be called by run_stream.py or directly"""
    try:
        # Start Flask server in background thread
        flask_thread = threading.Thread(target=run_flask_server)
        flask_thread.daemon = True
        flask_thread.start()
        
        print("Flask server starting on http://0.0.0.0:5000")
        print("Use buttons on LCD to control camera:")
        print("KEY1 (GPIO 21): Start streaming")
        print("KEY2 (GPIO 20): Exit program") 
        print("KEY3 (GPIO 16): Stop streaming")
        
        # Run button monitoring in main thread
        camera_stream.button_monitor_loop()
        
    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        camera_stream.stop_streaming()
        if camera_stream.lcd:
            camera_stream.lcd.LCD_Clear()
        GPIO.cleanup()

if __name__ == '__main__':
    main() 