package com.example.syncspeaker

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.example.syncspeaker.databinding.ActivityMainBinding

class MainActivity : ComponentActivity() {
    private lateinit var binding: ActivityMainBinding

    private val requestNotificationPermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            // no-op; foreground service will still run, but notifications may be hidden if not granted
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        maybeRequestNotificationPermission()
        maybeRequestIgnoreBatteryOptimizations()

        binding.hostInput.setText(defaultHost())

        binding.startButton.setOnClickListener {
            val host = binding.hostInput.text.toString().trim()
            val port = binding.portInput.text.toString().trim().toIntOrNull() ?: 8765
            val intent = Intent(this, SyncAudioService::class.java).apply {
                action = SyncAudioService.ACTION_START
                putExtra(SyncAudioService.EXTRA_HOST, host)
                putExtra(SyncAudioService.EXTRA_PORT, port)
            }
            startForegroundService(intent)
            binding.statusText.text = "Status: Starting..."
        }

        binding.stopButton.setOnClickListener {
            val intent = Intent(this, SyncAudioService::class.java).apply {
                action = SyncAudioService.ACTION_STOP
            }
            startService(intent)
            binding.statusText.text = "Status: Stopping..."
        }
    }

    private fun defaultHost(): String {
        // Emulator default
        return "10.0.2.2"
    }

    private fun maybeRequestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33) {
            requestNotificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    private fun maybeRequestIgnoreBatteryOptimizations() {
        try {
            val pm = getSystemService(POWER_SERVICE) as PowerManager
            val pkg = packageName
            val ignoring = pm.isIgnoringBatteryOptimizations(pkg)
            if (!ignoring) {
                val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
                    data = Uri.parse("package:$pkg")
                }
                startActivity(intent)
            }
        } catch (_: Throwable) {
        }
    }
}
