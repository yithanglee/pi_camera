#!/usr/bin/env python3
"""
Example client for consuming the Pi Camera stream
This demonstrates how other applications can use the video stream
"""

import requests
import cv2
import numpy as np
from urllib.parse import urljoin
import time

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
        """Get a single frame from the video stream"""
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
                        
                        # Convert to OpenCV image
                        nparr = np.frombuffer(jpeg_data, np.uint8)
                        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                        return frame
                        
        except Exception as e:
            print(f"Error getting frame: {e}")
            return None
            
    def stream_video(self, display=True, save_frames=False, output_dir="frames"):
        """
        Stream video from the Pi camera
        
        Args:
            display (bool): Whether to display the video using OpenCV
            save_frames (bool): Whether to save frames to disk
            output_dir (str): Directory to save frames
        """
        
        if save_frames:
            import os
            os.makedirs(output_dir, exist_ok=True)
            frame_count = 0
            
        print("Starting video stream...")
        print("Press 'q' to quit, 's' to save current frame")
        
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
                    
                    # Decode frame
                    nparr = np.frombuffer(jpeg_data, np.uint8)
                    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    
                    if frame is not None:
                        if display:
                            cv2.imshow('Pi Camera Stream', frame)
                            
                            key = cv2.waitKey(1) & 0xFF
                            if key == ord('q'):
                                break
                            elif key == ord('s') and save_frames:
                                filename = f"{output_dir}/frame_{frame_count:06d}.jpg"
                                cv2.imwrite(filename, frame)
                                print(f"Saved frame: {filename}")
                                frame_count += 1
                                
                        if save_frames and not display:
                            filename = f"{output_dir}/frame_{frame_count:06d}.jpg"
                            cv2.imwrite(filename, frame)
                            frame_count += 1
                            
                            if frame_count % 30 == 0:  # Print every 30 frames
                                print(f"Saved {frame_count} frames...")
                                
        except KeyboardInterrupt:
            print("\nStream interrupted by user")
        except Exception as e:
            print(f"Streaming error: {e}")
        finally:
            if display:
                cv2.destroyAllWindows()

def main():
    """Example usage of the Pi Camera client"""
    
    # Initialize client
    print("Pi Camera Stream Client")
    print("=" * 30)
    
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
        
    # Stream video
    try:
        client.stream_video(display=True, save_frames=False)
    except Exception as e:
        print(f"Error during streaming: {e}")
        
    print("\nClient finished")

if __name__ == "__main__":
    main() 