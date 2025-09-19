# ESP32 Flasher with LCD UI

This application uses the same LCD interface as the camera app to flash ESP32 microcontrollers via direct UART connection.

## Required Files

Place these binary files in the same directory as `main.py`:

- `sketch_apr20a.ino.bootloader.bin` (bootloader)
- `sketch_apr20a.ino.partitions.bin` (partition table)  
- `sketch_apr20a.ino.bin` (main firmware)

## Hardware Connections

The flasher supports **both USB and UART connections**:

### **Option 1: USB Connection**
- **ESP32 USB → Pi USB port** (simple plug-in)
- **Optional**: Custom cable with GPIO control wires:
  - Pi GPIO4 → ESP32 EN (auto reset)
  - Pi GPIO17 → ESP32 GPIO0 (auto boot mode)

### **Option 2: Direct UART Connection**
- **Pi GPIO14 (TXD) → ESP32 RX**
- **Pi GPIO15 (RXD) → ESP32 TX**  
- **Pi GND → ESP32 GND**
- **Pi GPIO4 → ESP32 EN** (reset control)
- **Pi GPIO17 → ESP32 GPIO0** (boot mode control)

## Requirements

- esptool.py (install with `pip install esptool`)
- ESP32 connected via **USB** or **UART** (auto-detected)
- LCD display (ST7735S compatible)
- Raspberry Pi with GPIO buttons
- For UART: UART enabled in Pi config (`sudo raspi-config` → Interface Options → Serial)

## Controls

- **KEY1 (GPIO 21)**: Flash ESP32
- **KEY2 (GPIO 20)**: Exit program
- **KEY3 (GPIO 16)**: Download firmware from server

## Usage

1. **Enable UART**: Run `sudo raspi-config` → Interface Options → Serial → Enable
2. **Wire connections**: Connect ESP32 to Pi using the GPIO pins listed above
3. **Get firmware**: Press KEY3 to auto-download firmware OR place your ESP32 binary files in this directory
4. **Run**: `python3 main.py`
5. **Flash**: Press KEY1 to start flashing (automatic boot mode control)
6. **Monitor**: Progress shown on LCD, ESP32 auto-reset after completion

### Auto-Download Feature

- **KEY3** automatically downloads the latest firmware from the server
- Downloads: `https://jreporting.jimatlabs.com/uploads/vids/ino/sketch_apr20aw9.ino.zip`
- Extracts files and cleans up automatically
- Shows progress on LCD (orange background during download)

## Flash Command

The application auto-detects the connection and executes esptool:

```bash
# USB Connection Example:
esptool.py --chip esp32 --port /dev/ttyUSB0 --baud 460800 write_flash -z \
  0x1000  sketch_apr20a.ino.bootloader.bin \
  0x8000  sketch_apr20a.ino.partitions.bin \
  0x10000 sketch_apr20a.ino.bin

# UART Connection Example:  
esptool.py --chip esp32 --port /dev/serial0 --baud 460800 write_flash -z \
  0x1000  sketch_apr20a.ino.bootloader.bin \
  0x8000  sketch_apr20a.ino.partitions.bin \
  0x10000 sketch_apr20a.ino.bin
```

## Automatic Boot Mode Control

### **UART Connection (Fully Automatic)**
- **Before flashing**: ESP32 GPIO0 pulled LOW, then reset (enters download mode)
- **After flashing**: ESP32 GPIO0 released HIGH, then reset (normal boot)
- **No manual intervention** required - fully automated!

### **USB Connection (Smart Detection)**
- **Custom cable with GPIO wires**: Automatic control (same as UART)
- **Standard USB cable**: Manual mode - hold BOOT button, press EN
- **Auto-detection**: Tries GPIO control first, falls back to manual instructions

## Status Display

The LCD shows:
- File availability status
- **Connection type**: USB: ttyUSB0 or UART: serial0
- Flash progress with automatic boot mode control
- Success/error messages with automatic ESP32 reset
