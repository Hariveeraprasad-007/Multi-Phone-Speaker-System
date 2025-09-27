import asyncio
import websockets
import sounddevice as sd
import numpy as np
import base64
import json
import time
import threading
from flask import Flask, send_from_directory
import queue

# -------------------- 
# Flask web server 
# -------------------- 
app = Flask(__name__, static_folder="public")

@app.route("/")
def home():
    return send_from_directory("public", "index.html")

def run_flask():
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)

# -------------------- 
# WebSocket audio server with synchronization
# -------------------- 
SAMPLE_RATE = 44100  # Changed to 44.1kHz for better mobile compatibility
CHUNK = 512  # Smaller chunks for smoother mobile playback
BUFFER_SIZE = 5  # seconds of audio to buffer
SYNC_INTERVAL = 1.0  # sync every 1 second

class AudioBroadcaster:
    def __init__(self):
        self.clients = set()
        self.audio_buffer = queue.Queue()
        self.running = False
        self.start_time = None
        
    def add_client(self, websocket):
        self.clients.add(websocket)
        print(f"Client connected. Total clients: {len(self.clients)}")
        
    def remove_client(self, websocket):
        self.clients.discard(websocket)
        print(f"Client disconnected. Total clients: {len(self.clients)}")
        
    async def broadcast_audio(self):
        """Broadcast audio to all connected clients with sync timestamps"""
        while self.running:
            try:
                # Get audio data from buffer
                if not self.audio_buffer.empty():
                    audio_data = self.audio_buffer.get_nowait()
                    
                    # Create synchronized packet with server timestamp
                    current_time = time.time()
                    if self.start_time is None:
                        self.start_time = current_time
                    
                    # Schedule playback with shorter delay for mobile compatibility
                    play_time = current_time + 0.05  # 50ms delay instead of 100ms
                    
                    packet = {
                        "type": "audio",
                        "audio": audio_data,
                        "timestamp": current_time,
                        "play_at": play_time,
                        "server_time": current_time,
                        "sample_rate": SAMPLE_RATE,
                        "channels": 2
                    }
                    
                    # Send to all clients
                    if self.clients:
                        disconnected = set()
                        for client in self.clients.copy():
                            try:
                                await client.send(json.dumps(packet))
                            except websockets.exceptions.ConnectionClosed:
                                disconnected.add(client)
                            except Exception as e:
                                print(f"Error sending to client: {e}")
                                disconnected.add(client)
                        
                        # Remove disconnected clients
                        for client in disconnected:
                            self.remove_client(client)
                
                await asyncio.sleep(0.01)  # Small delay to prevent busy waiting
                
            except Exception as e:
                print(f"Error in broadcast_audio: {e}")
                await asyncio.sleep(0.1)
    
    async def send_sync_signal(self):
        """Send periodic sync signals to help clients stay synchronized"""
        while self.running:
            try:
                if self.clients:
                    sync_packet = {
                        "type": "sync",
                        "server_time": time.time(),
                        "client_count": len(self.clients)
                    }
                    
                    disconnected = set()
                    for client in self.clients.copy():
                        try:
                            await client.send(json.dumps(sync_packet))
                        except websockets.exceptions.ConnectionClosed:
                            disconnected.add(client)
                        except Exception as e:
                            disconnected.add(client)
                    
                    # Remove disconnected clients
                    for client in disconnected:
                        self.remove_client(client)
                
                await asyncio.sleep(SYNC_INTERVAL)
                
            except Exception as e:
                print(f"Error in send_sync_signal: {e}")
                await asyncio.sleep(1)

# Global broadcaster instance
broadcaster = AudioBroadcaster()

async def handle_client(websocket):
    """Handle individual client connection"""
    broadcaster.add_client(websocket)
    
    try:
        # Send initial sync packet
        init_packet = {
            "type": "init",
            "server_time": time.time(),
            "sample_rate": SAMPLE_RATE,
            "buffer_size": BUFFER_SIZE,
            "message": "Connected to synchronized audio stream"
        }
        await websocket.send(json.dumps(init_packet))
        
        # Keep connection alive and handle client messages
        async for message in websocket:
            try:
                data = json.loads(message)
                if data.get("type") == "ping":
                    # Respond to ping with pong for latency measurement
                    pong = {
                        "type": "pong",
                        "server_time": time.time(),
                        "client_time": data.get("client_time")
                    }
                    await websocket.send(json.dumps(pong))
            except json.JSONDecodeError:
                print("Received invalid JSON from client")
            except Exception as e:
                print(f"Error handling client message: {e}")
                
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        print(f"Error in handle_client: {e}")
    finally:
        broadcaster.remove_client(websocket)

def audio_callback(indata, frames, time_info, status):
    """Audio input callback - processes microphone input"""
    if status:
        print("Sounddevice error:", status)
    
    try:
        # Convert audio to bytes and encode
        # Normalize audio to prevent clipping
        normalized_audio = np.clip(indata, -1.0, 1.0)
        
        # Convert float32 to int16 for better compatibility across devices
        audio_int16 = (normalized_audio * 32767).astype(np.int16)
        data = audio_int16.tobytes()
        b64 = base64.b64encode(data).decode("utf-8")
        
        # Add to broadcaster queue
        if not broadcaster.audio_buffer.full():
            broadcaster.audio_buffer.put(b64)
        else:
            # If buffer is full, remove oldest item
            try:
                broadcaster.audio_buffer.get_nowait()
                broadcaster.audio_buffer.put(b64)
            except queue.Empty:
                pass
                
    except Exception as e:
        print(f"Error in audio_callback: {e}")

async def main_ws():
    """Main WebSocket server"""
    broadcaster.running = True
    
    # Start background tasks
    broadcast_task = asyncio.create_task(broadcaster.broadcast_audio())
    sync_task = asyncio.create_task(broadcaster.send_sync_signal())
    
    try:
        # Start audio input stream
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=2,
            dtype="float32",
            callback=audio_callback,
            blocksize=CHUNK,
            latency='low'  # Try to minimize latency
        ):
            print("Audio input started")
            
            # Start WebSocket server
            async with websockets.serve(handle_client, "0.0.0.0", 8765):
                print("WebSocket server running on ws://0.0.0.0:8765")
                print("Synchronization enabled - devices should play in sync")
                await asyncio.Future()  # run forever
                
    except Exception as e:
        print(f"Error in main_ws: {e}")
    finally:
        broadcaster.running = False
        broadcast_task.cancel()
        sync_task.cancel()

# -------------------- 
# Start both servers 
# -------------------- 
if __name__ == "__main__":
    # Start Flask in a thread
    threading.Thread(target=run_flask, daemon=True).start()
    print("Flask server running on http://0.0.0.0:5000")
    
    # Run WebSocket server in main loop
    try:
        asyncio.run(main_ws())
    except KeyboardInterrupt:
        print("Server stopped by user")
    except Exception as e:
        print(f"Server error: {e}")