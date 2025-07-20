#!/usr/bin/env python3
"""
Example client for consuming the Pi Camera stream
This demonstrates how other applications can use the video stream
"""

import requests
import numpy as np
from urllib.parse import urljoin
from PIL import Image
import time
import io

class PiCameraClient:
    def __init__(self, server_url="http://localhost:5000"):
        """
        Initialize the Pi Camera client
        
        Args:
            server_url (str): URL of the Pi camera server
        """
        self.server_url = server_url
        self.session = requests.Session()
        
    def get_status(self):
        """Get the current streaming status"""
        try:
            response = self.session.get(urljoin(self.server_url, "/status"))
            return response.json()
        except Exception as e:
            print(f"Error getting status: {e}")
            return None
            
    def start_stream(self):
        """Start the camera stream"""
        try:
            response = self.session.post(urljoin(self.server_url, "/start_stream"))
            return response.json()
        except Exception as e:
            print(f"Error starting stream: {e}")
            return None
            
    def stop_stream(self):
        """Stop the camera stream"""
        try:
            response = self.session.post(urljoin(self.server_url, "/stop_stream"))
            return response.json()
        except Exception as e:
            print(f"Error stopping stream: {e}")
            return None
            
    def get_frame(self):
        """Get a single frame from the video stream as PIL Image"""
        try:
            response = self.session.get(urljoin(self.server_url, "/video_feed"), 
                                      stream=True, timeout=5)
            
            # Read the multipart response
            for chunk in response.iter_content(chunk_size=1024):
                if b'\xff\xd8' in chunk:  # JPEG start marker
                    # Find the start and end of the JPEG
                    start = chunk.find(b'\xff\xd8')
                    end = chunk.find(b'\xff\xd9')
                    
                    if start != -1 and end != -1:
                        jpeg_data = chunk[start:end+2]
                        
                        # Convert to PIL Image
                        image = Image.open(io.BytesIO(jpeg_data))
                        return image
                        
        except Exception as e:
            print(f"Error getting frame: {e}")
            return None
            
    def stream_and_display(self, save_frames=False, output_dir="frames"):
        """
        Stream video from the Pi camera and display using PIL
        
        Args:
            save_frames (bool): Whether to save frames to disk
            output_dir (str): Directory to save frames
        """
        
        if save_frames:
            import os
            os.makedirs(output_dir, exist_ok=True)
            frame_count = 0
            
        print("Starting video stream...")
        print("Note: This example saves frames but doesn't display them in real-time")
        print("For real-time display, consider using tkinter or another GUI library")
        print("Press Ctrl+C to quit")
        
        try:
            response = self.session.get(urljoin(self.server_url, "/video_feed"), 
                                      stream=True, timeout=10)
            
            bytes_data = b''
            
            for chunk in response.iter_content(chunk_size=1024):
                bytes_data += chunk
                
                # Look for JPEG boundaries
                start = bytes_data.find(b'\xff\xd8')
                end = bytes_data.find(b'\xff\xd9')
                
                if start != -1 and end != -1:
                    jpeg_data = bytes_data[start:end+2]
                    bytes_data = bytes_data[end+2:]
                    
                    # Decode frame using PIL
                    try:
                        image = Image.open(io.BytesIO(jpeg_data))
                        
                        if save_frames:
                            filename = f"{output_dir}/frame_{frame_count:06d}.jpg"
                            image.save(filename)
                            frame_count += 1
                            
                            if frame_count % 30 == 0:  # Print every 30 frames
                                print(f"Saved {frame_count} frames... (Latest: {image.size})")
                        else:
                            # Just print frame info without saving
                            print(f"Received frame: {image.size}, mode: {image.mode}")
                            
                    except Exception as e:
                        print(f"Error processing frame: {e}")
                        continue
                                
        except KeyboardInterrupt:
            print("\nStream interrupted by user")
        except Exception as e:
            print(f"Streaming error: {e}")
            
    def stream_to_tkinter(self):
        """
        Stream video and display in a tkinter window
        This is an optional method that requires tkinter
        """
        try:
            import tkinter as tk
            from tkinter import ttk
            from PIL import ImageTk
        except ImportError:
            print("tkinter not available. Install with: sudo apt-get install python3-tk")
            return
            
        root = tk.Tk()
        root.title("Pi Camera Stream")
        root.geometry("660x500")
        
        # Create label for video
        video_label = ttk.Label(root)
        video_label.pack(expand=True)
        
        # Status label
        status_label = ttk.Label(root, text="Connecting...")
        status_label.pack()
        
        def update_frame():
            try:
                image = self.get_frame()
                if image:
                    # Convert PIL image to tkinter PhotoImage
                    photo = ImageTk.PhotoImage(image)
                    video_label.configure(image=photo)
                    video_label.image = photo  # Keep a reference
                    status_label.configure(text=f"Streaming - {image.size}")
                else:
                    status_label.configure(text="No frame received")
            except Exception as e:
                status_label.configure(text=f"Error: {e}")
                
            # Schedule next update
            root.after(100, update_frame)  # Update every 100ms
            
        # Start the update loop
        update_frame()
        
        print("Starting tkinter display. Close window to stop.")
        root.mainloop()

def main():
    """Example usage of the Pi Camera client"""
    
    # Initialize client
    print("Pi Camera Stream Client (PIL/Pillow version)")
    print("=" * 45)
    
    # You can change this to your Pi's IP address
    client = PiCameraClient("http://localhost:5000")
    
    # Check status
    status = client.get_status()
    if status:
        print(f"Server status: {status}")
    else:
        print("Could not connect to server")
        return
        
    # Start streaming if not already active
    if not status.get('streaming', False):
        print("Starting stream...")
        start_result = client.start_stream()
        print(f"Start result: {start_result}")
        time.sleep(2)  # Wait for stream to start
        
    # Offer different display options
    print("\nChoose display method:")
    print("1. Save frames to disk (no real-time display)")
    print("2. Display in tkinter window (if available)")
    print("3. Just get single frame")
    
    choice = input("Enter choice (1-3): ").strip()
    
    try:
        if choice == "1":
            client.stream_and_display(save_frames=True)
        elif choice == "2":
            client.stream_to_tkinter()
        elif choice == "3":
            print("Getting single frame...")
            frame = client.get_frame()
            if frame:
                frame.save("single_frame.jpg")
                print(f"Saved single frame: {frame.size}, mode: {frame.mode}")
            else:
                print("Failed to get frame")
        else:
            print("Invalid choice, defaulting to frame info display")
            client.stream_and_display(save_frames=False)
    except Exception as e:
        print(f"Error during streaming: {e}")
        
    print("\nClient finished")

if __name__ == "__main__":
    main() 