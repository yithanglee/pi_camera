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
from captive_portal import CaptivePortal
from firmware_manager import FirmwareManager

# Pin definitions (same as camera app)
KEY1_PIN = 21  # Button 1
KEY2_PIN = 20  # Button 2
KEY3_PIN = 16  # Button 3
# Joystick/Navigation
JOY_UP_PIN = 6     # Joystick Up
JOY_DOWN_PIN = 19  # Joystick Down
JOY_LEFT_PIN = 5   # Joystick Left
JOY_RIGHT_PIN = 26 # Joystick Right
JOY_PRESS_PIN = 13 # Joystick Press

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
        self.current_page = 1  # 1 = main (flasher/offline library), 2 = network & sync
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.fw_mgr = FirmwareManager(self.script_dir)
        self.busy = False
        self.lcd_lock = threading.Lock()
        self.captive_portal = None
        self.setup_lcd()
        self.setup_gpio()
        
    def setup_gpio(self):
        """Sets up GPIO pins for buttons and ESP32 control."""
        GPIO.setmode(GPIO.BCM)
        # Button pins
        GPIO.setup(KEY1_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(KEY2_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(KEY3_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        # Joystick navigation pins
        GPIO.setup(JOY_UP_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(JOY_DOWN_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(JOY_LEFT_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(JOY_RIGHT_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        
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
            
        with self.lcd_lock:
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
            
        with self.lcd_lock:
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
    
    def detect_esp32_port(self, silent=True):
        """Detect available ESP32 connection port and type."""
        import glob
        # 1. First, search for all active USB serial devices (/dev/ttyUSB*, /dev/ttyACM*)
        usb_ports = sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))
        for port in usb_ports:
            if os.path.exists(port):
                if not silent and getattr(self, "_last_port", None) != port:
                    print(f"Found ESP32 port: {port} (USB)")
                self._last_port = port
                return port, "USB"

        # 2. Check Raspberry Pi onboard UART pins (/dev/serial0, /dev/ttyAMA0)
        # Note: /dev/serial0 is the Pi's internal Broadcom GPIO UART (pins 14/15)
        # It always exists on Pi OS even when NO ESP32 is wired to the GPIO header!
        uart_candidates = ["/dev/serial0", "/dev/ttyAMA0", "/dev/ttyS0"]
        for port in uart_candidates:
            if os.path.exists(port):
                if not silent and getattr(self, "_last_port", None) != port:
                    print(f"No USB device found. Detected Pi UART: {port}")
                self._last_port = port
                return port, "UART"

        self._last_port = None
        return None, None
        
    def check_files(self):
        """Refresh offline firmware catalog."""
        self.fw_mgr.load_library()
        return len(self.fw_mgr.firmwares) > 0

    def sync_firmwares(self):
        """Sync all firmwares from blog.damienslab.com for 100% offline storage."""
        if self.busy or self.flashing:
            return
        self.busy = True
        try:
            self.display_message(["SYNC FIRMWARES", "Connecting...", "blog.damienslab"], color="WHITE", bg_color="ORANGE")

            def on_progress(stage, cur, total, pct):
                self.display_progress(f"{stage} [{cur}/{total}]", pct)

            result = self.fw_mgr.sync_all(progress_callback=on_progress)
            if result.get("success"):
                count = result.get("count", 0)
                self.display_message([
                    "SYNC SUCCESS!",
                    f"{count} Firmwares",
                    "Cached offline",
                    "Ready to flash"
                ], color="WHITE", bg_color="GREEN")
                time.sleep(3)
            else:
                msg = result.get("message", "Sync failed")
                self.display_message(["SYNC FAILED", msg[:16], "Check network"], color="WHITE", bg_color="RED")
                time.sleep(3)
        except Exception as e:
            self.display_message(["SYNC ERROR", str(e)[:16]], color="WHITE", bg_color="RED")
            print(f"Sync error: {e}")
            time.sleep(3)
        finally:
            self.busy = False
            self.display_message(self.get_status_display())

    def get_status_display(self):
        """Get current status for display (page-aware)."""
        status_lines = ["ESP32 Flasher"]
        
        if self.current_page == 1:
            fw = self.fw_mgr.get_selected()
            total_fws = len(self.fw_mgr.firmwares)
            cur_idx = (self.fw_mgr.selected_index + 1) if total_fws > 0 else 0
            
            status_lines.append(f"FW [{cur_idx}/{total_fws}]")
            if fw:
                status_lines.append(f"{fw.get('name', 'N/A')[:16]}")
                status_lines.append(f"v{fw.get('version', '')[:8]} - {'RDY' if fw.get('ready') else 'NOT RDY'}")
            else:
                status_lines.append("No Offline FW")
                status_lines.append("Press K3 to Sync")
            
            # Show connection status
            port, conn_type = self.detect_esp32_port(silent=True)
            if conn_type == "USB":
                port_short = port.split('/')[-1]
                status_lines.append(f"USB: {port_short}")
            elif conn_type == "UART":
                status_lines.append("USB: Not plugged")
                status_lines.append(f"UART: {port.split('/')[-1]}")
            else:
                status_lines.append("ESP32: Not found")
            
            # Controls (Page 1)
            status_lines.extend([
                "----------------",
                "K1:Flash K2:Next",
                "K3:Sync  Joy:Up/Dn"
            ])
        else:
            # Page 2: Network & Utilities
            ap_active = self.is_ap_mode_active()
            if ap_active:
                ip = self.get_ap_ip()
                ap_status = f"AP: ON ({ip})"
                key1_action = "KEY1: Stop AP"
            else:
                ap_status = "AP: OFF"
                key1_action = "KEY1: Start AP"

            status_lines.extend([
                "Page 2: Network",
                ap_status,
                f"Offline FW: {len(self.fw_mgr.firmwares)}",
                "----------------",
                key1_action,
                "KEY2: WiFi status",
                "KEY3: Sync Firmwares",
                "LEFT/RIGHT: Page",
            ])
        
        return status_lines

    def on_portal_wifi_connected(self, ssid, new_ip):
        """Callback when user successfully connects Wi-Fi via captive portal."""
        print(f"Wi-Fi connected via captive portal: {ssid} ({new_ip})")
        self.display_message(["PORTAL SETUP", f"Connected: {ssid[:10]}", f"IP: {new_ip[:12]}"], color="WHITE", bg_color="GREEN")
        time.sleep(2)
        self.stop_ap_mode()

    def is_ap_mode_active(self):
        """Check if AP mode is currently active on wlan0."""
        try:
            res = subprocess.run(
                ["nmcli", "-t", "-f", "NAME,TYPE", "con", "show", "--active"],
                capture_output=True, text=True, timeout=2
            )
            if res.returncode == 0:
                for line in res.stdout.strip().splitlines():
                    name = line.split(":")[0]
                    if name in ["PiZero2-AP", "Hotspot"]:
                        return True
        except Exception:
            pass

        return False

    def get_ap_ip(self):
        """Get IP address of wlan0."""
        try:
            res = subprocess.run(["ip", "-4", "-o", "addr", "show", "wlan0"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0 and res.stdout:
                match = re.search(r"inet\s+([0-9.]+)", res.stdout)
                if match:
                    return match.group(1)
        except Exception:
            pass
        return "10.42.0.1"

    def stop_ap_mode(self):
        """Stop Wi-Fi AP mode and reconnect to client Wi-Fi."""
        if self.busy:
            return
        self.busy = True
        try:
            self.display_message(["AP MODE", "Stopping AP...", "Restoring WiFi"], color="WHITE", bg_color="ORANGE")
            
            # Stop Captive Portal if running
            if self.captive_portal:
                try:
                    self.captive_portal.stop()
                except Exception as e:
                    print(f"Error stopping captive portal: {e}")
                self.captive_portal = None

            # Ensure hotspot does not autoconnect in the future
            for con in ["PiZero2-AP", "Hotspot"]:
                subprocess.run(["nmcli", "con", "mod", con, "connection.autoconnect", "no"], capture_output=True, timeout=5)
                subprocess.run(["nmcli", "con", "down", con], capture_output=True, timeout=5)

            # Explicitly return wlan0 to managed (station) mode
            subprocess.run(["ip", "link", "set", "wlan0", "down"], capture_output=True, timeout=5)
            subprocess.run(["iw", "dev", "wlan0", "set", "type", "managed"], capture_output=True, timeout=5)
            subprocess.run(["ip", "link", "set", "wlan0", "up"], capture_output=True, timeout=5)
            time.sleep(1)

            # Check for known saved station Wi-Fi networks (excluding AP profiles)
            known_conns = []
            res = subprocess.run(["nmcli", "-t", "-f", "NAME,TYPE", "con", "show"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                for line in res.stdout.strip().splitlines():
                    parts = line.split(":")
                    if len(parts) >= 2 and "wireless" in parts[1]:
                        if parts[0] not in ["PiZero2-AP", "Hotspot"]:
                            known_conns.append(parts[0])

            connected = False
            for wifi_name in known_conns:
                res_up = subprocess.run(["nmcli", "con", "up", wifi_name], capture_output=True, text=True, timeout=8)
                if res_up.returncode == 0:
                    connected = True
                    break

            if not connected:
                # When no other Wi-Fi is available to connect, keep wlan0 disconnected in station mode.
                # This ensures AP mode does NOT turn back on!
                subprocess.run(["nmcli", "dev", "disconnect", "wlan0"], capture_output=True, timeout=5)

            time.sleep(1)
            if connected:
                self.display_message(["AP MODE", "AP Stopped", "WiFi Connected"], color="WHITE", bg_color="GREEN")
            else:
                self.display_message(["AP MODE", "AP Stopped", "WiFi Idle (OFF)"], color="WHITE", bg_color="GREEN")
            time.sleep(2)
        except Exception as e:
            self.display_message(["AP STOP ERR", str(e)[:16]], color="WHITE", bg_color="RED")
            print(f"Stop AP error: {e}")
            time.sleep(2)
        finally:
            self.busy = False
            self.display_message(self.get_status_display())

    def start_ap_mode(self):
        """Toggle or start Wi-Fi AP mode on wlan0 using NetworkManager (nmcli)."""
        if self.busy:
            return
            
        # Toggle: if already active, stop it
        if self.is_ap_mode_active():
            self.stop_ap_mode()
            return

        self.busy = True
        try:
            self.display_message(["AP MODE", "Starting...", "SSID: PiZero2-AP"], color="WHITE", bg_color="ORANGE")
            
            # 1. Ensure NetworkManager is installed
            nm_which = subprocess.run(["which", "nmcli"], capture_output=True, text=True)
            if nm_which.returncode != 0 and not os.path.exists("/usr/bin/nmcli"):
                self.display_message(["AP FAILED", "nmcli not found", "Install nmcli"], color="WHITE", bg_color="RED")
                time.sleep(3)
                return

            # 2. Check and start NetworkManager service if needed
            nm_check = subprocess.run(["systemctl", "is-active", "--quiet", "NetworkManager"], capture_output=True)
            if nm_check.returncode != 0:
                print("NetworkManager not active, starting service...")
                self.display_message(["AP MODE", "Starting service", "NetworkManager..."], color="WHITE", bg_color="ORANGE")
                start_cmd = ["systemctl", "start", "NetworkManager"]
                if os.geteuid() != 0:
                    start_cmd = ["sudo"] + start_cmd
                subprocess.run(start_cmd, capture_output=True, timeout=10)
                
                # Wait for service to become active
                started = False
                for _ in range(6):
                    time.sleep(0.5)
                    if subprocess.run(["systemctl", "is-active", "--quiet", "NetworkManager"]).returncode == 0:
                        started = True
                        break
                if not started:
                    print("Failed to start NetworkManager service.")
                    self.display_message(["AP FAILED", "NM service", "not running"], color="WHITE", bg_color="RED")
                    time.sleep(3)
                    return

            # 3. Ensure wlan0 is managed
            subprocess.run(["nmcli", "dev", "set", "wlan0", "managed", "yes"], capture_output=True, timeout=5)

            # 4. Check if PiZero2-AP profile already exists
            con_check = subprocess.run(["nmcli", "-t", "-f", "NAME", "con", "show"], capture_output=True, text=True, timeout=5)
            existing_conns = con_check.stdout.splitlines() if con_check.returncode == 0 else []

            success = False
            if "PiZero2-AP" in existing_conns:
                print("Profile PiZero2-AP exists, activating...")
                res = subprocess.run(["nmcli", "con", "up", "PiZero2-AP"], capture_output=True, text=True, timeout=12)
                if res.returncode == 0:
                    success = True
                else:
                    print(f"nmcli con up failed: {res.stderr}. Recreating profile...")
                    subprocess.run(["nmcli", "con", "delete", "PiZero2-AP"], capture_output=True, timeout=5)

            if not success:
                cmd = [
                    "nmcli", "dev", "wifi", "hotspot",
                    "ifname", "wlan0",
                    "con-name", "PiZero2-AP",
                    "ssid", "PiZero2-AP",
                    "password", "pizerow2AP"
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                if res.returncode == 0:
                    success = True
                else:
                    print(f"nmcli hotspot error: {res.stderr}")
                    # Generic fallback without con-name
                    cmd_gen = [
                        "nmcli", "dev", "wifi", "hotspot",
                        "ifname", "wlan0",
                        "ssid", "PiZero2-AP",
                        "password", "pizerow2AP"
                    ]
                    res_gen = subprocess.run(cmd_gen, capture_output=True, text=True, timeout=15)
                    if res_gen.returncode == 0:
                        success = True
                    else:
                        print(f"Generic hotspot error: {res_gen.stderr}")

            # Ensure hotspot does not autoconnect on its own
            subprocess.run(["nmcli", "con", "mod", "PiZero2-AP", "connection.autoconnect", "no"], capture_output=True, timeout=5)

            # Start Captive Portal web server on port 80 & DNS
            try:
                if not self.captive_portal:
                    self.captive_portal = CaptivePortal(on_connected=self.on_portal_wifi_connected, fw_mgr=self.fw_mgr)
                self.captive_portal.start()
            except Exception as e:
                print(f"Captive portal launch error: {e}")

            # 5. Verify AP state and display IP
            if success or self.is_ap_mode_active():
                time.sleep(1)
                ip = self.get_ap_ip()
                self.display_message([
                    "AP MODE ACTIVE",
                    "SSID: PiZero2-AP",
                    "PWD: pizerow2AP",
                    f"IP: {ip}",
                    "Portal: Port 80"
                ], color="WHITE", bg_color="GREEN")
                time.sleep(3)
                return
            
            # Fallback: check create_ap
            cmd_check = subprocess.run(["which", "create_ap"], capture_output=True, text=True)
            if cmd_check.returncode == 0:
                cmd2 = ["create_ap", "wlan0", "eth0", "PiZero2-AP", "pizerow2AP", "-n"]
                if os.geteuid() != 0:
                    cmd2 = ["sudo"] + cmd2
                result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=15)
                if result2.returncode == 0:
                    self.display_message(["AP MODE", "Started", "SSID: PiZero2-AP"], color="WHITE", bg_color="GREEN")
                    time.sleep(3)
                    return

            self.display_message(["AP FAILED", "Hotspot failed", "Check nmcli logs"], color="WHITE", bg_color="RED")
            time.sleep(3)
        except Exception as e:
            self.display_message(["AP ERROR", str(e)[:16]], color="WHITE", bg_color="RED")
            print(f"AP mode error: {e}")
            time.sleep(3)
        finally:
            self.busy = False
            self.display_message(self.get_status_display())

    def show_wifi_status(self):
        """Display basic Wi-Fi status details."""
        if self.busy:
            return
        self.busy = True
        try:
            ssid = ""
            ip4 = ""
            link = ""

            ap_active = self.is_ap_mode_active()
            if ap_active:
                ssid = "PiZero2-AP (AP)"
                ip4 = self.get_ap_ip()
                link = "Mode: Hotspot"
            else:
                # SSID
                try:
                    out = subprocess.run(["iwgetid", "-r"], capture_output=True, text=True, timeout=2)
                    if out.returncode == 0 and out.stdout.strip():
                        ssid = out.stdout.strip()
                    else:
                        nm_out = subprocess.run(
                            ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"],
                            capture_output=True, text=True, timeout=2
                        )
                        if nm_out.returncode == 0:
                            for line in nm_out.stdout.splitlines():
                                if line.startswith("yes:"):
                                    ssid = line.split(":", 1)[1]
                                    break
                except Exception:
                    pass
                # IP
                try:
                    out = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=2)
                    if out.returncode == 0:
                        ip4 = out.stdout.strip().split(" ")[0]
                except Exception:
                    pass
                # Link state
                try:
                    out = subprocess.run(["iw", "dev", "wlan0", "link"], capture_output=True, text=True, timeout=2)
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
            time.sleep(3)
        except Exception as e:
            self.display_message(["WiFi Error", str(e)[:16]], color="WHITE", bg_color="RED")
            print(f"WiFi status error: {e}")
            time.sleep(2)
        finally:
            self.busy = False
            self.display_message(self.get_status_display())
    
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

    def flash_esp32(self, fw_item=None):
        """Flash the ESP32 with the binary files from selected firmware."""
        if self.flashing or self.busy:
            return
            
        self.flashing = True
        
        try:
            target = fw_item or self.fw_mgr.get_selected()
            if not target:
                self.display_message(["Flash FAILED", "No FW selected", "Sync firmwares first"], color="WHITE", bg_color="RED")
                time.sleep(3)
                return

            targets = self.fw_mgr.get_flash_targets(target)
            if not targets:
                self.display_message(["Flash FAILED", "Missing files", f"in {target.get('name', '')[:12]}"], color="WHITE", bg_color="RED")
                time.sleep(3)
                return
                
            # Detect ESP32 port
            port, conn_type = self.detect_esp32_port(silent=False)
            if not port:
                self.display_message(["Flash FAILED", "No ESP32 found", "Check connections"], color="WHITE", bg_color="RED")
                time.sleep(3)
                return
            
            # Show detected connection
            port_name = port.split('/')[-1]
            print(f"Using {conn_type} connection: {port}")
            if conn_type == "UART":
                print("\n" + "="*56)
                print("NOTE: No USB port (/dev/ttyUSB* or /dev/ttyACM*) was detected.")
                print("If ESP32 is plugged in via USB:")
                print(" 1. Check Pi Zero 2 W port: use the inner 'USB' port (not 'PWR IN').")
                print(" 2. Ensure your micro-USB cable is a DATA cable, not charge-only.")
                print("="*56 + "\n")
            
            # Put ESP32 into download mode
            self.esp32_enter_download_mode()
            
            # Initialize progress
            self.current_stage = "Starting"
            self.current_percent = 0
            self.display_progress(f"Flash {target.get('name', '')[:10]}", 0)
            
            # Build esptool command
            cmd = [
                "esptool.py",
                "--chip", ESP32_CHIP,
                "--port", port,  # Use detected port
                "--baud", str(ESP32_BAUD),
                "write_flash", "-z"
            ]
            
            # Add each file with its address
            for addr, filepath in targets:
                cmd.extend([addr, filepath])
            
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
        """Monitor button presses with page-aware actions and LEFT/RIGHT navigation."""
        last_display_update = 0
        
        while True:
            try:
                current_time = time.time()
                
                # Update display every 2 seconds when not flashing or busy
                if not self.flashing and not self.busy and (current_time - last_display_update > 2):
                    self.check_files()  # Refresh file status
                    status_lines = self.get_status_display()
                    self.display_message(status_lines)
                    last_display_update = current_time
                
                # KEY1 actions
                if not GPIO.input(KEY1_PIN) and not self.flashing and not self.busy:
                    if self.current_page == 1:
                        print("KEY1 pressed, starting ESP32 flash with selected firmware.")
                        flash_thread = threading.Thread(target=self.flash_esp32)
                        flash_thread.daemon = True
                        flash_thread.start()
                    else:
                        print("KEY1 pressed (Page 2), toggling AP mode.")
                        ap_thread = threading.Thread(target=self.start_ap_mode)
                        ap_thread.daemon = True
                        ap_thread.start()
                    time.sleep(0.3)  # Debounce
                
                # KEY2 actions
                if not GPIO.input(KEY2_PIN) and not self.flashing and not self.busy:
                    if self.current_page == 1:
                        print("KEY2 pressed, selecting next firmware.")
                        self.fw_mgr.next_firmware()
                        self.display_message(self.get_status_display())
                        last_display_update = time.time()
                    else:
                        print("KEY2 pressed (Page 2), showing WiFi status.")
                        wifi_thread = threading.Thread(target=self.show_wifi_status)
                        wifi_thread.daemon = True
                        wifi_thread.start()
                    time.sleep(0.3)  # Debounce
                
                # KEY3 actions: Sync firmwares
                if not GPIO.input(KEY3_PIN) and not self.flashing and not self.busy:
                    print("KEY3 pressed, syncing all firmwares from blog.damienslab.com.")
                    sync_thread = threading.Thread(target=self.sync_firmwares)
                    sync_thread.daemon = True
                    sync_thread.start()
                    time.sleep(0.3)  # Debounce

                # JOYSTICK UP / DOWN: Cycle firmware selection
                if not GPIO.input(JOY_UP_PIN) and not self.flashing and not self.busy:
                    self.fw_mgr.prev_firmware()
                    print(f"Joy UP: Selected {self.fw_mgr.get_selected()}")
                    self.display_message(self.get_status_display())
                    last_display_update = time.time()
                    time.sleep(0.25)
                
                if not GPIO.input(JOY_DOWN_PIN) and not self.flashing and not self.busy:
                    self.fw_mgr.next_firmware()
                    print(f"Joy DOWN: Selected {self.fw_mgr.get_selected()}")
                    self.display_message(self.get_status_display())
                    last_display_update = time.time()
                    time.sleep(0.25)

                # LEFT/RIGHT navigation
                if not GPIO.input(JOY_LEFT_PIN) and not self.flashing and not self.busy:
                    if self.current_page != 1:
                        self.current_page = 1
                        print("Navigation: LEFT -> Page 1")
                        self.display_message(self.get_status_display())
                        last_display_update = time.time()
                        time.sleep(0.3)
                if not GPIO.input(JOY_RIGHT_PIN) and not self.flashing and not self.busy:
                    if self.current_page != 2:
                        self.current_page = 2
                        print("Navigation: RIGHT -> Page 2")
                        self.display_message(self.get_status_display())
                        last_display_update = time.time()
                        time.sleep(0.3)
                
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
