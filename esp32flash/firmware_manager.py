#!/usr/bin/env python3
"""
Offline Firmware Manager for ESP32 Flasher.
Maintains a local library of downloaded firmwares on the Pi's storage.
Allows 100% offline browsing and flashing, with on-demand sync from blog.damienslab.com.
"""

import os
import sys
import json
import urllib.request
import urllib.error
import zipfile
import shutil
import glob
import re

DEFAULT_SERVER_URL = "https://blog.damienslab.com"
FLASH_ADDRESSES = {
    "bootloader": "0x1000",
    "partitions": "0x8000",
    "firmware": "0x10000"
}


class FirmwareManager:
    """Manages local offline firmware library and synchronization."""

    def __init__(self, script_dir):
        self.script_dir = script_dir
        self.firmwares_dir = os.path.join(script_dir, "firmwares")
        self.library_file = os.path.join(self.firmwares_dir, "library.json")
        os.makedirs(self.firmwares_dir, exist_ok=True)
        
        self.firmwares = []
        self.selected_index = 0
        self.server_url = DEFAULT_SERVER_URL
        
        # Load or initialize library
        self.load_library()

    def sanitize_name(self, name):
        """Sanitize directory name."""
        return re.sub(r'[^a-zA-Z0-9_\-\.]', '_', str(name)).strip('_')

    def load_library(self):
        """Load firmware catalog from local storage or scan disk."""
        self.firmwares = []
        if os.path.exists(self.library_file):
            try:
                with open(self.library_file, "r") as f:
                    data = json.load(f)
                    self.firmwares = data.get("firmwares", [])
                    self.selected_index = data.get("selected_index", 0)
                    self.server_url = data.get("server_url", DEFAULT_SERVER_URL)
            except Exception as e:
                print(f"[FWManager] Error reading library.json: {e}")

        # Scan filesystem for existing folders (including legacy fw1, fw2)
        existing_folders = {fw.get("folder"): fw for fw in self.firmwares}
        
        # Check firmwares directory subdirectories
        if os.path.exists(self.firmwares_dir):
            for entry in os.listdir(self.firmwares_dir):
                folder_path = os.path.join(self.firmwares_dir, entry)
                if os.path.isdir(folder_path) and entry not in existing_folders:
                    bins = self.inspect_folder_bins(folder_path)
                    if bins["firmware"]:
                        fw_info = {
                            "name": entry,
                            "version": "local",
                            "folder": entry,
                            "path": folder_path,
                            "url": ""
                        }
                        self.firmwares.append(fw_info)
                        existing_folders[entry] = fw_info

        # Also support legacy fw1 and fw2 if present
        for slot_num, slot_name in [(1, "fw1"), (2, "fw2")]:
            legacy_path = os.path.join(self.script_dir, slot_name)
            if os.path.exists(legacy_path) and slot_name not in existing_folders:
                bins = self.inspect_folder_bins(legacy_path)
                if bins["firmware"]:
                    fw_info = {
                        "name": f"Slot {slot_num} ({slot_name})",
                        "version": "legacy",
                        "folder": slot_name,
                        "path": legacy_path,
                        "url": ""
                    }
                    self.firmwares.append(fw_info)
                    existing_folders[slot_name] = fw_info

        # Verify all entries have valid paths and check files
        valid_fws = []
        for fw in self.firmwares:
            folder = fw.get("folder", "")
            path = fw.get("path")
            if not path or not os.path.exists(path):
                cand_fw = os.path.join(self.firmwares_dir, folder)
                cand_script = os.path.join(self.script_dir, folder)
                if os.path.exists(cand_fw):
                    path = cand_fw
                elif os.path.exists(cand_script):
                    path = cand_script

            if path and os.path.exists(path):
                fw["path"] = path
                bins = self.inspect_folder_bins(path)
                fw["ready"] = bool(bins["firmware"] and bins["bootloader"] and bins["partitions"])
                valid_fws.append(fw)

        self.firmwares = valid_fws
        if self.selected_index >= len(self.firmwares):
            self.selected_index = max(0, len(self.firmwares) - 1)

        self.save_library()

    def save_library(self):
        """Persist library catalog to library.json."""
        try:
            data = {
                "server_url": self.server_url,
                "selected_index": self.selected_index,
                "firmwares": self.firmwares
            }
            with open(self.library_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[FWManager] Failed to save library.json: {e}")

    def inspect_folder_bins(self, folder_path):
        """Identify bootloader, partitions, and firmware bin files in a directory."""
        bins = {"bootloader": None, "partitions": None, "firmware": None}
        if not os.path.exists(folder_path):
            return bins

        all_bins = glob.glob(os.path.join(folder_path, "*.bin"))
        
        # 1. Bootloader
        for b in all_bins:
            b_lower = os.path.basename(b).lower()
            if "bootloader" in b_lower:
                bins["bootloader"] = b
                break

        # 2. Partitions
        for b in all_bins:
            b_lower = os.path.basename(b).lower()
            if "partition" in b_lower:
                bins["partitions"] = b
                break

        # 3. Main firmware
        for b in all_bins:
            if b != bins["bootloader"] and b != bins["partitions"]:
                bins["firmware"] = b
                break

        return bins

    def ensure_default_bins(self, target_folder):
        """Ensure standard bootloader and partitions exist in target folder."""
        bins = self.inspect_folder_bins(target_folder)
        defaults = {
            "bootloader": "sketch_apr20a.ino.bootloader.bin",
            "partitions": "sketch_apr20a.ino.partitions.bin"
        }
        for key, default_filename in defaults.items():
            if not bins[key]:
                # Look in root script_dir or fw1 for default
                for src_dir in [self.script_dir, os.path.join(self.script_dir, "fw1"), os.path.join(self.script_dir, "fw2")]:
                    src_file = os.path.join(src_dir, default_filename)
                    if os.path.exists(src_file):
                        dest_file = os.path.join(target_folder, default_filename)
                        shutil.copy2(src_file, dest_file)
                        print(f"[FWManager] Copied default {key} -> {dest_file}")
                        break

    def get_selected(self):
        """Return currently selected firmware dict, or None if library empty."""
        if not self.firmwares:
            return None
        if self.selected_index >= len(self.firmwares):
            self.selected_index = 0
        return self.firmwares[self.selected_index]

    def next_firmware(self):
        """Select next firmware."""
        if self.firmwares:
            self.selected_index = (self.selected_index + 1) % len(self.firmwares)
            self.save_library()
        return self.get_selected()

    def prev_firmware(self):
        """Select previous firmware."""
        if self.firmwares:
            self.selected_index = (self.selected_index - 1) % len(self.firmwares)
            self.save_library()
        return self.get_selected()

    def get_flash_targets(self, fw_item=None):
        """
        Get list of (address, filepath) tuples for esptool flashing.
        Returns None if prerequisites missing.
        """
        item = fw_item or self.get_selected()
        if not item or not item.get("path"):
            return None

        folder_path = item["path"]
        bins = self.inspect_folder_bins(folder_path)

        # Make sure default bootloader and partitions exist if missing
        if not bins["bootloader"] or not bins["partitions"]:
            self.ensure_default_bins(folder_path)
            bins = self.inspect_folder_bins(folder_path)

        if not bins["firmware"] or not bins["bootloader"] or not bins["partitions"]:
            print(f"[FWManager] Missing binary files in {folder_path}: {bins}")
            return None

        return [
            (FLASH_ADDRESSES["bootloader"], bins["bootloader"]),
            (FLASH_ADDRESSES["partitions"], bins["partitions"]),
            (FLASH_ADDRESSES["firmware"], bins["firmware"]),
        ]

    def fetch_catalog(self, server_url=None):
        """Query server for list of firmware versions."""
        url = (server_url or self.server_url).rstrip("/") + "/iot/ota/versions"
        req = urllib.request.Request(url, headers={"User-Agent": "ESP32-Flasher-Pi/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("firmware_versions", [])

    def sync_all(self, server_url=None, progress_callback=None):
        """
        Download and unpack all firmwares from the server for 100% offline use.
        progress_callback: fn(stage, current_num, total_num, percent)
        """
        base_url = (server_url or self.server_url).rstrip("/")
        if progress_callback:
            progress_callback("Connecting", 0, 0, 0)

        catalog = self.fetch_catalog(base_url)
        if not catalog:
            return {"success": False, "message": "No firmwares found on server", "count": 0}

        total = len(catalog)
        downloaded = 0

        for idx, fw in enumerate(catalog, start=1):
            name = fw.get("name") or f"fw_{idx}"
            version = fw.get("version") or "1.0"
            raw_url = fw.get("url") or ""

            if not raw_url:
                continue

            # Resolve full download URL
            if raw_url.startswith("http://") or raw_url.startswith("https://"):
                download_url = raw_url
            else:
                download_url = base_url + ("" if raw_url.startswith("/") else "/") + raw_url

            folder_name = self.sanitize_name(f"{name}_v{version}")
            target_dir = os.path.join(self.firmwares_dir, folder_name)
            os.makedirs(target_dir, exist_ok=True)

            bins = self.inspect_folder_bins(target_dir)
            if bins["firmware"] and bins["bootloader"] and bins["partitions"]:
                # Already complete offline
                print(f"[FWManager] Firmware {folder_name} already cached offline.")
                # Update catalog list if not present
                self._update_firmware_record(name, version, folder_name, target_dir, download_url)
                downloaded += 1
                continue

            if progress_callback:
                progress_callback(f"DL {name[:10]}", idx, total, 10)

            # Download archive or binary
            filename = os.path.basename(download_url.split("?")[0]) or "firmware.bin"
            temp_file = os.path.join(target_dir, filename)

            try:
                req = urllib.request.Request(download_url, headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"
                })
                with urllib.request.urlopen(req, timeout=30) as resp, open(temp_file, "wb") as out_f:
                    shutil.copyfileobj(resp, out_f)
            except Exception as e:
                print(f"[FWManager] Download failed for {download_url}: {e}")
                continue

            # Process downloaded file
            if filename.endswith(".zip"):
                if progress_callback:
                    progress_callback(f"Extract {name[:8]}", idx, total, 60)
                try:
                    with zipfile.ZipFile(temp_file, "r") as zf:
                        zf.extractall(target_dir)
                    os.remove(temp_file)
                except Exception as e:
                    print(f"[FWManager] Unzip failed: {e}")
            else:
                # Direct .bin file
                target_bin = os.path.join(target_dir, "sketch_apr20a.ino.bin")
                if temp_file != target_bin:
                    shutil.move(temp_file, target_bin)

            # Ensure bootloader and partitions exist in folder
            self.ensure_default_bins(target_dir)

            # Check ready status
            bins = self.inspect_folder_bins(target_dir)
            if bins["firmware"] and bins["bootloader"] and bins["partitions"]:
                self._update_firmware_record(name, version, folder_name, target_dir, download_url)
                downloaded += 1

            if progress_callback:
                progress_callback(f"Done {name[:8]}", idx, total, 100)

        self.save_library()
        return {"success": True, "count": downloaded, "total": total}

    def _update_firmware_record(self, name, version, folder_name, target_dir, url):
        """Add or update firmware record in local list."""
        for existing in self.firmwares:
            if existing.get("folder") == folder_name or (existing.get("name") == name and existing.get("version") == version):
                existing["path"] = target_dir
                existing["url"] = url
                existing["ready"] = True
                return

        self.firmwares.append({
            "name": name,
            "version": version,
            "folder": folder_name,
            "path": target_dir,
            "url": url,
            "ready": True
        })


if __name__ == "__main__":
    mgr = FirmwareManager(os.path.dirname(os.path.abspath(__file__)))
    print(f"Loaded {len(mgr.firmwares)} local firmwares.")
    for fw in mgr.firmwares:
        print(f" - {fw['name']} ({fw['version']}) in {fw['path']} [ready={fw.get('ready')}]")
    
    print("\\nSyncing from blog.damienslab.com...")
    res = mgr.sync_all()
    print("Sync result:", res)
