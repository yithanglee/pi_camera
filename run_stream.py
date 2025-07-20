#!/usr/bin/env python3
"""
Pi Camera Streaming Server
Run this script to start the camera streaming server with LCD controls
"""

import sys
import os

def check_dependencies():
    """Check if all required dependencies are available"""
    try:
        import flask
        import cv2
        import RPi.GPIO
        import PIL
        import numpy
        print("✓ All Python dependencies found")
        return True
    except ImportError as e:
        print(f"✗ Missing dependency: {e}")
        print("Please install dependencies with: pip install -r requirements.txt")
        return False

def check_camera():
    """Check if camera is available"""
    try:
        from picamera2 import Picamera2
        picam2 = Picamera2()
        picam2.stop()  # Stop immediately after checking
        print("✓ Camera detected")
        return True
    except Exception as e:
        print(f"✗ Camera error: {e}")
        print("Make sure the camera is enabled and properly connected")
        return False

def check_lcd_modules():
    """Check if LCD modules are available"""
    try:
        import LCD_1in44
        import LCD_Config
        print("✓ LCD modules found")
        return True
    except ImportError as e:
        print(f"✗ LCD module missing: {e}")
        print("Make sure LCD_1in44.py and LCD_Config.py are in the current directory")
        return False

def main():
    """Main function to run the streaming server"""
    print("Pi Camera Streaming Server")
    print("=" * 40)
    
    # Check system requirements
    if not check_dependencies():
        sys.exit(1)
        
    if not check_lcd_modules():
        print("Warning: LCD modules not found. Some features may not work.")
        
    if not check_camera():
        print("Warning: Camera not detected. Streaming may not work.")
        
    print("\nStarting server...")
    print("Web interface will be available at:")
    print("  - Local: http://localhost:5000")
    print("  - Network: http://<your-pi-ip>:5000")
    print("\nPhysical controls:")
    print("  - KEY1 (GPIO 21): Start streaming")
    print("  - KEY2 (GPIO 20): Exit program")
    print("  - KEY3 (GPIO 16): Stop streaming")
    print("\nPress Ctrl+C to stop the server")
    print("=" * 40)
    
    try:
        # Import and run the main app
        from app import camera_stream
        import app
        
        # Start the application
        app.main()
        
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
    except Exception as e:
        print(f"Error running server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 