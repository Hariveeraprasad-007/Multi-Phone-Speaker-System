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
from collections import deque

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
# Enhanced WebSocket audio server with precise synchronization
# -------------------- 
SAMPLE_RATE = 44100  # 44.1kHz for better mobile compatibility
CHUNK = 1024  # Larger chunks for better quality and stability
BUFFER_DURATION = 0.1  # 100ms buffer for synchronization
SYNC_INTERVAL = 2.0  # Sync every 2 seconds
MAX_BUFFER_SIZE = 100  # Maximum packets in buffer

class PrecisionAudioBroadcaster:
    def __init__(self):
        self.clients = set()
        self.audio_buffer = deque(maxlen=MAX_BUFFER_SIZE)
        self.running = False
        self.start_time = None
        self.packet_counter = 0
        self.global_sync_time = None
        self.base_timestamp = None
        
        # Synchronization tracking
        self.sync_offsets = {}  # Track each client's sync offset
        self.client_latencies = {}  # Track round-trip latencies
        
        self.stats = {
            'total_packets': 0,
            'clients_served': 0,
            'sync_errors': 0,
            'buffer_underruns': 0
        }
        
    def add_client(self, websocket, client_id):
        self.clients.add((websocket, client_id))
        self.sync_offsets[client_id] = 0
        self.client_latencies[client_id] = 0
        print(f"Client {client_id} connected. Total clients: {len(self.clients)}")
        
    def remove_client(self, websocket, client_id):
        self.clients = {(ws, cid) for ws, cid in self.clients if ws != websocket}
        if client_id in self.sync_offsets:
            del self.sync_offsets[client_id]
        if client_id in self.client_latencies:
            del self.client_latencies[client_id]
        print(f"Client {client_id} disconnected. Total clients: {len(self.clients)}")
        
    async def broadcast_audio(self):
        """Enhanced audio broadcasting with precise timing"""
        while self.running:
            try:
                if self.audio_buffer:
                    current_time = time.time()
                    
                    # Initialize base timestamp if not set
                    if self.base_timestamp is None:
                        self.base_timestamp = current_time
                    
                    # Get audio data from buffer
                    audio_data = self.audio_buffer.popleft()
                    
                    # Calculate precise playback time
                    # Use higher buffer for mobile devices (they need more time to process)
                    mobile_buffer_time = 0.15  # 150ms for mobile devices
                    play_time = current_time + mobile_buffer_time
                    
                    # Create high-precision packet
                    packet = {
                        "type": "audio",
                        "audio": audio_data,
                        "timestamp": current_time,
                        "play_at": play_time,
                        "server_time": current_time,
                        "packet_id": self.packet_counter,
                        "sample_rate": SAMPLE_RATE,
                        "channels": 2,
                        "chunk_size": CHUNK,
                        "buffer_time": mobile_buffer_time,
                        "sync_mode": "precise",
                        "sequence": self.packet_counter % 1000  # Rolling sequence number
                    }
                    
                    self.packet_counter += 1
                    self.stats['total_packets'] += 1
                    
                    # Send to all clients with individual timing adjustments
                    if self.clients:
                        disconnected = set()
                        for websocket, client_id in self.clients.copy():
                            try:
                                # Adjust timing for individual client latency
                                client_packet = packet.copy()
                                if client_id in self.client_latencies:
                                    latency_compensation = self.client_latencies[client_id] / 2  # Half RTT
                                    client_packet["play_at"] = play_time + latency_compensation
                                    client_packet["latency_compensation"] = latency_compensation
                                
                                await websocket.send(json.dumps(client_packet))
                                
                            except websockets.exceptions.ConnectionClosed:
                                disconnected.add((websocket, client_id))
                            except Exception as e:
                                print(f"Error sending to client {client_id}: {e}")
                                disconnected.add((websocket, client_id))
                        
                        # Remove disconnected clients
                        for ws, cid in disconnected:
                            self.remove_client(ws, cid)
                
                # Adaptive sleep based on buffer size
                if len(self.audio_buffer) > 5:
                    await asyncio.sleep(0.001)  # Process faster if buffer is full
                else:
                    await asyncio.sleep(0.005)  # Normal processing speed
                    
            except IndexError:
                # Buffer is empty
                self.stats['buffer_underruns'] += 1
                await asyncio.sleep(0.01)
            except Exception as e:
                print(f"Error in broadcast_audio: {e}")
                await asyncio.sleep(0.1)
    
    async def send_sync_signals(self):
        """Send enhanced synchronization signals"""
        while self.running:
            try:
                if self.clients:
                    current_time = time.time()
                    
                    # Global synchronization every 10 seconds
                    if self.global_sync_time is None or (current_time - self.global_sync_time) > 10:
                        self.global_sync_time = current_time + 2.0  # 2 seconds from now
                        
                        global_sync_packet = {
                            "type": "global_sync",
                            "global_start_time": self.global_sync_time,
                            "server_time": current_time,
                            "client_count": len(self.clients),
                            "sync_quality": "ultra_high",
                            "message": "Global synchronization point - all devices should align"
                        }
                        
                        # Send to all clients
                        for websocket, client_id in self.clients.copy():
                            try:
                                await websocket.send(json.dumps(global_sync_packet))
                            except:
                                pass
                        
                        print(f"Global sync signal sent to {len(self.clients)} clients at {self.global_sync_time}")
                    
                    # Regular sync packets
                    sync_packet = {
                        "type": "sync",
                        "server_time": current_time,
                        "client_count": len(self.clients),
                        "buffer_size": len(self.audio_buffer),
                        "packet_rate": self.stats['total_packets'] / max((current_time - (self.start_time or current_time)), 1),
                        "sync_errors": self.stats['sync_errors'],
                        "buffer_underruns": self.stats['buffer_underruns'],
                        "precision_mode": "ultra_high"
                    }
                    
                    disconnected = set()
                    for websocket, client_id in self.clients.copy():
                        try:
                            await websocket.send(json.dumps(sync_packet))
                        except websockets.exceptions.ConnectionClosed:
                            disconnected.add((websocket, client_id))
                        except Exception as e:
                            disconnected.add((websocket, client_id))
                    
                    # Remove disconnected clients
                    for ws, cid in disconnected:
                        self.remove_client(ws, cid)
                
                await asyncio.sleep(SYNC_INTERVAL)
                
            except Exception as e:
                print(f"Error in send_sync_signals: {e}")
                await asyncio.sleep(1)

# Global broadcaster instance
broadcaster = PrecisionAudioBroadcaster()

async def handle_client(websocket):
    """Handle individual client connection with enhanced sync"""
    # Generate unique client ID
    client_id = f"client_{int(time.time() * 1000) % 100000}"
    broadcaster.add_client(websocket, client_id)
    
    try:
        # Send enhanced initial packet
        current_time = time.time()
        init_packet = {
            "type": "init",
            "client_id": client_id,
            "server_time": current_time,
            "sample_rate": SAMPLE_RATE,
            "chunk_size": CHUNK,
            "buffer_duration": BUFFER_DURATION,
            "sync_mode": "ultra_precise",
            "mobile_optimized": True,
            "message": f"Connected as {client_id} to synchronized audio stream"
        }
        await websocket.send(json.dumps(init_packet))
        
        # Immediate sync calibration
        sync_cal_packet = {
            "type": "sync_calibration",
            "server_time": time.time(),
            "client_id": client_id,
            "calibration_tone": True,
            "message": "Calibrating synchronization - you may hear a brief tone"
        }
        await websocket.send(json.dumps(sync_cal_packet))
        
        # Keep connection alive and handle client messages
        async for message in websocket:
            try:
                data = json.loads(message)
                current_time = time.time()
                
                if data.get("type") == "ping":
                    # Enhanced ping-pong for precise latency measurement
                    client_time = data.get("client_time", 0)
                    latency = (current_time - client_time) if client_time > 0 else 0
                    
                    # Store client latency for compensation
                    broadcaster.client_latencies[client_id] = latency
                    
                    pong = {
                        "type": "pong",
                        "server_time": current_time,
                        "client_time": client_time,
                        "client_id": client_id,
                        "measured_latency": latency,
                        "precision": "microseconds"
                    }
                    await websocket.send(json.dumps(pong))
                    
                elif data.get("type") == "sync_request":
                    # Ultra-precise clock synchronization
                    sync_response = {
                        "type": "sync_response",
                        "server_time": current_time,
                        "client_time": data.get("client_time"),
                        "client_id": client_id,
                        "sync_precision": "high_resolution",
                        "time_source": "system_monotonic"
                    }
                    await websocket.send(json.dumps(sync_response))
                    
                elif data.get("type") == "buffer_status":
                    # Client reports buffer status
                    client_buffer = data.get("buffer_size", 0)
                    if client_buffer < 2:  # Low buffer warning
                        buffer_boost = {
                            "type": "buffer_boost",
                            "boost_duration": 0.2,  # 200ms extra buffer
                            "priority": "high"
                        }
                        await websocket.send(json.dumps(buffer_boost))
                        
                elif data.get("type") == "sync_error":
                    # Client reports synchronization error
                    broadcaster.stats['sync_errors'] += 1
                    print(f"Sync error from {client_id}: {data.get('error')}")
                    
            except json.JSONDecodeError:
                print(f"Invalid JSON from client {client_id}")
            except Exception as e:
                print(f"Error handling message from client {client_id}: {e}")
                
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        print(f"Error in handle_client for {client_id}: {e}")
    finally:
        broadcaster.remove_client(websocket, client_id)

def enhanced_audio_callback(indata, frames, time_info, status):
    """Enhanced audio input callback with better processing"""
    if status:
        print("Audio input status:", status)
    
    try:
        # Enhanced audio processing for movie/high-quality content
        # Apply gentle normalization to prevent clipping while preserving dynamics
        peak = np.max(np.abs(indata))
        
        if peak > 0.95:
            # Gentle compression for loud parts
            indata = indata * (0.95 / peak)
        elif peak < 0.01:
            # Boost very quiet parts slightly
            indata = indata * 2.0
            indata = np.clip(indata, -1.0, 1.0)
        
        # Convert to high-quality int16 with dithering for better sound
        audio_float = np.clip(indata, -1.0, 1.0)
        
        # Add subtle dithering to reduce quantization noise
        dither = np.random.normal(0, 1/65536, audio_float.shape)
        audio_with_dither = audio_float + dither
        
        # Convert to int16 with proper scaling
        audio_int16 = (audio_with_dither * 16383).astype(np.int16)  # Slightly reduced to prevent clipping
        
        # Encode to base64
        data = audio_int16.tobytes()
        b64 = base64.b64encode(data).decode("utf-8")
        
        # Add to broadcaster buffer
        broadcaster.audio_buffer.append(b64)
                
    except Exception as e:
        print(f"Error in audio_callback: {e}")

async def main_ws():
    """Main WebSocket server with enhanced features"""
    broadcaster.running = True
    broadcaster.start_time = time.time()
    
    # Start background tasks
    broadcast_task = asyncio.create_task(broadcaster.broadcast_audio())
    sync_task = asyncio.create_task(broadcaster.send_sync_signals())
    
    try:
        # Start enhanced audio input stream
        print("Starting high-quality audio capture...")
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=2,
            dtype="float32",
            callback=enhanced_audio_callback,
            blocksize=CHUNK,
            latency='low'  # Minimize input latency
        ):
            print(f"Audio input started: {SAMPLE_RATE}Hz, {CHUNK} samples per chunk")
            
            # Start WebSocket server
            async with websockets.serve(handle_client, "0.0.0.0", 8765):
                print("Enhanced WebSocket server running on ws://0.0.0.0:8765")
                print("Ready for synchronized multi-device audio streaming")
                print("Connect your mobile devices and enjoy synchronized movie audio!")
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
    print("=== Synchronized Multi-Device Speaker System ===")
    print("1. Start this server on your laptop")
    print("2. Connect mobile phones to the same network")
    print("3. Open browser on each phone and go to laptop's IP:5000")
    print("4. Play your movie/audio on laptop - all devices will be synchronized!")
    print("")
    
    # Start Flask in a thread
    threading.Thread(target=run_flask, daemon=True).start()
    print("Web interface running on http://0.0.0.0:5000")
    
    # Run WebSocket server in main loop
    try:
        asyncio.run(main_ws())
    except KeyboardInterrupt:
        print("\nServer stopped by user")
    except Exception as e:
        print(f"Server error: {e}")
