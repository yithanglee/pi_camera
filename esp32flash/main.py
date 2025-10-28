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

# ESP32 Flash configuration - Multiple connection support
ESP32_PORTS = [
    "/dev/ttyUSB0",    # USB connection (most common)
    "/dev/ttyUSB1",    # USB connection (alternative)
    "/dev/ttyACM0",    # USB connection (some ESP32 boards)
    "/dev/serial0",    # Pi UART pins (GPIO14/15)
    "/dev/ttyAMA0",    # Pi UART alternative
    "/dev/ttyS0"       # Pi UART alternative
]
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
        self.current_page = 1  # 1 = main (flash/download), 2 = network utils
        self.key3_pressed_at = None  # For detecting long press on right key
        # Firmware URLs (both default to same; update URL_2 as needed)
        self.FIRMWARE_URL_1 = "https://jreporting.jimatlabs.com/uploads/vids/ino/sketch_apr20aw9.ino.zip"
        self.FIRMWARE_URL_2 = "https://jreporting.jimatlabs.com/uploads/vids/ino/sketch_apr20aw10.ino.zip"
        # Directories
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.SLOT_DIRS = {
            1: os.path.join(self.script_dir, "fw1"),
            2: os.path.join(self.script_dir, "fw2"),
        }
        # Per-slot file status
        self.files_status_1 = {k: False for k in FLASH_FILES}
        self.files_status_2 = {k: False for k in FLASH_FILES}
        self.setup_lcd()
        self.setup_gpio()
        self.ensure_slot_dirs()
        self.check_files()  # initialize statuses for both slots
        
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
        port, conn_type = self.detect_esp32_port()
        
        if conn_type == "UART":
            # Use GPIO control for UART connection
            print("Using GPIO control for UART connection")
            self.display_message(["ESP32 Setup", "GPIO download mode", "UART connection"], 
                               color="WHITE", bg_color="BLUE")
            
            GPIO.output(ESP32_GPIO0_PIN, GPIO.LOW)   # Pull GPIO0 low
            time.sleep(0.1)
            GPIO.output(ESP32_EN_PIN, GPIO.LOW)      # Reset ESP32
            time.sleep(0.1) 
            GPIO.output(ESP32_EN_PIN, GPIO.HIGH)     # Release reset
            time.sleep(0.5)                          # Wait for ESP32 to enter download mode
            
            print("ESP32 should now be in download mode")
        else:
            # USB connection - either manual or GPIO-controlled custom cable
            print("USB connection detected")
            self.display_message(["ESP32 Setup", "USB connection", "Auto-detecting..."], 
                               color="WHITE", bg_color="BLUE")
            
            # Try GPIO control first (in case it's a custom cable)
            try:
                GPIO.output(ESP32_GPIO0_PIN, GPIO.LOW)   # Pull GPIO0 low
                time.sleep(0.1)
                GPIO.output(ESP32_EN_PIN, GPIO.LOW)      # Reset ESP32
                time.sleep(0.1) 
                GPIO.output(ESP32_EN_PIN, GPIO.HIGH)     # Release reset
                time.sleep(0.5)
                print("GPIO control attempted for USB connection")
            except:
                # GPIO control not available - show manual instructions
                self.display_message(["ESP32 Setup", "USB Manual Mode:", "Hold BOOT, Press EN"], 
                                   color="WHITE", bg_color="ORANGE")
                time.sleep(3)  # Give user time to see message
                print("Manual boot mode required - hold BOOT, press EN")
    
    def esp32_exit_download_mode(self):
        """Reset ESP32 to normal operation mode."""
        port, conn_type = self.detect_esp32_port()
        
        if conn_type == "UART":
            # Use GPIO control for UART connection
            print("Resetting ESP32 to normal mode via GPIO...")
            
            GPIO.output(ESP32_GPIO0_PIN, GPIO.HIGH)  # Release GPIO0 for normal boot
            time.sleep(0.1)
            GPIO.output(ESP32_EN_PIN, GPIO.LOW)      # Reset ESP32
            time.sleep(0.1)
            GPIO.output(ESP32_EN_PIN, GPIO.HIGH)     # Release reset
            time.sleep(0.5)                          # Wait for normal boot
            
            print("ESP32 reset to normal operation")
        else:
            # USB connection
            print("USB connection - attempting GPIO reset...")
            
            try:
                # Try GPIO control (custom cable)
                GPIO.output(ESP32_GPIO0_PIN, GPIO.HIGH)  # Release GPIO0 for normal boot
                time.sleep(0.1)
                GPIO.output(ESP32_EN_PIN, GPIO.LOW)      # Reset ESP32
                time.sleep(0.1)
                GPIO.output(ESP32_EN_PIN, GPIO.HIGH)     # Release reset
                time.sleep(0.5)
                print("GPIO reset completed for USB connection")
            except:
                # Manual reset or auto-reset after flashing
                print("USB connection - ESP32 will auto-reset or press EN button manually")
    
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
    
    def build_cache_busted_url(self, base_url):
        """Append a cache-busting timestamp query parameter to the URL."""
        try:
            sep = '&' if '?' in base_url else '?'
            return f"{base_url}{sep}v={int(time.time())}"
        except Exception:
            return base_url

    def ensure_slot_dirs(self):
        """Ensure firmware slot directories exist."""
        for _, d in self.SLOT_DIRS.items():
            try:
                os.makedirs(d, exist_ok=True)
            except Exception:
                pass

    def get_slot_dir(self, slot_index):
        return self.SLOT_DIRS.get(slot_index, self.SLOT_DIRS[1])

    def check_files_slot(self, slot_index):
        """Check files presence in a specific slot directory."""
        slot_dir = self.get_slot_dir(slot_index)
        status = {}
        for file_type, filename in FLASH_FILES.items():
            filepath = os.path.join(slot_dir, filename)
            status[file_type] = os.path.exists(filepath)
        if slot_index == 1:
            self.files_status_1 = status
        else:
            self.files_status_2 = status
        return status

    def all_files_ok(self, slot_index):
        status = self.files_status_1 if slot_index == 1 else self.files_status_2
        return all(status.values())

    def download_firmware(self, url_index=1):
        """Download and extract firmware files from server.
        url_index: 1 for primary URL, 2 for secondary URL
        """
        if self.flashing:
            return
            
        self.flashing = True  # Prevent other operations during download
        
        try:
            # Show download starting
            self.display_message(["DOWNLOADING", "Firmware files...", "", "Please wait"], color="WHITE", bg_color="ORANGE")
            
            temp_zip = os.path.join(self.script_dir, "temp.zip")
            target_dir = self.get_slot_dir(url_index)
            
            # Download command
            base_url = self.FIRMWARE_URL_1 if url_index == 1 else self.FIRMWARE_URL_2
            download_url = self.build_cache_busted_url(base_url)
            
            print("Downloading firmware files...")
            
            # Execute wget command
            cmd = [
                "wget",
                "--no-cache",
                "--header", "Cache-Control: no-cache",
                "--header", "Pragma: no-cache",
                "-O", temp_zip,
                download_url
            ]
            result = subprocess.run(cmd, cwd=self.script_dir, capture_output=True, text=True)
            
            if result.returncode != 0:
                self.display_message(["DOWNLOAD FAILED", "Check network", "connection"], color="WHITE", bg_color="RED")
                print(f"wget failed: {result.stderr}")
                time.sleep(3)
                return
            
            # Show extraction
            self.display_message(["EXTRACTING", "Files...", "", "Almost done"], color="WHITE", bg_color="ORANGE")
            
            # Extract files
            cmd = ["unzip", "-o", temp_zip, "-d", target_dir]
            result = subprocess.run(cmd, cwd=self.script_dir, capture_output=True, text=True)
            
            if result.returncode != 0:
                self.display_message(["EXTRACT FAILED", "Invalid zip file"], color="WHITE", bg_color="RED")
                print(f"unzip failed: {result.stderr}")
                time.sleep(3)
                return
            
            # Clean up temp file
            if os.path.exists(temp_zip):
                os.remove(temp_zip)
            
            # Check if files were extracted successfully
            self.check_files_slot(url_index)
            all_files_ok = self.all_files_ok(url_index)
            
            if all_files_ok:
                self.display_message([
                    "DOWNLOAD SUCCESS!",
                    "",
                    "All files ready",
                    "Ready to flash"
                ], color="WHITE", bg_color="GREEN")
                print("Firmware files downloaded successfully!")
            else:
                status = self.files_status_1 if url_index == 1 else self.files_status_2
                missing_files = [f for f, exists in status.items() if not exists]
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
    
    def detect_esp32_port(self):
        """Detect available ESP32 connection port and type."""
        for port in ESP32_PORTS:
            if os.path.exists(port):
                try:
                    # Determine connection type
                    if "ttyUSB" in port or "ttyACM" in port:
                        conn_type = "USB"
                    else:
                        conn_type = "UART"
                    
                    print(f"Found ESP32 port: {port} ({conn_type})")
                    return port, conn_type
                except Exception as e:
                    print(f"Port {port} exists but not accessible: {e}")
                    continue
        
        print("No ESP32 ports found")
        return None, None
        
    def check_files(self):
        """Check files in both slots."""
        self.check_files_slot(1)
        self.check_files_slot(2)
        return self.all_files_ok(1) and self.all_files_ok(2)
    
    def get_status_display(self):
        """Get current status for display (page-aware)."""
        status_lines = ["ESP32 Flasher Enhanced"]
        
        if self.current_page == 1:
            # Show file status
            self.check_files_slot(1)
            all_files_ok = self.all_files_ok(1)
            if all_files_ok:
                status_lines.append("Files: OK")
            else:
                status_lines.append("Files: MISSING")
                for file_type, exists in self.files_status_1.items():
                    if not exists:
                        status_lines.append(f"  {file_type}: NO")
            
            # Show connection status
            port, conn_type = self.detect_esp32_port()
            if port:
                port_short = port.split('/')[-1]
                status_lines.append(f"{conn_type}: {port_short}")
            else:
                status_lines.append("No ESP32 found")
            
            # Controls (Page 1)
            status_lines.extend([
                "",
                "KEY1: Flash ESP32",
                "KEY2: Download FW1",
                "KEY3: Download FW2",
                "Hold RIGHT: Page 2"
            ])
        else:
            # Page 2: Network utilities
            # Show file status for slot 2
            self.check_files_slot(2)
            all_files_ok_2 = self.all_files_ok(2)
            status_lines.append("Files2: OK" if all_files_ok_2 else "Files2: MISSING")
            status_lines.extend([
                "Page 2: Network",
                "",
                "KEY1: Start AP mode",
                "KEY2: WiFi status",
                "KEY3: Flash fw2",
            ])
        
        return status_lines

    def start_ap_mode(self):
        """Attempt to start Wi-Fi AP mode on wlan0 using NetworkManager (nmcli)."""
        try:
            self.display_message(["AP MODE", "Starting...", "SSID: PiZero2-AP"], color="WHITE", bg_color="ORANGE")
            script_dir = os.path.dirname(os.path.abspath(__file__))
            # Try nmcli hotspot
            cmd = [
                "nmcli", "dev", "wifi", "hotspot",
                "ifname", "wlan0",
                "ssid", "PiZero2-AP",
                "password", "pizerow2AP"
            ]
            result = subprocess.run(cmd, cwd=script_dir, capture_output=True, text=True)
            if result.returncode == 0:
                self.display_message(["AP MODE", "Started", "SSID: PiZero2-AP"], color="WHITE", bg_color="GREEN")
                time.sleep(2)
                return
            # Fallback: try create_ap if available
            cmd_check = subprocess.run(["which", "create_ap"], capture_output=True, text=True)
            if cmd_check.returncode == 0:
                cmd2 = ["create_ap", "wlan0", "eth0", "PiZero2-AP", "pizerow2AP", "-n"]
                result2 = subprocess.run(cmd2, capture_output=True, text=True)
                if result2.returncode == 0:
                    self.display_message(["AP MODE", "Started", "SSID: PiZero2-AP"], color="WHITE", bg_color="GREEN")
                    time.sleep(2)
                    return
            # If all failed
            self.display_message(["AP FAILED", "Install nmcli", "or create_ap"], color="WHITE", bg_color="RED")
            print(f"AP start failed. nmcli: {result.stderr}")
            time.sleep(2)
        except Exception as e:
            self.display_message(["AP ERROR", str(e)[:16]], color="WHITE", bg_color="RED")
            print(f"AP mode error: {e}")
            time.sleep(2)

    def show_wifi_status(self):
        """Display basic Wi-Fi status details."""
        try:
            ssid = ""
            ip4 = ""
            link = ""
            # SSID
            try:
                out = subprocess.run(["iwgetid", "-r"], capture_output=True, text=True)
                if out.returncode == 0:
                    ssid = out.stdout.strip()
            except Exception:
                pass
            # IP
            try:
                out = subprocess.run(["hostname", "-I"], capture_output=True, text=True)
                if out.returncode == 0:
                    ip4 = out.stdout.strip().split(" ")[0]
            except Exception:
                pass
            # Link state
            try:
                out = subprocess.run(["iw", "dev", "wlan0", "link"], capture_output=True, text=True)
                if out.returncode == 0:
                    first_line = out.stdout.strip().splitlines()[0] if out.stdout else ""
                    link = first_line[:18]
            except Exception:
                pass
            lines = [
                "WiFi Status",
                f"SSID: {ssid[:12] if ssid else 'N/A'}",
                f"IP: {ip4[:14] if ip4 else 'N/A'}",
                link if link else ""
            ]
            self.display_message([l for l in lines if l], color="WHITE", bg_color="BLUE")
            time.sleep(2)
        except Exception as e:
            self.display_message(["WiFi Error", str(e)[:16]], color="WHITE", bg_color="RED")
            print(f"WiFi status error: {e}")
            time.sleep(2)
    
    def download_then_flash_url2(self):
        """Download firmware from URL 2 into slot 2, then flash from slot 2."""
        try:
            # Download URL2
            self.download_firmware(url_index=2)
            # After download attempt, if files are all present, flash
            if self.all_files_ok(2):
                self.display_message(["FLASHING", "From URL2 files"], color="WHITE", bg_color="ORANGE")
                self.flash_esp32(slot_index=2)
            else:
                self.display_message(["CANNOT FLASH", "Files missing"], color="WHITE", bg_color="RED")
                time.sleep(2)
        except Exception as e:
            self.display_message(["URL2 FLASH ERR", str(e)[:16]], color="WHITE", bg_color="RED")
            print(f"download_then_flash_url2 error: {e}")
            time.sleep(2)

    def flash_esp32(self, slot_index=1):
        """Flash the ESP32 with the binary files from a specific slot."""
        if self.flashing:
            return
            
        self.flashing = True
        
        try:
            # Check prerequisites
            self.check_files_slot(slot_index)
            if not self.all_files_ok(slot_index):
                self.display_message(["Flash FAILED", "Missing files"], color="WHITE", bg_color="RED")
                time.sleep(3)
                return
                
            # Detect ESP32 port
            port, conn_type = self.detect_esp32_port()
            if not port:
                self.display_message(["Flash FAILED", "No ESP32 found", "Check connections"], color="WHITE", bg_color="RED")
                time.sleep(3)
                return
            
            # Show detected connection
            port_name = port.split('/')[-1]
            print(f"Using {conn_type} connection: {port}")
            
            # Put ESP32 into download mode
            self.esp32_enter_download_mode()
            
            # Initialize progress
            self.current_stage = "Starting"
            self.current_percent = 0
            self.display_progress(f"Starting {conn_type}", 0)
            
            # Build esptool command
            slot_dir = self.get_slot_dir(slot_index)
            
            cmd = [
                "esptool.py",
                "--chip", ESP32_CHIP,
                "--port", port,  # Use detected port
                "--baud", str(ESP32_BAUD),
                "write_flash", "-z"
            ]
            
            # Add each file with its address
            for file_type in ["bootloader", "partitions", "firmware"]:
                address = FLASH_ADDRESSES[file_type]
                filename = FLASH_FILES[file_type]
                filepath = os.path.join(slot_dir, filename)
                cmd.extend([address, filepath])
            
            print(f"Executing: {' '.join(cmd)}")
            
            # Execute the flash command
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                cwd=self.script_dir
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
        """Monitor button presses with page-aware actions and long-press on KEY3 to switch page."""
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
                
                # KEY1 actions
                if not GPIO.input(KEY1_PIN) and not self.flashing:
                    if self.current_page == 1:
                        print("KEY1 pressed, starting ESP32 flash.")
                        flash_thread = threading.Thread(target=self.flash_esp32, args=(1,))
                        flash_thread.daemon = True
                        flash_thread.start()
                    else:
                        print("KEY1 pressed (Page 2), starting AP mode.")
                        ap_thread = threading.Thread(target=self.start_ap_mode)
                        ap_thread.daemon = True
                        ap_thread.start()
                    time.sleep(0.3)  # Debounce
                
                # KEY2 actions
                if not GPIO.input(KEY2_PIN) and not self.flashing:
                    if self.current_page == 1:
                        print("KEY2 pressed, downloading firmware URL 1.")
                        download_thread = threading.Thread(target=self.download_firmware, args=(1,))
                        download_thread.daemon = True
                        download_thread.start()
                    else:
                        print("KEY2 pressed (Page 2), showing WiFi status.")
                        self.show_wifi_status()
                    time.sleep(0.3)  # Debounce
                
                # KEY3 actions (short vs long press)
                if not GPIO.input(KEY3_PIN) and not self.flashing:
                    # Pressed
                    if self.key3_pressed_at is None:
                        self.key3_pressed_at = current_time
                    else:
                        if self.current_page == 1 and (current_time - self.key3_pressed_at > 1.2):
                            # Long press on Page 1 -> switch to Page 2
                            self.current_page = 2
                            print("KEY3 long-press: Switched to Page 2")
                            self.display_message(self.get_status_display())
                            self.key3_pressed_at = float('inf')  # Prevent retrigger until release
                else:
                    # Released
                    if self.key3_pressed_at is not None and self.key3_pressed_at != float('inf'):
                        press_duration = current_time - self.key3_pressed_at
                        if press_duration <= 1.2:
                            if self.current_page == 1 and not self.flashing:
                                print("KEY3 short-press, downloading firmware URL 2.")
                                download_thread = threading.Thread(target=self.download_firmware, args=(2,))
                                download_thread.daemon = True
                                download_thread.start()
                            elif self.current_page == 2 and not self.flashing:
                                print("KEY3 pressed (Page 2), flash from fw2.")
                                t = threading.Thread(target=self.flash_esp32, args=(2,))
                                t.daemon = True
                                t.start()
                        # Reset tracking
                    if self.key3_pressed_at is not None:
                        self.key3_pressed_at = None
                
                time.sleep(0.05)  # Polling delay
                
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
