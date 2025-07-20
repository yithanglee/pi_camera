import LCD_1in44
import LCD_Config
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import RPi.GPIO as GPIO
import time
import sys
from picamera2 import Picamera2
import io

# Pin definitions from ST7735S_buttons.txt
KEY1_PIN = 21  # Start video
KEY2_PIN = 20  # Exit program
KEY3_PIN = 16  # Stop video

def setup_gpio():
    """Sets up GPIO pins for buttons."""
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(KEY1_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(KEY2_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(KEY3_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

def display_message(lcd, lines):
    """Displays multi-line messages on the LCD."""
    image = Image.new("RGB", (lcd.width, lcd.height), "WHITE")
    draw = ImageDraw.Draw(image)
    try:
        # Use a more common font if the original is not available
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 14)
    except IOError:
        font = ImageFont.load_default()
    
    y_text = 10
    for line in lines:
        draw.text((10, y_text), line, font=font, fill="BLACK")
        y_text += 20
    lcd.LCD_ShowImage(image, 0, 0)

def start_video_stream(lcd):
    """Starts the camera stream on the LCD using picamera2."""
    display_message(lcd, ["Starting Stream...", "Press KEY3 to stop."])
    time.sleep(2)

    picam2 = Picamera2()
    picam2.configure(picam2.create_preview_configuration(main={"size": (128, 128)}))
    picam2.start()

    try:
        while True:
            if not GPIO.input(KEY3_PIN):
                print("KEY3 pressed, stopping video stream.")
                break

            frame = picam2.capture_array()
            image = Image.fromarray(frame)
            lcd.LCD_ShowImage(image, 0, 0)
            time.sleep(0.05)  # Small delay for smoother visuals
    finally:
        picam2.stop()

def main():
    """Main function to run the application."""
    setup_gpio()
    lcd = LCD_1in44.LCD()
    Lcd_ScanDir = LCD_1in44.SCAN_DIR_DFT
    lcd.LCD_Init(Lcd_ScanDir)
    lcd.LCD_Clear()

    try:
        while True:
            # Display the welcome menu
            welcome_lines = [
                "Welcome!",
                "Press KEY1 for video",
                "Press KEY2 to exit"
            ]
            display_message(lcd, welcome_lines)
            
            # Wait for user input
            while True:
                if not GPIO.input(KEY1_PIN):
                    print("KEY1 pressed, starting video stream.")
                    start_video_stream(lcd)
                    # Break to redisplay the menu after the stream stops
                    break 
                
                if not GPIO.input(KEY2_PIN):
                    print("KEY2 pressed, exiting program.")
                    display_message(lcd, ["Goodbye!"])
                    time.sleep(1)
                    lcd.LCD_Clear()
                    GPIO.cleanup()
                    sys.exit()
                
                time.sleep(0.1) # Polling delay

    except KeyboardInterrupt:
        print("Program interrupted by user.")
    finally:
        lcd.LCD_Clear()
        GPIO.cleanup()

if __name__ == '__main__':
    main()
