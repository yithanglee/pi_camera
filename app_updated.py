from flask import Flask, Response, render_template, jsonify
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
        self.network_monitor = NetworkMonitor()
        self.active_clients = 0
        self.frame_generation_active = False
        self.last_frame_time = None
        self.setup_lcd()
        self.setup_gpio()
        
    def setup_gpio(self):
        """Sets up GPIO pins for buttons."""
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(KEY1_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(KEY2_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(KEY3_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        
    def setup_lcd(self):
        """Initialize the LCD display."""
        self.lcd = LCD_1in44.LCD()
        Lcd_ScanDir = LCD_1in44.SCAN_DIR_DFT
        self.lcd.LCD_Init(Lcd_ScanDir)
        self.lcd.LCD_Clear()
        
    def display_message(self, lines):
        """Displays multi-line messages on the LCD."""
        if not self.lcd:
            return
            
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
        
    def start_camera(self):
        """Initialize and start the camera with optimal resolution"""
        if self.picam2 is None:
            self.picam2 = Picamera2()
            
            # Choose resolution based on what's needed
            if self.web_streaming:
                # Higher resolution for web streaming - match original format
                config = self.picam2.create_preview_configuration(
                    main={"size": (640, 480)}
                )
            else:
                # LCD-only mode: use 128x128 like original main.py (no format specified!)
                config = self.picam2.create_preview_configuration(
                    main={"size": (128, 128)}
                )
                
            self.picam2.configure(config)
            self.picam2.start()
            time.sleep(2)  # Allow camera to warm up
            
    def restart_camera_if_needed(self, need_web_res=False):
        """Restart camera with different resolution if needed"""
        current_size = None
        if self.picam2:
            # Get current configured size (simplified check)
            current_size = (640, 480) if need_web_res else (128, 128)
            
        need_restart = False
        if need_web_res and current_size == (128, 128):
            need_restart = True
        elif not need_web_res and current_size == (640, 480):
            need_restart = True
            
        if need_restart:
            print(f"Restarting camera for {'web' if need_web_res else 'LCD-only'} resolution")
            self.stop_camera()
            self.start_camera()
                
    def stop_camera(self):
        """Stop the camera"""
        with self.lock:
            if self.picam2:
                self.picam2.stop()
                self.picam2 = None
                
    def start_streaming(self):
        """Start both LCD and web streaming"""
        # Check network before starting
        if not self.network_monitor.is_network_stable():
            self.display_message(["Network Unstable", "Cannot start", "web streaming", "LCD only mode"])
            # Start LCD-only mode
            self.streaming = True
            self.lcd_streaming = True
            self.web_streaming = False
        else:
            self.display_message(["Starting Stream...", "Web: Available", "LCD: Active", "Press KEY3 to stop"])
            # Set streaming flags first so start_camera knows what resolution to use
            self.streaming = True
            self.lcd_streaming = True
            self.web_streaming = True
        
        time.sleep(2)
        self.start_camera()
        
        # Start LCD streaming in a separate thread
        lcd_thread = threading.Thread(target=self.lcd_stream_loop)
        lcd_thread.daemon = True
        lcd_thread.start()
        
        # Start network monitoring thread
        network_thread = threading.Thread(target=self.network_monitor_loop)
        network_thread.daemon = True
        network_thread.start()
        
    def network_monitor_loop(self):
        """Monitor network stability and stop streaming if unstable"""
        while self.streaming:
            if not self.network_monitor.is_network_stable():
                print("Network instability detected, stopping web streaming")
                self.display_message(["Network Lost", "Web stream stopped", "LCD continues", "Monitoring..."])
                
                # Stop web streaming but keep LCD
                self.web_streaming = False
                
                # Wait for network to recover
                recovery_attempts = 0
                max_recovery_attempts = 10
                
                while self.streaming and recovery_attempts < max_recovery_attempts:
                    time.sleep(10)  # Wait 10 seconds before checking again
                    recovery_attempts += 1
                    
                    if self.network_monitor.is_network_stable():
                        print("Network recovered, resuming web streaming")
                        self.display_message(["Network Recovered", "Resuming web", "streaming...", ""])
                        self.web_streaming = True
                        break
                    else:
                        self.display_message([f"Network check {recovery_attempts}/{max_recovery_attempts}", "Still unstable", "Retrying...", ""])
                
                if recovery_attempts >= max_recovery_attempts and self.streaming:
                    print("Network failed to recover, stopping all streaming")
                    self.display_message(["Network Failed", "Stopping all", "streaming", "Press KEY1 to retry"])
                    self.stop_streaming()
                    break
            
            time.sleep(5)  # Check every 5 seconds
        
    def lcd_stream_loop(self):
        """Stream video to LCD display"""
        try:
            while self.lcd_streaming and self.streaming:
                if not GPIO.input(KEY3_PIN):
                    print("KEY3 pressed, stopping streams.")
                    self.stop_streaming()
                    break
                    
                with self.lock:
                    if self.picam2:
                        try:
                            # Capture frame
                            frame = self.picam2.capture_array()
                            
                            # Convert numpy array to PIL Image
                            image = Image.fromarray(frame)
                            
                            # Only resize if not already 128x128 (web streaming mode)
                            if image.size != (128, 128):
                                # Use LANCZOS for older PIL versions, fallback to ANTIALIAS for very old versions
                                try:
                                    # Try new style first (Pillow >= 10.0.0)
                                    image = image.resize((128, 128), Image.Resampling.LANCZOS)
                                except AttributeError:
                                    try:
                                        # Try intermediate style (Pillow >= 2.7.0)
                                        image = image.resize((128, 128), Image.LANCZOS)
                                    except AttributeError:
                                        # Fallback for very old versions
                                        image = image.resize((128, 128), Image.ANTIALIAS)
                            
                            # Display on LCD
                            if self.lcd:
                                self.lcd.LCD_ShowImage(image, 0, 0)
                        except Exception as e:
                            print(f"LCD frame capture error: {e}")
                            # Continue with LCD streaming even if there are occasional errors
                        
                time.sleep(0.05)  # 20 FPS for LCD
        except Exception as e:
            print(f"LCD streaming error: {e}")
        
    def stop_streaming(self):
        """Stop all streaming"""
        self.streaming = False
        self.lcd_streaming = False
        self.web_streaming = False
        self.frame_generation_active = False
        self.stop_camera()
        
        if self.lcd:
            self.display_message(["Stream Stopped", "Press KEY1 to start", "Press KEY2 to exit"])
                
    def generate_frames(self):
        """Generate frames for MJPEG web streaming with network monitoring"""
        frame_count = 0
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        self.frame_generation_active = True
        self.last_frame_time = datetime.now()
        
        print("Starting frame generation for web streaming")
        
        try:
            while self.web_streaming and self.streaming and self.frame_generation_active:
                # Check if network is still stable
                if not self.network_monitor.is_network_stable():
                    print("Network instability detected in frame generation, stopping")
                    break
                
                # Check for stale connections (no recent frame requests)
                if self.active_clients == 0 and (datetime.now() - self.last_frame_time).seconds > 30:
                    print("No active clients for 30 seconds, stopping frame generation")
                    break
                
                with self.lock:
                    if self.picam2:
                        try:
                            # Capture frame as numpy array
                            frame = self.picam2.capture_array()
                            
                            # Convert numpy array to PIL Image
                            image = Image.fromarray(frame)
                            
                            # Convert RGBA to RGB if needed (JPEG doesn't support transparency)
                            if image.mode == 'RGBA':
                                # Create a white background and paste the RGBA image on it
                                rgb_image = Image.new('RGB', image.size, (255, 255, 255))
                                rgb_image.paste(image, mask=image.split()[-1])  # Use alpha channel as mask
                                image = rgb_image
                            elif image.mode != 'RGB':
                                # Convert any other mode to RGB
                                image = image.convert('RGB')
                            
                            # Convert to JPEG using PIL
                            img_io = io.BytesIO()
                            image.save(img_io, format='JPEG', quality=85)
                            img_io.seek(0)
                            frame_bytes = img_io.read()
                            
                            frame_count += 1
                            consecutive_errors = 0  # Reset error counter on success
                            self.last_frame_time = datetime.now()
                            
                            if frame_count % 30 == 0:  # Log every 30 frames
                                print(f"Web streaming: frame {frame_count}, size: {image.size}, clients: {self.active_clients}")
                            
                            yield (b'--frame\r\n'
                                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                            
                        except Exception as e:
                            consecutive_errors += 1
                            print(f"Frame generation error {consecutive_errors}/{max_consecutive_errors}: {e}")
                            
                            if consecutive_errors >= max_consecutive_errors:
                                print("Too many consecutive errors, stopping frame generation")
                                break
                            
                            # Yield an error frame instead of breaking immediately
                            error_image = Image.new('RGB', (640, 480), color='yellow')
                            draw = ImageDraw.Draw(error_image)
                            draw.text((200, 220), "Frame Error:", fill='black')
                            draw.text((200, 240), str(e)[:40], fill='black')
                            draw.text((200, 260), f"Attempt {consecutive_errors}/{max_consecutive_errors}", fill='black')
                            
                            img_io = io.BytesIO()
                            error_image.save(img_io, 'JPEG')
                            img_io.seek(0)
                            error_bytes = img_io.read()
                            
                            yield (b'--frame\r\n'
                                   b'Content-Type: image/jpeg\r\n\r\n' + error_bytes + b'\r\n')
                            time.sleep(1)  # Wait before retrying
                    else:
                        print("Warning: picam2 object is None in generate_frames")
                        # Generate a "no camera" frame
                        no_camera_image = Image.new('RGB', (640, 480), color='blue')
                        draw = ImageDraw.Draw(no_camera_image)
                        draw.text((250, 220), "No Camera Object", fill='white')
                        draw.text((250, 240), "Check camera state", fill='white')
                        
                        img_io = io.BytesIO()
                        no_camera_image.save(img_io, 'JPEG')
                        img_io.seek(0)
                        no_camera_bytes = img_io.read()
                        
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' + no_camera_bytes + b'\r\n')
                        time.sleep(1)  # Wait before retrying
                            
                time.sleep(0.033)  # ~30 FPS for web
        
        except GeneratorExit:
            print("Frame generator closed by client")
        except Exception as e:
            print(f"Fatal error in frame generation: {e}")
        finally:
            self.frame_generation_active = False
            print("Frame generation stopped")
            
    def button_monitor_loop(self):
        """Monitor button presses"""
        while True:
            try:
                if not self.streaming:
                    # Display welcome menu when not streaming
                    network_status = "Connected" if self.network_monitor.is_network_stable() else "Unstable"
                    welcome_lines = [
                        "Pi Camera Stream",
                        "KEY1: Start Stream",
                        "KEY2: Exit",
                        f"Network: {network_status}"
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


@app.route('/cors-test')
def cors_test():
    """Test endpoint to verify CORS configuration"""
    origin = request.headers.get('Origin', 'No origin header')
    return jsonify({
        "message": "CORS test successful!",
        "origin": origin,
        "allowed": is_allowed_origin(origin),
        "timestamp": time.time(),
        "allowed_origins": ALLOWED_ORIGINS
    })
@app.route('/')
def index():
    """Main page with video stream"""
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    """Video streaming route with connection monitoring"""
    # Check if streaming is active and network is stable
    if not camera_stream.streaming:
        return create_placeholder_image("Camera Stream Not Started", "Press KEY1 to start")
    
    if not camera_stream.web_streaming:
        if not camera_stream.network_monitor.is_network_stable():
            return create_placeholder_image("Network Unstable", "Web streaming disabled")
        else:
            return create_placeholder_image("Web Streaming Disabled", "Check system status")
    
    # Increment active client counter
    camera_stream.active_clients += 1
    print(f"New client connected. Active clients: {camera_stream.active_clients}")
    
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
        
        # Add headers to prevent buffering and enable CORS
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.headers['X-Accel-Buffering'] = 'no'
        response.headers['Connection'] = 'keep-alive'
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response
        
    except Exception as e:
        # Cleanup on error
        camera_stream.active_clients = max(0, camera_stream.active_clients - 1)
        print(f"Error setting up stream for client: {e}")
        return create_placeholder_image("Streaming Error", str(e)[:50])

def create_placeholder_image(title, message):
    """Create a placeholder image with given title and message"""
    placeholder = Image.new('RGB', (640, 480), (0, 0, 0))  # Black background
    draw = ImageDraw.Draw(placeholder)
    draw.text((250, 220), title, fill=(255, 255, 255))  # White text
    draw.text((250, 240), message, fill=(255, 255, 255))
    
    img_io = io.BytesIO()
    placeholder.save(img_io, format='JPEG', quality=85)
    img_io.seek(0)
    
    response = Response(img_io.read(), mimetype='image/jpeg')
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Cache-Control'] = 'no-cache'
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
    """Get streaming and network status"""
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
        "active_clients": camera_stream.active_clients,
        "frame_generation_active": camera_stream.frame_generation_active,
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