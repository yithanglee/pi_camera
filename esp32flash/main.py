#!/usr/bin/env python3
"""
ESP32 Flash Tool with LCD UI
Uses the existing LCD interface to flash ESP32 with KEY1 button press
"""
import time
import subprocess
import threading
import re
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
        self.current_stage = ""
        self.current_percent = 0
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
    
    def display_progress(self, stage, percent, details=""):
        """Display progress with progress bar on LCD."""
        if not self.lcd:
            print(f"Progress: {stage} {percent}% {details}")
            return
            
        try:
            image = Image.new("RGB", (self.lcd.width, self.lcd.height), "BLUE")
            draw = ImageDraw.Draw(image)
            
            try:
                font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 10)
            except IOError:
                try:
                    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 10)
                except IOError:
                    font = ImageFont.load_default()
            
            # Title
            draw.text((2, 2), "ESP32 FLASHING", font=font, fill="WHITE")
            
            # Stage
            stage_text = stage[:18]  # Truncate if too long
            draw.text((2, 16), stage_text, font=font, fill="WHITE")
            
            # Progress percentage
            draw.text((2, 30), f"{percent}%", font=font, fill="WHITE")
            
            # Progress bar
            bar_x = 2
            bar_y = 45
            bar_width = self.lcd.width - 4
            bar_height = 8
            
            # Background bar
            draw.rectangle([bar_x, bar_y, bar_x + bar_width, bar_y + bar_height], 
                          outline="WHITE", fill="DARKBLUE")
            
            # Progress fill
            if percent > 0:
                fill_width = int((bar_width - 2) * percent / 100)
                draw.rectangle([bar_x + 1, bar_y + 1, bar_x + 1 + fill_width, bar_y + bar_height - 1], 
                              fill="WHITE")
            
            # Details (if any)
            if details:
                details_text = details[:18]  # Truncate if too long
                draw.text((2, 58), details_text, font=font, fill="WHITE")
                
            self.lcd.LCD_ShowImage(image, 0, 0)
        except Exception as e:
            print(f"Progress display error: {e}")
    
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
    
    def parse_esptool_line(self, line):
        """Parse esptool output line and extract progress information."""
        
        line = line.strip()
        
        # Extract percentage from "Writing at 0x... (XX %)" lines
        percent_match = re.search(r'\((\d+) %\)', line)
        if percent_match:
            self.current_percent = int(percent_match.group(1))
        
        # Determine current stage
        if "Connecting" in line:
            self.current_stage = "Connecting"
            self.current_percent = 0
        elif "Chip is" in line:
            self.current_stage = "Connected"
            self.current_percent = 5
        elif "Flash will be erased" in line:
            self.current_stage = "Erasing Flash"
            self.current_percent = 10
        elif "Compressed" in line and "bytes to" in line:
            self.current_stage = "Compressing"
            self.current_percent = 15
        elif "Writing at 0x00001000" in line:
            self.current_stage = "Bootloader"
        elif "Writing at 0x00008000" in line:
            self.current_stage = "Partitions"  
        elif "Writing at 0x00010000" in line:
            self.current_stage = "Firmware"
        elif "Wrote" in line and "bytes" in line:
            if "0x00001000" in line:
                self.current_stage = "Bootloader Done"
            elif "0x00008000" in line:
                self.current_stage = "Partitions Done"
            elif "0x00010000" in line:
                self.current_stage = "Firmware Done"
        elif "Hash of data verified" in line:
            self.current_stage = "Verifying"
        elif "Leaving" in line:
            self.current_stage = "Complete"
            self.current_percent = 100
        elif "Hard resetting" in line:
            self.current_stage = "Resetting"
            
        return self.current_stage, self.current_percent
    
    def download_firmware(self):
        """Download and extract firmware files from server."""
        if self.flashing:
            return
            
        self.flashing = True  # Prevent other operations during download
        
        try:
            # Show download starting
            self.display_message(["DOWNLOADING", "Firmware files...", "", "Please wait"], color="WHITE", bg_color="ORANGE")
            
            script_dir = os.path.dirname(os.path.abspath(__file__))
            temp_zip = os.path.join(script_dir, "temp.zip")
            
            # Download command
            download_url = "https://jreporting.jimatlabs.com/uploads/vids/ino/sketch_apr20aw9.ino.zip"
            
            print("Downloading firmware files...")
            
            # Execute wget command
            cmd = ["wget", "-O", temp_zip, download_url]
            result = subprocess.run(cmd, cwd=script_dir, capture_output=True, text=True)
            
            if result.returncode != 0:
                self.display_message(["DOWNLOAD FAILED", "Check network", "connection"], color="WHITE", bg_color="RED")
                print(f"wget failed: {result.stderr}")
                time.sleep(3)
                return
            
            # Show extraction
            self.display_message(["EXTRACTING", "Files...", "", "Almost done"], color="WHITE", bg_color="ORANGE")
            
            # Extract files
            cmd = ["unzip", "-o", temp_zip]
            result = subprocess.run(cmd, cwd=script_dir, capture_output=True, text=True)
            
            if result.returncode != 0:
                self.display_message(["EXTRACT FAILED", "Invalid zip file"], color="WHITE", bg_color="RED")
                print(f"unzip failed: {result.stderr}")
                time.sleep(3)
                return
            
            # Clean up temp file
            if os.path.exists(temp_zip):
                os.remove(temp_zip)
            
            # Check if files were extracted successfully
            self.check_files()
            all_files_ok = all(self.files_status.values())
            
            if all_files_ok:
                self.display_message([
                    "DOWNLOAD SUCCESS!",
                    "",
                    "All files ready",
                    "Press KEY1 to flash"
                ], color="WHITE", bg_color="GREEN")
                print("Firmware files downloaded successfully!")
            else:
                missing_files = [f for f, exists in self.files_status.items() if not exists]
                self.display_message([
                    "PARTIAL SUCCESS",
                    f"Missing: {missing_files[0]}",
                    "Check files"
                ], color="WHITE", bg_color="ORANGE")
                print(f"Some files still missing: {missing_files}")
                
        except FileNotFoundError as e:
            if "wget" in str(e):
                self.display_message([
                    "DOWNLOAD FAILED",
                    "wget not found",
                    "Install wget"
                ], color="WHITE", bg_color="RED")
                print("wget not found. Install with: sudo apt install wget")
            elif "unzip" in str(e):
                self.display_message([
                    "EXTRACT FAILED", 
                    "unzip not found",
                    "Install unzip"
                ], color="WHITE", bg_color="RED")
                print("unzip not found. Install with: sudo apt install unzip")
            else:
                self.display_message([
                    "DOWNLOAD FAILED",
                    "Missing tools"
                ], color="WHITE", bg_color="RED")
                print(f"Tool not found: {e}")
            time.sleep(3)
            
        except Exception as e:
            self.display_message([
                "DOWNLOAD FAILED",
                "Error occurred:",
                str(e)[:16]
            ], color="WHITE", bg_color="RED")
            print(f"Download error: {e}")
            time.sleep(3)
            
        finally:
            self.flashing = False
        
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
        status_lines = ["ESP32 Flasher Enhanced"]
        
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
                "KEY3: Download FW"
            ])
        else:
            status_lines.extend([
                "",
                "KEY1: Flash (check files)",
                "KEY2: Exit",
                "KEY3: Download FW"
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
            
            # Initialize progress
            self.current_stage = "Starting"
            self.current_percent = 0
            self.display_progress("Starting", 0)
            
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
            
            # Monitor progress with enhanced parsing
            for line in iter(process.stdout.readline, ''):
                if not line:
                    break
                    
                line = line.strip()
                if line:
                    print(f"esptool: {line}")
                    
                    # Parse the line and update progress
                    stage, percent = self.parse_esptool_line(line)
                    
                    # Extract details for display
                    details = ""
                    if "Writing at 0x" in line:
                        # Extract address for display
                        addr_match = re.search(r'0x([0-9a-f]+)', line)
                        if addr_match:
                            details = f"@{addr_match.group(1)[:6]}"
                    elif "bytes" in line and ("compressed" in line or "Wrote" in line):
                        # Extract byte count
                        bytes_match = re.search(r'(\d+) bytes', line)
                        if bytes_match:
                            bytes_count = int(bytes_match.group(1))
                            if bytes_count > 1000:
                                details = f"{bytes_count//1000}KB"
                            else:
                                details = f"{bytes_count}B"
                    
                    # Update display
                    self.display_progress(stage, percent, details)
                    time.sleep(0.1)  # Small delay for LCD update
            
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
                    print("KEY3 pressed, downloading firmware.")
                    download_thread = threading.Thread(target=self.download_firmware)
                    download_thread.daemon = True
                    download_thread.start()
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
    print("ESP32 Flasher Enhanced starting...")
    print("Controls:")
    print("KEY1 (GPIO 21): Flash ESP32")
    print("KEY2 (GPIO 20): Exit program") 
    print("KEY3 (GPIO 16): Download firmware")
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
