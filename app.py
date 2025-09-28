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
import struct
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
# Ultra-Low Latency Audio Broadcaster
# -------------------- 
SAMPLE_RATE = 48000  # Higher sample rate for better quality
CHUNK_SIZE = 256     # Much smaller chunks for lower latency
CHANNELS = 2
DTYPE = np.float32

# Buffer settings optimized for low latency
MIN_BUFFER_MS = 20   # Minimum 20ms buffer
MAX_BUFFER_MS = 100  # Maximum 100ms buffer
TARGET_BUFFER_MS = 40  # Target 40ms buffer

class UltraLowLatencyBroadcaster:
    def __init__(self):
        self.clients = {}  # client_id -> client_info
        self.audio_queue = asyncio.Queue(maxsize=50)  # Async queue for better performance
        self.running = False
        self.start_time = None
        self.sequence_number = 0
        
        # Network optimization
        self.compression_enabled = True
        self.adaptive_quality = True
        
        # Timing precision
        self.master_clock = time.time()
        self.clock_drift_compensation = {}
        
        # Statistics
        self.stats = {
            'packets_sent': 0,
            'clients_connected': 0,
            'avg_latency': 0,
            'packet_loss': 0,
            'buffer_underruns': 0
        }
        
    async def add_client(self, websocket, path=None):
        client_id = f"client_{int(time.time() * 1000000) % 1000000}"
        client_info = {
            'websocket': websocket,
            'connected_at': time.time(),
            'last_ping': 0,
            'latency': 0,
            'buffer_health': 0,
            'packets_received': 0,
            'last_sequence': -1
        }
        
        self.clients[client_id] = client_info
        self.stats['clients_connected'] = len(self.clients)
        
        logger.info(f"Client {client_id} connected. Total: {len(self.clients)}")
        
        # Send initial configuration
        await self.send_to_client(client_id, {
            'type': 'init',
            'client_id': client_id,
            'sample_rate': SAMPLE_RATE,
            'chunk_size': CHUNK_SIZE,
            'channels': CHANNELS,
            'target_buffer_ms': TARGET_BUFFER_MS,
            'server_time': time.time(),
            'config': {
                'use_compression': self.compression_enabled,
                'adaptive_quality': self.adaptive_quality,
                'precision_mode': True
            }
        })
        
        return client_id
    
    async def remove_client(self, client_id):
        if client_id in self.clients:
            del self.clients[client_id]
            self.stats['clients_connected'] = len(self.clients)
            logger.info(f"Client {client_id} disconnected. Remaining: {len(self.clients)}")
    
    async def send_to_client(self, client_id, data):
        if client_id not in self.clients:
            return False
        
        try:
            websocket = self.clients[client_id]['websocket']
            if websocket.open:
                # Use binary mode for audio data, text for control messages
                if data.get('type') == 'audio':
                    # Send as binary for better performance
                    binary_data = self.pack_audio_data(data)
                    await websocket.send(binary_data)
                else:
                    await websocket.send(json.dumps(data))
                return True
        except websockets.exceptions.ConnectionClosed:
            await self.remove_client(client_id)
        except Exception as e:
            logger.error(f"Error sending to client {client_id}: {e}")
            await self.remove_client(client_id)
        
        return False
    
    def pack_audio_data(self, data):
        """Pack audio data into efficient binary format"""
        # Header: type(1) + sequence(4) + timestamp(8) + sample_rate(4) + channels(1) + data_length(4)
        header = struct.pack('!BIdiBI', 
            1,  # Audio type
            data['sequence'],
            data['timestamp'],
            data['server_time'],
            SAMPLE_RATE,
            CHANNELS,
            len(data['audio_data'])
        )
        
        return header + data['audio_data']
    
    async def broadcast_audio_data(self, audio_data, timestamp):
        """Broadcast audio with ultra-low latency optimizations"""
        if not self.clients:
            return
        
        # Convert to bytes for transmission
        audio_bytes = audio_data.astype(np.float32).tobytes()
        
        # Calculate precise timing
        server_time = time.time()
        play_time = server_time + (TARGET_BUFFER_MS / 1000.0)
        
        packet = {
            'type': 'audio',
            'sequence': self.sequence_number,
            'timestamp': timestamp,
            'server_time': server_time,
            'play_at': play_time,
            'sample_rate': SAMPLE_RATE,
            'channels': CHANNELS,
            'audio_data': audio_bytes,
            'chunk_duration_ms': (len(audio_data) // CHANNELS) / SAMPLE_RATE * 1000
        }
        
        self.sequence_number += 1
        self.stats['packets_sent'] += 1
        
        # Send to all clients concurrently
        tasks = []
        for client_id in list(self.clients.keys()):
            tasks.append(self.send_to_client(client_id, packet))
        
        # Wait for all sends to complete
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def audio_broadcast_loop(self):
        """Main audio broadcasting loop with minimal latency"""
        while self.running:
            try:
                # Get audio data with timeout to prevent blocking
                audio_data = await asyncio.wait_for(
                    self.audio_queue.get(), 
                    timeout=0.1
                )
                
                if audio_data is not None:
                    timestamp = time.time()
                    await self.broadcast_audio_data(audio_data, timestamp)
                
                # Minimal sleep to prevent CPU overload
                await asyncio.sleep(0.001)
                
            except asyncio.TimeoutError:
                # No audio data available, continue
                continue
            except Exception as e:
                logger.error(f"Error in broadcast loop: {e}")
                await asyncio.sleep(0.01)
    
    async def sync_loop(self):
        """Send sync packets to maintain timing precision"""
        while self.running:
            try:
                if self.clients:
                    sync_packet = {
                        'type': 'sync',
                        'server_time': time.time(),
                        'sequence': self.sequence_number,
                        'client_count': len(self.clients),
                        'stats': self.stats.copy()
                    }
                    
                    # Send sync to all clients
                    for client_id in list(self.clients.keys()):
                        await self.send_to_client(client_id, sync_packet)
                
                # Sync every 1 second
                await asyncio.sleep(1.0)
                
            except Exception as e:
                logger.error(f"Error in sync loop: {e}")
                await asyncio.sleep(1.0)
    
    def add_audio_data(self, audio_data):
        """Add audio data to broadcast queue (called from audio callback)"""
        try:
            # Non-blocking put - if queue is full, drop oldest
            try:
                self.audio_queue.put_nowait(audio_data)
            except asyncio.QueueFull:
                # Remove oldest and add new
                try:
                    self.audio_queue.get_nowait()
                    self.audio_queue.put_nowait(audio_data)
                    self.stats['buffer_underruns'] += 1
                except asyncio.QueueEmpty:
                    pass
        except Exception as e:
            logger.error(f"Error adding audio data: {e}")

# Global broadcaster
broadcaster = UltraLowLatencyBroadcaster()

def optimized_audio_callback(indata, frames, time_info, status):
    """Optimized audio input callback for minimal latency"""
    if status:
        logger.warning(f"Audio status: {status}")
    
    try:
        # Minimal processing to reduce latency
        audio_data = indata.copy().astype(np.float32)
        
        # Simple gain control to prevent clipping
        peak = np.max(np.abs(audio_data))
        if peak > 0.95:
            audio_data *= 0.95 / peak
        
        # Add to broadcaster queue
        broadcaster.add_audio_data(audio_data)
        
    except Exception as e:
        logger.error(f"Audio callback error: {e}")

async def handle_websocket_connection(websocket):
    """Handle WebSocket connections with enhanced error handling"""
    client_id = None
    try:
        client_id = await broadcaster.add_client(websocket, None)
        
        # Handle client messages
        async for message in websocket:
            try:
                if isinstance(message, bytes):
                    # Binary message handling if needed
                    continue
                
                data = json.loads(message)
                await handle_client_message(client_id, data)
                
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON from client {client_id}")
            except Exception as e:
                logger.error(f"Error handling message from {client_id}: {e}")
                
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")
    finally:
        if client_id:
            await broadcaster.remove_client(client_id)

async def handle_client_message(client_id, data):
    """Handle messages from clients"""
    if client_id not in broadcaster.clients:
        return
    
    client_info = broadcaster.clients[client_id]
    
    if data.get('type') == 'ping':
        # High precision ping response
        current_time = time.time()
        latency = current_time - data.get('client_time', current_time)
        client_info['latency'] = latency
        client_info['last_ping'] = current_time
        
        response = {
            'type': 'pong',
            'server_time': current_time,
            'client_time': data.get('client_time'),
            'measured_latency': latency * 1000,  # Convert to ms
            'client_id': client_id
        }
        await broadcaster.send_to_client(client_id, response)
    
    elif data.get('type') == 'buffer_status':
        client_info['buffer_health'] = data.get('buffer_size', 0)
        
        # Adaptive quality adjustment
        if data.get('buffer_size', 0) < 2:
            # Send buffer adjustment
            response = {
                'type': 'buffer_adjust',
                'target_buffer_ms': min(TARGET_BUFFER_MS + 10, MAX_BUFFER_MS),
                'reason': 'low_buffer'
            }
            await broadcaster.send_to_client(client_id, response)
    
    elif data.get('type') == 'stats':
        # Update client statistics
        client_info['packets_received'] = data.get('packets_received', 0)
        client_info['last_sequence'] = data.get('last_sequence', -1)

async def main_server():
    """Main server with both WebSocket and audio processing"""
    broadcaster.running = True
    broadcaster.start_time = time.time()
    
    # Start background tasks
    broadcast_task = asyncio.create_task(broadcaster.audio_broadcast_loop())
    sync_task = asyncio.create_task(broadcaster.sync_loop())
    
    try:
        # Start audio input stream with optimized settings
        logger.info("Starting ultra-low latency audio capture...")
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            callback=optimized_audio_callback,
            blocksize=CHUNK_SIZE,
            latency='low',
            extra_settings=sd.default.extra_settings
        ):
            logger.info(f"Audio stream active: {SAMPLE_RATE}Hz, {CHUNK_SIZE} samples, {CHANNELS} channels")
            
            # Start WebSocket server with optimized settings
            server = await websockets.serve(
                handle_websocket_connection,
                "0.0.0.0",
                8765,
                max_size=None,  # Remove message size limit
                max_queue=10,   # Limit queue size for low latency
                compression=None,  # Disable compression for speed
                ping_interval=20,  # Keep connections alive
                ping_timeout=10
            )
            
            logger.info("WebSocket server running on ws://0.0.0.0:8765")
            logger.info("Ultra-low latency audio sync server ready!")
            
            # Keep server running
            await server.wait_closed()
            
    except Exception as e:
        logger.error(f"Server error: {e}")
    finally:
        broadcaster.running = False
        broadcast_task.cancel()
        sync_task.cancel()

if __name__ == "__main__":
    print("=== Ultra-Low Latency Multi-Device Audio Sync ===")
    print("Optimized for minimal latency and maximum stability")
    print("")
    
    # Start Flask server in background
    threading.Thread(target=run_flask, daemon=True).start()
    logger.info("Web interface running on http://0.0.0.0:5000")
    
    # Start main server
    try:
        asyncio.run(main_server())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Fatal server error: {e}")