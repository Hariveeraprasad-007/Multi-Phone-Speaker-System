project:
  name: "Sync Speaker - Multi-Device Synchronized Audio Streaming"
  description: >
    Turn your phones, tablets, and laptops into perfectly synchronized wireless
    speakers for movies, music, or presentations. Streams audio from your computer
    to multiple devices over WiFi with millisecond synchronization using Flask,
    WebSockets, and the Web Audio API.
  license: "MIT"
  version: "1.0.0"

features:
  - "📡 Real-time audio streaming using WebSockets"
  - "🔊 Stereo high-quality sound (44.1 kHz, adjustable)"
  - "⏱️ Precise synchronization across devices (latency measurement & compensation)"
  - "📊 Live metrics: latency, buffer health, sync quality"
  - "📱 Mobile-friendly UI with visualizer & controls"
  - "🌐 Zero installation on clients (just open browser)"
  - "🖥️ Works with movies, YouTube, music players, and games"

structure:
  root: "/sync-speaker"
  files:
    - "server.py : Backend (Flask + WebSocket + audio capture + sync)"
    - "public/index.html : Frontend (Web client player & UI)"

requirements:
  system:
    - "Python 3.9+"
    - "Windows, macOS, or Linux"
  python_libraries:
    - flask
    - websockets
    - sounddevice
    - numpy
  virtual_audio_devices:
    windows: "VB-Audio Virtual Cable"
    macos: "BlackHole or Loopback"
    linux: "PulseAudio loopback module"

usage:
  steps:
    - "Start the server: python server.py"
    - "Check logs for server running on http://0.0.0.0:5000 and ws://0.0.0.0:8765"
    - "On phones/tablets: open browser and visit http://<your-laptop-ip>:5000"
    - "Click 'Enable Audio' then 'Connect'"
    - "Play music or movies on the server laptop"
    - "All connected devices will play audio in sync"

configuration:
  parameters:
    SAMPLE_RATE:
      default: 44100
      description: "Audio sample rate (use 48000 for higher quality if supported)"
    CHUNK:
      default: 1024
      description: "Buffer size per audio frame (smaller = lower latency, larger = smoother)"
    BUFFER_DURATION:
      default: 0.1
      description: "Buffer length in seconds (100ms default)"
    SYNC_INTERVAL:
      default: 2.0
      description: "Interval in seconds for sync packets"
    MAX_BUFFER_SIZE:
      default: 100
      description: "Maximum number of audio packets in queue"

client_ui:
  controls:
    - "Enable Audio button"
    - "Connect / Disconnect buttons"
    - "Volume slider"
  features:
    - "Real-time audio visualizer"
    - "Latency, buffer, and sync quality metrics"
    - "Status log with timestamps"

notes:
  - "All devices must be on the same WiFi LAN."
  - "Mobile browsers (especially iOS) block autoplay: user must tap Enable Audio first."
  - "Default delay ~200ms ensures smooth playback across devices."
  - "System automatically re-syncs every few seconds to prevent drift."
  - "For stability, run server on Ethernet if possible."

troubleshooting:
  no_audio:
    - "Ensure you clicked 'Enable Audio'."
    - "Check if VB-Cable (Windows) or BlackHole (macOS) is selected as input."
  audio_lag:
    - "Increase BUFFER_DURATION to 0.2 (200ms)."
    - "Set CHUNK = 2048 for more stable playback."
  connection_issues:
    - "Ensure firewall allows Python to open ports 5000 (HTTP) and 8765 (WebSocket)."
    - "Use laptop IP instead of localhost on other devices."

future_improvements:
  - "Native system audio capture (remove need for VB-Cable/BlackHole)."
  - "PWA mode for mobile offline use."
  - "WebRTC support for lower latency streaming."
  - "Server-side EQ, reverb, and effects."
  - "Multi-room audio grouping like Sonos."

credits:
  - "Flask - lightweight Python web server"
  - "WebSockets - real-time audio delivery"
  - "SoundDevice - audio capture"
  - "VB-Audio Cable / BlackHole - virtual audio devices"
