#!/usr/bin/env python3
"""
Captive Portal & Wi-Fi Provisioning Server for Raspberry Pi Zero 2 W
Runs an embedded HTTP server (Port 80) and DNS catch-all (Port 53)
when AP mode is active.
"""

import http.server
import socketserver
import socket
import threading
import subprocess
import json
import urllib.parse
import re
import time
import os

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Wi-Fi Setup - Pi Zero 2 W</title>
  <style>
    :root {
      --bg: #0f172a;
      --card: #1e293b;
      --accent: #38bdf8;
      --accent-hover: #0ea5e9;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --success: #22c55e;
      --danger: #ef4444;
      --border: #334155;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 100vh;
      padding: 16px;
    }
    .card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 24px;
      width: 100%;
      max-width: 420px;
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
    }
    .header {
      text-align: center;
      margin-bottom: 24px;
    }
    .header h1 {
      font-size: 1.4rem;
      font-weight: 700;
      color: var(--text);
      margin-bottom: 6px;
    }
    .header p {
      font-size: 0.85rem;
      color: var(--text-muted);
    }
    .badge {
      display: inline-block;
      padding: 4px 10px;
      background: rgba(56, 189, 248, 0.15);
      color: var(--accent);
      border-radius: 9999px;
      font-size: 0.75rem;
      font-weight: 600;
      margin-bottom: 12px;
    }
    .section-title {
      font-size: 0.85rem;
      font-weight: 600;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 10px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .btn-refresh {
      background: transparent;
      border: none;
      color: var(--accent);
      font-size: 0.8rem;
      cursor: pointer;
      font-weight: 600;
    }
    .btn-refresh:hover { text-decoration: underline; }
    .wifi-list {
      max-height: 200px;
      overflow-y: auto;
      border: 1px solid var(--border);
      border-radius: 10px;
      margin-bottom: 16px;
      background: rgba(15, 23, 42, 0.4);
    }
    .wifi-item {
      padding: 12px 14px;
      border-bottom: 1px solid var(--border);
      cursor: pointer;
      display: flex;
      justify-content: space-between;
      align-items: center;
      transition: background 0.15s ease;
    }
    .wifi-item:last-child { border-bottom: none; }
    .wifi-item:hover, .wifi-item.selected {
      background: rgba(56, 189, 248, 0.12);
    }
    .wifi-name {
      font-weight: 500;
      font-size: 0.95rem;
    }
    .wifi-meta {
      font-size: 0.75rem;
      color: var(--text-muted);
    }
    .form-group {
      margin-bottom: 16px;
    }
    label {
      display: block;
      font-size: 0.85rem;
      font-weight: 500;
      margin-bottom: 6px;
      color: var(--text);
    }
    input[type="text"], input[type="password"] {
      width: 100%;
      padding: 12px 14px;
      background: #0f172a;
      border: 1px solid var(--border);
      border-radius: 8px;
      color: var(--text);
      font-size: 0.95rem;
      outline: none;
      transition: border 0.15s ease;
    }
    input[type="text"]:focus, input[type="password"]:focus {
      border-color: var(--accent);
    }
    .password-wrap {
      position: relative;
    }
    .btn-toggle-pwd {
      position: absolute;
      right: 12px;
      top: 50%;
      transform: translateY(-50%);
      background: transparent;
      border: none;
      color: var(--text-muted);
      cursor: pointer;
      font-size: 0.8rem;
    }
    .btn-submit {
      width: 100%;
      padding: 12px;
      background: var(--accent);
      color: #0f172a;
      font-weight: 600;
      font-size: 0.95rem;
      border: none;
      border-radius: 8px;
      cursor: pointer;
      transition: background 0.15s ease;
      margin-top: 8px;
    }
    .btn-submit:hover {
      background: var(--accent-hover);
    }
    .btn-submit:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    .alert {
      padding: 12px;
      border-radius: 8px;
      font-size: 0.85rem;
      margin-top: 16px;
      display: none;
    }
    .alert-danger {
      background: rgba(239, 68, 68, 0.15);
      border: 1px solid var(--danger);
      color: #fca5a5;
    }
    .alert-success {
      background: rgba(34, 197, 94, 0.15);
      border: 1px solid var(--success);
      color: #86efac;
    }
    .spinner {
      display: inline-block;
      width: 14px;
      height: 14px;
      border: 2px solid rgba(15, 23, 42, 0.3);
      border-radius: 50%;
      border-top-color: #0f172a;
      animation: spin 0.8s linear infinite;
      margin-right: 6px;
      vertical-align: middle;
    }
    @keyframes spin {
      to { transform: rotate(360deg); }
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="header">
      <div class="badge">Hotspot Active</div>
      <h1>Configure Wi-Fi</h1>
      <p>Connect your Raspberry Pi to a local network</p>
    </div>

    <div class="section-title">
      <span>Available Networks</span>
      <button class="btn-refresh" id="btnRefresh" onclick="scanWifi()">↻ Refresh</button>
    </div>

    <div class="wifi-list" id="wifiList">
      <div class="wifi-item" style="color:var(--text-muted); justify-content:center;">Scanning networks...</div>
    </div>

    <form id="wifiForm" onsubmit="connectWifi(event)">
      <div class="form-group">
        <label for="ssid">Network Name (SSID)</label>
        <input type="text" id="ssid" placeholder="Select above or enter name" required>
      </div>

      <div class="form-group">
        <label for="password">Password</label>
        <div class="password-wrap">
          <input type="password" id="password" placeholder="Enter password (if any)">
          <button type="button" class="btn-toggle-pwd" onclick="togglePassword()">Show</button>
        </div>
      </div>

      <button type="submit" class="btn-submit" id="btnSubmit">Connect & Save</button>
    </form>

    <div class="alert" id="statusAlert"></div>
  </div>

  <script>
    function togglePassword() {
      const pwd = document.getElementById('password');
      const btn = document.querySelector('.btn-toggle-pwd');
      if (pwd.type === 'password') {
        pwd.type = 'text';
        btn.textContent = 'Hide';
      } else {
        pwd.type = 'password';
        btn.textContent = 'Show';
      }
    }

    function scanWifi() {
      const list = document.getElementById('wifiList');
      const btn = document.getElementById('btnRefresh');
      btn.textContent = 'Scanning...';
      btn.disabled = true;

      fetch('/api/scan')
        .then(r => r.json())
        .then(networks => {
          btn.textContent = '↻ Refresh';
          btn.disabled = false;
          list.innerHTML = '';
          if (!networks || networks.length === 0) {
            list.innerHTML = '<div class="wifi-item" style="color:var(--text-muted); justify-content:center;">No networks found</div>';
            return;
          }
          networks.forEach(net => {
            const div = document.createElement('div');
            div.className = 'wifi-item';
            div.innerHTML = `
              <span class="wifi-name">${escapeHtml(net.ssid)}</span>
              <span class="wifi-meta">${net.signal}% ${net.security || 'Open'}</span>
            `;
            div.onclick = () => {
              document.querySelectorAll('.wifi-item').forEach(el => el.classList.remove('selected'));
              div.classList.add('selected');
              document.getElementById('ssid').value = net.ssid;
              document.getElementById('password').focus();
            };
            list.appendChild(div);
          });
        })
        .catch(err => {
          btn.textContent = '↻ Refresh';
          btn.disabled = false;
          list.innerHTML = '<div class="wifi-item" style="color:var(--text-muted); justify-content:center;">Scan failed</div>';
        });
    }

    function connectWifi(e) {
      e.preventDefault();
      const ssid = document.getElementById('ssid').value.trim();
      const password = document.getElementById('password').value;
      const btn = document.getElementById('btnSubmit');
      const alertBox = document.getElementById('statusAlert');

      if (!ssid) return;

      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span> Connecting...';
      alertBox.style.display = 'none';

      fetch('/api/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ssid, password })
      })
      .then(r => r.json())
      .then(res => {
        btn.disabled = false;
        btn.textContent = 'Connect & Save';
        alertBox.style.display = 'block';

        if (res.success) {
          alertBox.className = 'alert alert-success';
          alertBox.innerHTML = `<strong>Connected!</strong> Connected to <strong>${escapeHtml(ssid)}</strong>.<br>IP: ${res.ip || 'Obtained'}. AP mode is closing.`;
        } else {
          alertBox.className = 'alert alert-danger';
          alertBox.innerHTML = `<strong>Connection Failed:</strong> ${escapeHtml(res.error || 'Please check credentials.')}`;
        }
      })
      .catch(err => {
        btn.disabled = false;
        btn.textContent = 'Connect & Save';
        alertBox.style.display = 'block';
        alertBox.className = 'alert alert-danger';
        alertBox.innerHTML = '<strong>Request error:</strong> Could not reach device.';
      });
    }

    function escapeHtml(str) {
      return (str || '').replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    // Initial scan on load
    window.onload = scanWifi;
  </script>
</body>
</html>
"""

class CaptiveDNSHandler:
    """Lightweight UDP DNS Server resolving all queries to 10.42.0.1"""
    def __init__(self, ip="10.42.0.1", port=53):
        self.ip = ip
        self.port = port
        self.sock = None
        self.running = False
        self.thread = None

    def start(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.settimeout(1.0)
            self.sock.bind(("0.0.0.0", self.port))
            self.running = True
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
            print(f"[CaptiveDNS] Listening on UDP {self.port}")
        except Exception as e:
            # dnsmasq usually already binds port 53 with address=/#/10.42.0.1
            print(f"[CaptiveDNS] Port {self.port} in use or unavailable ({e}); dnsmasq handles DNS.")
            self.running = False

    def _run(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(512)
                if not data:
                    continue
                # Simple DNS answer packet for A record
                # Header: Transaction ID (2 bytes) + Flags (0x8180 standard response)
                transaction_id = data[:2]
                flags = b"\\x81\\x80"
                qdcount = data[4:6]
                ancount = qdcount  # 1 answer per question
                nscount = b"\\x00\\x00"
                arcount = b"\\x00\\x00"
                
                # Question section: read domain name
                idx = 12
                while idx < len(data) and data[idx] != 0:
                    idx += 1 + data[idx]
                idx += 1  # null byte
                qtype_qclass = data[idx:idx+4]
                question = data[12:idx+4]

                # Answer: Pointer to name (0xc00c) + TYPE A (0x0001) + CLASS IN (0x0001) + TTL (60s) + Data len (4) + IP
                ip_parts = [int(p) for p in self.ip.split(".")]
                answer = b"\\xc0\\x0c\\x00\\x01\\x00\\x01\\x00\\x00\\x00\\x3c\\x00\\x04" + bytes(ip_parts)
                
                response = transaction_id + flags + qdcount + ancount + nscount + arcount + question + answer
                self.sock.sendto(response, addr)
            except socket.timeout:
                continue
            except Exception:
                break

    def stop(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass


class CaptiveHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    """Handles HTTP requests and captive portal probe redirects."""

    def log_message(self, format, *args):
        # Silence default request logging
        return

    def do_GET(self):
        host = self.headers.get("Host", "")
        path = self.path

        # Handle Captive Portal detection probes (redirect to portal)
        probe_paths = [
            "/hotspot-detect.html",   # Apple
            "/canonical.html",        # Apple
            "/generate_204",          # Android / Chrome
            "/gen_204",               # Android
            "/connecttest.txt",       # Windows
            "/ncsi.txt",              # Windows
            "/redirect",
        ]
        
        # If client is requesting a known probe or foreign domain, redirect
        is_probe = any(path.startswith(p) for p in probe_paths)
        if is_probe or (host and not host.startswith("10.42.0.1") and not host.startswith("localhost")):
            self.send_response(302)
            self.send_header("Location", "http://10.42.0.1/")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            return

        if path.startswith("/api/scan"):
            self.handle_scan()
        elif path == "/" or path.startswith("/index.html") or path.startswith("/wifi"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
        else:
            # Fallback redirect to root
            self.send_response(302)
            self.send_header("Location", "http://10.42.0.1/")
            self.end_headers()

    def do_POST(self):
        if self.path.startswith("/api/connect"):
            content_len = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_len).decode("utf-8")
            try:
                data = json.loads(post_data)
            except Exception:
                data = urllib.parse.parse_qs(post_data)
                data = {k: v[0] for k, v in data.items()}

            ssid = data.get("ssid", "").strip()
            password = data.get("password", "").strip()
            self.handle_connect(ssid, password)
        else:
            self.send_response(404)
            self.end_headers()

    def handle_scan(self):
        """Scan nearby Wi-Fi networks using nmcli."""
        networks = []
        seen = set()
        try:
            # Trigger rescan and list
            res = subprocess.run(
                ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list"],
                capture_output=True, text=True, timeout=8
            )
            if res.returncode == 0:
                for line in res.stdout.strip().splitlines():
                    parts = line.split(":")
                    if len(parts) >= 2:
                        ssid = parts[0].strip()
                        signal = parts[1].strip()
                        security = parts[2].strip() if len(parts) > 2 else ""
                        if ssid and ssid != "--" and ssid != "PiZero2-AP" and ssid not in seen:
                            seen.add(ssid)
                            try:
                                sig_int = int(signal)
                            except ValueError:
                                sig_int = 50
                            networks.append({
                                "ssid": ssid,
                                "signal": sig_int,
                                "security": security
                            })
                # Sort by signal strength descending
                networks.sort(key=lambda x: x["signal"], reverse=True)
        except Exception as e:
            print(f"[CaptivePortal] Scan error: {e}")

        payload = json.dumps(networks).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(payload)

    def handle_connect(self, ssid, password):
        """Attempt connection to target Wi-Fi network."""
        if not ssid:
            self._send_json({"success": False, "error": "SSID cannot be empty"})
            return

        print(f"[CaptivePortal] Attempting connection to SSID: {ssid}")
        cmd = ["nmcli", "dev", "wifi", "connect", ssid]
        if password:
            cmd.extend(["password", password])

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if res.returncode == 0:
                print(f"[CaptivePortal] Successfully connected to {ssid}")
                # Retrieve IP
                ip_res = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=2)
                new_ip = ip_res.stdout.strip().split(" ")[0] if ip_res.returncode == 0 else ""
                
                self._send_json({
                    "success": True,
                    "message": f"Connected to {ssid}",
                    "ip": new_ip
                })

                # Notify server callback if registered
                if hasattr(self.server, "on_connected_callback") and self.server.on_connected_callback:
                    threading.Thread(target=self.server.on_connected_callback, args=(ssid, new_ip), daemon=True).start()
            else:
                err = res.stderr.strip() or res.stdout.strip() or "Connection failed"
                print(f"[CaptivePortal] Connection error: {err}")
                self._send_json({"success": False, "error": err})
        except Exception as e:
            print(f"[CaptivePortal] Exception connecting: {e}")
            self._send_json({"success": False, "error": str(e)})

    def _send_json(self, data):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(payload)


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class CaptivePortal:
    """Manager for Captive Portal HTTP and DNS services."""
    def __init__(self, on_connected=None, port=80, ip="10.42.0.1"):
        self.on_connected = on_connected
        self.port = port
        self.ip = ip
        self.http_server = None
        self.dns_server = None
        self.http_thread = None
        self.is_running = False

    def start(self):
        """Start both HTTP captive portal and DNS listener."""
        if self.is_running:
            return

        # Start DNS
        self.dns_server = CaptiveDNSHandler(ip=self.ip, port=53)
        self.dns_server.start()

        # Start HTTP Server on port 80
        try:
            self.http_server = ThreadingHTTPServer(("0.0.0.0", self.port), CaptiveHTTPRequestHandler)
            self.http_server.on_connected_callback = self.on_connected
            self.http_thread = threading.Thread(target=self.http_server.serve_forever, daemon=True)
            self.http_thread.start()
            self.is_running = True
            print(f"[CaptivePortal] HTTP Server active on port {self.port}")
        except Exception as e:
            print(f"[CaptivePortal] Failed to start HTTP server on port {self.port}: {e}")
            self.is_running = False

    def stop(self):
        """Stop captive portal HTTP and DNS servers."""
        if not self.is_running and not self.http_server and not self.dns_server:
            return

        print("[CaptivePortal] Stopping captive portal services...")
        if self.dns_server:
            try:
                self.dns_server.stop()
            except Exception:
                pass
            self.dns_server = None

        if self.http_server:
            try:
                self.http_server.shutdown()
                self.http_server.server_close()
            except Exception:
                pass
            self.http_server = None

        self.is_running = False
        print("[CaptivePortal] Captive portal stopped.")


if __name__ == "__main__":
    portal = CaptivePortal()
    portal.start()
    print("Captive Portal running. Press Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        portal.stop()
