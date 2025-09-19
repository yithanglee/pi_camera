#!/usr/bin/env python3
"""
ESP32 Flash Tool with LCD UI
Uses the existing LCD interface to flash ESP32 with KEY1 button press
"""
import time
import subprocess
import threading
import RPi.GPIO as GPIO
from PIL import Image, ImageDraw, ImageFont
import LCD_1in44
import LCD_Config
import os
import sys

# Pin definitions (same as camera app)
KEY1_PIN = 21  # Flash ESP32
KEY2_PIN = 20  # Exit program
KEY3_PIN = 16  # Refresh status

# ESP32 Control pins
ESP32_EN_PIN = 4    # ESP32 EN (reset) - GPIO4
ESP32_GPIO0_PIN = 17  # ESP32 GPIO0 (boot mode) - GPIO17

# ESP32 Flash configuration
ESP32_PORT = "/dev/serial0"  # Pi UART pins (GPIO14/15)
ESP32_CHIP = "esp32"
ESP32_BAUD = 460800

# Flash file paths (assuming they're in the same directory as main.py)
FLASH_FILES = {
    "bootloader": "sketch_apr20a.ino.bootloader.bin",
    "partitions": "sketch_apr20a.ino.partitions.bin", 
    "firmware": "sketch_apr20a.ino.bin"
}

# Flash addresses
FLASH_ADDRESSES = {
    "bootloader": "0x1000",
    "partitions": "0x8000",
    "firmware": "0x10000"
}

class ESP32Flasher:
    def __init__(self):
        self.lcd = None
        self.flashing = False
        self.flash_progress = ""
        self.setup_lcd()
        self.setup_gpio()
        self.check_files()
        
    def setup_gpio(self):
        """Sets up GPIO pins for buttons and ESP32 control."""
        GPIO.setmode(GPIO.BCM)
        # Button pins
        GPIO.setup(KEY1_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(KEY2_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(KEY3_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        
        # ESP32 control pins
        GPIO.setup(ESP32_EN_PIN, GPIO.OUT, initial=GPIO.HIGH)    # EN high = normal operation
        GPIO.setup(ESP32_GPIO0_PIN, GPIO.OUT, initial=GPIO.HIGH) # GPIO0 high = normal boot
        
    def setup_lcd(self):
        """Initialize the LCD display."""
        try:
            self.lcd = LCD_1in44.LCD()
            Lcd_ScanDir = LCD_1in44.SCAN_DIR_DFT
            self.lcd.LCD_Init(Lcd_ScanDir)
            self.lcd.LCD_Clear()
            print("LCD initialized successfully")
        except Exception as e:
            print(f"LCD initialization error: {e}")
            self.lcd = None
            
    def display_message(self, lines, color="BLACK", bg_color="WHITE"):
        """Displays multi-line messages on the LCD."""
        if not self.lcd:
            print("LCD not available:", " | ".join(lines))
            return
            
        try:
            image = Image.new("RGB", (self.lcd.width, self.lcd.height), bg_color)
            draw = ImageDraw.Draw(image)
            
            try:
                font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 11)
            except IOError:
                try:
                    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 11)
                except IOError:
                    font = ImageFont.load_default()
            
            y_text = 8
            for line in lines:
                # Wrap long lines
                if len(line) > 18:  # Approximate character limit for LCD width
                    words = line.split(' ')
                    current_line = ""
                    for word in words:
                        if len(current_line + word) < 18:
                            current_line += word + " "
                        else:
                            if current_line:
                                draw.text((2, y_text), current_line.strip(), font=font, fill=color)
                                y_text += 14
                            current_line = word + " "
                    if current_line:
                        draw.text((2, y_text), current_line.strip(), font=font, fill=color)
                        y_text += 14
                else:
                    draw.text((2, y_text), line, font=font, fill=color)
                    y_text += 14
                    
                # Prevent text from going off screen
                if y_text > self.lcd.height - 14:
                    break
                    
            self.lcd.LCD_ShowImage(image, 0, 0)
        except Exception as e:
            print(f"Display error: {e}")
    
    def esp32_enter_download_mode(self):
        """Put ESP32 into download mode for flashing."""
        print("Putting ESP32 into download mode...")
        self.display_message(["ESP32 Setup", "Entering download", "mode..."], color="WHITE", bg_color="BLUE")
        
        # GPIO0 low = download mode, EN pulse = reset
        GPIO.output(ESP32_GPIO0_PIN, GPIO.LOW)   # Pull GPIO0 low
        time.sleep(0.1)
        GPIO.output(ESP32_EN_PIN, GPIO.LOW)      # Reset ESP32
        time.sleep(0.1) 
        GPIO.output(ESP32_EN_PIN, GPIO.HIGH)     # Release reset
        time.sleep(0.5)                          # Wait for ESP32 to enter download mode
        
        print("ESP32 should now be in download mode")
    
    def esp32_exit_download_mode(self):
        """Reset ESP32 to normal operation mode."""
        print("Resetting ESP32 to normal mode...")
        
        # GPIO0 high = normal boot, EN pulse = reset
        GPIO.output(ESP32_GPIO0_PIN, GPIO.HIGH)  # Release GPIO0 for normal boot
        time.sleep(0.1)
        GPIO.output(ESP32_EN_PIN, GPIO.LOW)      # Reset ESP32
        time.sleep(0.1)
        GPIO.output(ESP32_EN_PIN, GPIO.HIGH)     # Release reset
        time.sleep(0.5)                          # Wait for normal boot
        
        print("ESP32 reset to normal operation")
        
    def check_files(self):
        """Check if all required flash files exist."""
        self.files_status = {}
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        for file_type, filename in FLASH_FILES.items():
            filepath = os.path.join(script_dir, filename)
            self.files_status[file_type] = os.path.exists(filepath)
            
        return all(self.files_status.values())
    
    def get_status_display(self):
        """Get current status for display."""
        status_lines = ["ESP32 Flasher"]
        
        # Show file status
        all_files_ok = all(self.files_status.values())
        if all_files_ok:
            status_lines.append("Files: OK")
        else:
            status_lines.append("Files: MISSING")
            for file_type, exists in self.files_status.items():
                if not exists:
                    status_lines.append(f"  {file_type}: NO")
        
        # Show UART status  
        if os.path.exists(ESP32_PORT):
            status_lines.append("UART: Ready")
        else:
            status_lines.append("UART: Check wiring")
            
        # Show controls
        if all_files_ok and os.path.exists(ESP32_PORT):
            status_lines.extend([
                "",
                "KEY1: Flash ESP32",
                "KEY2: Exit",
                "KEY3: Refresh"
            ])
        else:
            status_lines.extend([
                "",
                "Fix issues first",
                "KEY2: Exit",
                "KEY3: Refresh"
            ])
            
        return status_lines
    
    def flash_esp32(self):
        """Flash the ESP32 with the binary files."""
        if self.flashing:
            return
            
        self.flashing = True
        
        try:
            # Check prerequisites
            if not all(self.files_status.values()):
                self.display_message(["Flash FAILED", "Missing files"], color="WHITE", bg_color="RED")
                time.sleep(3)
                return
                
            if not os.path.exists(ESP32_PORT):
                self.display_message(["Flash FAILED", "UART not available", "Check wiring"], color="WHITE", bg_color="RED")
                time.sleep(3)
                return
            
            # Put ESP32 into download mode
            self.esp32_enter_download_mode()
            
            # Show starting message
            self.display_message(["FLASHING ESP32", "Please wait...", "", "Do not disconnect"], color="WHITE", bg_color="BLUE")
            
            # Build esptool command
            script_dir = os.path.dirname(os.path.abspath(__file__))
            
            cmd = [
                "esptool.py",
                "--chip", ESP32_CHIP,
                "--port", ESP32_PORT,
                "--baud", str(ESP32_BAUD),
                "write_flash", "-z"
            ]
            
            # Add each file with its address
            for file_type in ["bootloader", "partitions", "firmware"]:
                address = FLASH_ADDRESSES[file_type]
                filename = FLASH_FILES[file_type]
                filepath = os.path.join(script_dir, filename)
                cmd.extend([address, filepath])
            
            print(f"Executing: {' '.join(cmd)}")
            
            # Execute the flash command
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                cwd=script_dir
            )
            
            # Monitor progress
            progress_lines = ["FLASHING...", "", ""]
            line_count = 0
            
            for line in iter(process.stdout.readline, ''):
                line = line.strip()
                if line:
                    print(f"esptool: {line}")
                    
                    # Update progress display
                    if "Writing at" in line or "%" in line:
                        progress_lines[1] = line[:16]  # Truncate for LCD
                    elif "Connecting" in line:
                        progress_lines[1] = "Connecting..."
                    elif "Chip is" in line:
                        progress_lines[1] = "Connected"
                    elif "Erasing" in line:
                        progress_lines[1] = "Erasing..."
                    elif "Writing" in line and "0x" in line:
                        progress_lines[1] = "Writing flash..."
                        
                    # Update display every few lines
                    line_count += 1
                    if line_count % 3 == 0:
                        self.display_message(progress_lines, color="WHITE", bg_color="BLUE")
            
            # Wait for process to complete
            return_code = process.wait()
            
            if return_code == 0:
                # Reset ESP32 to normal mode after successful flash
                self.esp32_exit_download_mode()
                
                self.display_message([
                    "FLASH SUCCESS!",
                    "",
                    "ESP32 programmed",
                    "& reset to run"
                ], color="WHITE", bg_color="GREEN")
                print("ESP32 flashing completed successfully!")
            else:
                # Reset ESP32 even if flash failed
                self.esp32_exit_download_mode()
                
                self.display_message([
                    "FLASH FAILED",
                    f"Error code: {return_code}",
                    "",
                    "Check connections"
                ], color="WHITE", bg_color="RED")
                print(f"ESP32 flashing failed with code: {return_code}")
                
        except FileNotFoundError:
            # Reset ESP32 on error
            self.esp32_exit_download_mode()
            
            self.display_message([
                "FLASH FAILED",
                "esptool.py not found",
                "",
                "Install esptool"
            ], color="WHITE", bg_color="RED")
            print("esptool.py not found. Install with: pip install esptool")
            
        except Exception as e:
            # Reset ESP32 on error
            self.esp32_exit_download_mode()
            
            self.display_message([
                "FLASH FAILED", 
                "Error occurred:",
                str(e)[:16]
            ], color="WHITE", bg_color="RED")
            print(f"Flash error: {e}")
            
        finally:
            self.flashing = False
            time.sleep(3)  # Show result for 3 seconds
    
    def button_monitor_loop(self):
        """Monitor button presses."""
        last_display_update = 0
        
        while True:
            try:
                current_time = time.time()
                
                # Update display every 2 seconds when not flashing
                if not self.flashing and (current_time - last_display_update > 2):
                    self.check_files()  # Refresh file status
                    status_lines = self.get_status_display()
                    self.display_message(status_lines)
                    last_display_update = current_time
                
                # Check button presses
                if not GPIO.input(KEY1_PIN) and not self.flashing:
                    print("KEY1 pressed, starting ESP32 flash.")
                    flash_thread = threading.Thread(target=self.flash_esp32)
                    flash_thread.daemon = True
                    flash_thread.start()
                    time.sleep(0.5)  # Debounce
                    
                if not GPIO.input(KEY2_PIN):
                    print("KEY2 pressed, exiting program.")
                    self.display_message(["Goodbye!", "Shutting down..."])
                    time.sleep(1)
                    if self.lcd:
                        self.lcd.LCD_Clear()
                    GPIO.cleanup()
                    sys.exit(0)
                    
                if not GPIO.input(KEY3_PIN) and not self.flashing:
                    print("KEY3 pressed, refreshing status.")
                    self.check_files()
                    status_lines = self.get_status_display()
                    self.display_message(status_lines)
                    last_display_update = current_time
                    time.sleep(0.5)  # Debounce
                    
                time.sleep(0.1)  # Polling delay
                
            except KeyboardInterrupt:
                print("Keyboard interrupt received")
                break
            except Exception as e:
                print(f"Button monitor error: {e}")
                time.sleep(1)

def main():
    """Main function"""
    print("ESP32 Flasher starting...")
    print("Controls:")
    print("KEY1 (GPIO 21): Flash ESP32")
    print("KEY2 (GPIO 20): Exit program") 
    print("KEY3 (GPIO 16): Refresh status")
    print(f"Expected flash files in {os.path.dirname(os.path.abspath(__file__))}:")
    for file_type, filename in FLASH_FILES.items():
        print(f"  {file_type}: {filename}")
    
    try:
        flasher = ESP32Flasher()
        flasher.button_monitor_loop()
    except KeyboardInterrupt:
        print("Shutting down...")
    except Exception as e:
        print(f"Main error: {e}")
    finally:
        try:
            GPIO.cleanup()
        except:
            pass

if __name__ == '__main__':
    main()
