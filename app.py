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

app = Flask(__name__)

# Pin definitions from ST7735S_buttons.txt
KEY1_PIN = 21  # Start video/streaming
KEY2_PIN = 20  # Exit program
KEY3_PIN = 16  # Stop video/streaming

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
        self.display_message(["Starting Stream...", "Web: Available", "LCD: Active", "Press KEY3 to stop"])
        time.sleep(2)
        
        # Set streaming flags first so start_camera knows what resolution to use
        self.streaming = True
        self.lcd_streaming = True
        self.web_streaming = True
        
        self.start_camera()
        
        # Start LCD streaming in a separate thread
        lcd_thread = threading.Thread(target=self.lcd_stream_loop)
        lcd_thread.daemon = True
        lcd_thread.start()
        
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
                        
                time.sleep(0.05)  # 20 FPS for LCD
        except Exception as e:
            print(f"LCD streaming error: {e}")
        
    def stop_streaming(self):
        """Stop all streaming"""
        self.streaming = False
        self.lcd_streaming = False
        self.web_streaming = False
        self.stop_camera()
        
        if self.lcd:
            self.display_message(["Stream Stopped", "Press KEY1 to start", "Press KEY2 to exit"])
                
    def generate_frames(self):
        """Generate frames for MJPEG web streaming"""
        frame_count = 0
        while self.web_streaming and self.streaming:
            with self.lock:
                if self.picam2:
                    try:
                        # Capture frame as numpy array
                        frame = self.picam2.capture_array()
                        
                        # Convert numpy array to PIL Image
                        image = Image.fromarray(frame)
                        
                        # Convert to JPEG using PIL
                        img_io = io.BytesIO()
                        image.save(img_io, format='JPEG', quality=85)
                        img_io.seek(0)
                        frame_bytes = img_io.read()
                        
                        frame_count += 1
                        if frame_count % 30 == 0:  # Log every 30 frames
                            print(f"Web streaming: frame {frame_count}, size: {image.size}")
                        
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                    except Exception as e:
                        print(f"Frame generation error: {e}")
                        # Yield an error frame instead of breaking
                        error_image = Image.new('RGB', (640, 480), color='yellow')
                        draw = ImageDraw.Draw(error_image)
                        draw.text((200, 220), "Frame Error:", fill='black')
                        draw.text((200, 240), str(e)[:40], fill='black')
                        
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
    """Video streaming route"""
    if camera_stream.streaming and camera_stream.web_streaming:
        try:
            return Response(camera_stream.generate_frames(),
                           mimetype='multipart/x-mixed-replace; boundary=frame')
        except Exception as e:
            # If there's an error with streaming, return an error image
            error_image = Image.new('RGB', (640, 480), color='red')
            draw = ImageDraw.Draw(error_image)
            draw.text((200, 220), f"Streaming Error:", fill='white')
            draw.text((200, 240), str(e)[:50], fill='white')
            
            img_io = io.BytesIO()
            error_image.save(img_io, 'JPEG')
            img_io.seek(0)
            
            return Response(img_io.read(), mimetype='image/jpeg')
    else:
        # Return a placeholder image when not streaming
        placeholder = Image.new('RGB', (640, 480), color='black')
        draw = ImageDraw.Draw(placeholder)
        if not camera_stream.streaming:
            draw.text((250, 220), "Camera Stream Not Started", fill='white')
            draw.text((280, 240), "Press KEY1 to start", fill='white')
        elif not camera_stream.web_streaming:
            draw.text((250, 220), "Web Streaming Disabled", fill='white')
        else:
            draw.text((250, 220), "Camera Not Active", fill='white')
        
        img_io = io.BytesIO()
        placeholder.save(img_io, 'JPEG')
        img_io.seek(0)
        
        return Response(img_io.read(), mimetype='image/jpeg')

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
    """Get streaming status"""
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
        "camera_object_exists": camera_stream.picam2 is not None
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