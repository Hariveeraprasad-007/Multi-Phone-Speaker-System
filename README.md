# 🎶 Multi-Phone Speaker System

Turn your **laptop + multiple smartphones** into a **synchronized speaker system**.  
This project streams laptop audio to multiple phones over WiFi, so all devices play sound **in sync** — solving the problem of low laptop volume while watching movies or listening to music.  

---

## 🚀 Features
- 📡 Real-time audio streaming from laptop → phones  
- ⏱️ Timestamp-based synchronization so all phones play together  
- 🔊 Multi-device support (use as many phones as you want)  
- 🎚️ Volume control per device  
- 🎧 Stereo mode (Left/Right channel split across phones)  
- ⚡ Low latency (<100ms) with buffering + drift correction  

---

## 🏗️ Tech Stack
- **Java Sound API** → Audio capture & playback  
- **Sockets (TCP/UDP)** → Laptop ↔ Phone communication  
- **Multithreading** → Handle multiple devices  
- **Synchronization Algorithm** → Timestamp-based drift correction  
- **JavaFX / Android (optional)** → Control panel UI  

---

## ⚙️ How It Works
1. Laptop runs the **Audio Server**  
   - Captures system audio (PCM format).  
   - Splits audio into small chunks (20–40 ms).  
   - Sends chunks + timestamps to connected phones.  

2. Phones run the **Audio Client**  
   - Receive audio chunks and buffer them.  
   - Align playback with timestamps from server.  
   - Adjust playback slightly (±1%) to stay in sync.  

---

## 📐 System Architecture

---

## 📝 Algorithm (Simplified)

**Server (Laptop):**
1. Capture audio chunk (40 ms).  
2. Attach timestamp.  
3. Send to all clients.  

**Client (Phone):**
1. Receive `[timestamp, audio_chunk]`.  
2. Store in buffer (100ms).  
3. Wait until local clock ≈ timestamp.  
4. Play audio in sync with others.  

---

## 🔮 Future Enhancements
- 📱 QR Code scanning for easy device connection  
- 🎶 Opus/AAC compression for lower bandwidth  
- 🌐 Web client (open in browser instead of Android app)  
- 🎛️ Chromecast-like master device selection  

---

## 📊 Resume Value
This project demonstrates:  
- 🎧 Real-time audio streaming  
- 🌍 Cross-device communication  
- ⚡ Networking & concurrency in Java  
- 🕒 Time synchronization algorithms  
- 🎨 System design & scalability  

**Sample Resume Line:**  
> Developed a multi-device synchronized speaker system in Java, streaming laptop audio to multiple smartphones over WiFi using socket programming, multithreading, and timestamp-based synchronization (<100ms latency).  

---

⚡ Ready to build your own **distributed speaker system**? Let’s sync the beats! 🎵
