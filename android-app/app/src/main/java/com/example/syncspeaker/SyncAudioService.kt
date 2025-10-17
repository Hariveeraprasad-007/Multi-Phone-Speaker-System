package com.example.syncspeaker

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.*
import android.net.wifi.WifiManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import okhttp3.*
import okio.ByteString
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.ShortBuffer
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

class SyncAudioService : Service() {

    companion object {
        const val ACTION_START = "com.example.syncspeaker.action.START"
        const val ACTION_STOP = "com.example.syncspeaker.action.STOP"
        const val EXTRA_HOST = "extra_host"
        const val EXTRA_PORT = "extra_port"

        private const val NOTIF_CHANNEL_ID = "syncspeaker_channel"
        private const val NOTIF_ID = 1001
    }

    private val logTag = "SyncAudioService"

    private var host: String = "10.0.2.2"
    private var port: Int = 8765

    private var client: OkHttpClient? = null
    private var webSocket: WebSocket? = null

    private var audioTrack: AudioTrack? = null
    private var audioSessionId: Int = AudioManager.AUDIO_SESSION_ID_GENERATE

    private var wakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null

    private val isRunning = AtomicBoolean(false)
    private val isConnected = AtomicBoolean(false)

    private val playbackQueue = ArrayBlockingQueue<ShortArray>(32)
    private var playbackThread: Thread? = null

    private var reconnectThread: Thread? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                host = intent.getStringExtra(EXTRA_HOST) ?: host
                port = intent.getIntExtra(EXTRA_PORT, port)
                startForegroundServiceInternal()
            }
            ACTION_STOP -> {
                stopSelfSafely()
            }
            else -> {
                // If system restarts service, resume with last known config
                startForegroundServiceInternal()
            }
        }
        return START_STICKY
    }

    private fun startForegroundServiceInternal() {
        if (isRunning.get()) return
        isRunning.set(true)

        val notification = buildNotification("Connecting to $host:$port…")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(
                NOTIF_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK
            )
        } else {
            startForeground(NOTIF_ID, notification)
        }

        acquireLocks()
        initAudioTrack()
        connectWebSocket()
        startPlaybackLoop()
    }

    private fun stopSelfSafely() {
        isRunning.set(false)
        isConnected.set(false)

        try { webSocket?.close(1000, "stop") } catch (_: Throwable) {}
        webSocket = null
        client?.dispatcher?.executorService?.shutdown()
        client = null

        playbackThread?.interrupt()
        playbackThread = null

        releaseAudio()
        releaseLocks()

        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun buildNotification(status: String): Notification {
        val openIntent = Intent(this, MainActivity::class.java)
        val contentPendingIntent = PendingIntent.getActivity(
            this, 0, openIntent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        val stopIntent = Intent(this, SyncAudioService::class.java).apply { action = ACTION_STOP }
        val stopPending = PendingIntent.getService(
            this, 1, stopIntent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        return NotificationCompat.Builder(this, NOTIF_CHANNEL_ID)
            .setContentTitle(getString(R.string.notif_title))
            .setContentText(status)
            .setSmallIcon(android.R.drawable.stat_sys_headset)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(contentPendingIntent)
            .addAction(0, getString(R.string.action_stop), stopPending)
            .build()
    }

    private fun updateNotification(text: String) {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(NOTIF_ID, buildNotification(text))
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            val channel = NotificationChannel(
                NOTIF_CHANNEL_ID,
                getString(R.string.channel_name),
                NotificationManager.IMPORTANCE_LOW
            )
            channel.description = getString(R.string.channel_desc)
            nm.createNotificationChannel(channel)
        }
    }

    private fun acquireLocks() {
        try {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "$logTag:Wake").apply {
                setReferenceCounted(false)
                acquire()
            }
        } catch (t: Throwable) {
            Log.w(logTag, "WakeLock failed: ${t.message}")
        }
        try {
            val wm = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
            val mode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) WifiManager.WIFI_MODE_FULL_LOW_LATENCY else WifiManager.WIFI_MODE_FULL_HIGH_PERF
            wifiLock = wm.createWifiLock(mode, "$logTag:Wifi").apply {
                setReferenceCounted(false)
                acquire()
            }
        } catch (t: Throwable) {
            Log.w(logTag, "WifiLock failed: ${t.message}")
        }
    }

    private fun releaseLocks() {
        try { wakeLock?.let { if (it.isHeld) it.release() } } catch (_: Throwable) {}
        try { wifiLock?.let { if (it.isHeld) it.release() } } catch (_: Throwable) {}
        wakeLock = null
        wifiLock = null
    }

    private fun initAudioTrack(sampleRate: Int = 44100) {
        try {
            val attributes = AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_MEDIA)
                .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                .build()

            val format = AudioFormat.Builder()
                .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                .setSampleRate(sampleRate)
                .setChannelMask(AudioFormat.CHANNEL_OUT_STEREO)
                .build()

            val minBuf = AudioTrack.getMinBufferSize(
                sampleRate,
                AudioFormat.CHANNEL_OUT_STEREO,
                AudioFormat.ENCODING_PCM_16BIT
            )
            val bufferSize = (minBuf * 2).coerceAtLeast(4096)

            val at = AudioTrack(
                attributes,
                format,
                bufferSize,
                AudioTrack.MODE_STREAM,
                audioSessionId
            )
            at.play()
            audioTrack = at
        } catch (t: Throwable) {
            Log.e(logTag, "AudioTrack init error: ${t.message}")
        }
    }

    private fun releaseAudio() {
        try { audioTrack?.stop() } catch (_: Throwable) {}
        try { audioTrack?.release() } catch (_: Throwable) {}
        audioTrack = null
        playbackQueue.clear()
    }

    private fun startPlaybackLoop() {
        playbackThread = Thread({
            android.os.Process.setThreadPriority(android.os.Process.THREAD_PRIORITY_AUDIO)
            val localTrack = audioTrack
            if (localTrack == null) {
                Log.e(logTag, "AudioTrack is null; playback loop aborting")
                return@Thread
            }
            while (isRunning.get() && !Thread.currentThread().isInterrupted) {
                try {
                    val chunk = playbackQueue.take() // blocking wait
                    var written = 0
                    while (written < chunk.size) {
                        val w = localTrack.write(chunk, written, chunk.size - written, AudioTrack.WRITE_BLOCKING)
                        if (w < 0) break
                        written += w
                    }
                } catch (ie: InterruptedException) {
                    break
                } catch (t: Throwable) {
                    Log.w(logTag, "Playback error: ${t.message}")
                }
            }
        }, "PlaybackThread").apply { isDaemon = true; start() }
    }

    private fun connectWebSocket() {
        client = OkHttpClient.Builder()
            .pingInterval(20, TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.SECONDS) // websocket
            .build()

        val url = "ws://$host:$port"
        val request = Request.Builder().url(url).build()
        updateNotification("Connecting to $host:$port…")

        webSocket = client!!.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                isConnected.set(true)
                updateNotification("Connected to $host:$port")
                // request initial sync
                sendJson(mapOf("type" to "sync_request"))
                // kick off ping timer
                startPingLoop()
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                handleMessage(text)
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                // If server ever sends binary, ignore or parse as UTF-8
                bytes.utf8()?.let { handleMessage(it) }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                isConnected.set(false)
                updateNotification("Disconnected ($code)")
                scheduleReconnect()
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                isConnected.set(false)
                updateNotification("Connection error: ${t.message}")
                scheduleReconnect()
            }
        })
    }

    private fun scheduleReconnect() {
        if (!isRunning.get()) return
        if (reconnectThread?.isAlive == true) return
        reconnectThread = Thread({
            var delayMs = 1000L
            while (isRunning.get() && !isConnected.get()) {
                try {
                    Thread.sleep(delayMs)
                } catch (_: InterruptedException) { return@Thread }
                try {
                    connectWebSocket()
                } catch (t: Throwable) {
                    Log.w(logTag, "Reconnect failed: ${t.message}")
                }
                delayMs = (delayMs * 2).coerceAtMost(30000L)
            }
        }, "ReconnectThread").apply { isDaemon = true; start() }
    }

    private fun startPingLoop() {
        Thread({
            while (isRunning.get() && isConnected.get()) {
                try {
                    val clientTime = System.nanoTime() / 1_000_000_000.0
                    sendJson(mapOf(
                        "type" to "ping",
                        "client_time" to clientTime,
                        "performance_time" to System.nanoTime() / 1_000_000.0
                    ))
                    Thread.sleep(2000)
                } catch (_: Throwable) { break }
            }
        }, "PingThread").apply { isDaemon = true; start() }
    }

    private fun handleMessage(text: String) {
        try {
            val obj = JSONObject(text)
            when (obj.optString("type")) {
                "audio" -> handleAudio(obj)
                "pong" -> handlePong(obj)
                "sync", "sync_response" -> { /* optional: update clocks */ }
                "global_sync" -> { playbackQueue.clear() }
            }
        } catch (t: Throwable) {
            Log.w(logTag, "JSON error: ${t.message}")
        }
    }

    private fun handlePong(obj: JSONObject) {
        // Optionally compute latency here
    }

    private fun handleAudio(obj: JSONObject) {
        val b64 = obj.optString("audio", null) ?: return
        try {
            val bytes = android.util.Base64.decode(b64, android.util.Base64.DEFAULT)
            val bb: ByteBuffer = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
            val sb: ShortBuffer = bb.asShortBuffer()
            val arr = ShortArray(sb.remaining())
            sb.get(arr)

            // Basic clipping safeguard (optional)
            // for (i in arr.indices) arr[i] = arr[i].coerceIn(Short.MIN_VALUE, Short.MAX_VALUE)

            // If queue is too full, drop the oldest to keep latency low
            if (playbackQueue.remainingCapacity() == 0) {
                playbackQueue.poll()
            }
            playbackQueue.offer(arr)
        } catch (t: Throwable) {
            Log.w(logTag, "Audio decode error: ${t.message}")
        }
    }

    private fun sendJson(map: Map<String, Any>) {
        try {
            val obj = JSONObject()
            for ((k, v) in map) obj.put(k, v)
            webSocket?.send(obj.toString())
        } catch (_: Throwable) {}
    }

    override fun onDestroy() {
        super.onDestroy()
        stopSelfSafely()
    }
}
