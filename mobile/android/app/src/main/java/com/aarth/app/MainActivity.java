package com.aarth.app;

import android.Manifest;
import android.content.pm.PackageManager;
import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(CallPlugin.class);
        super.onCreate(savedInstanceState);
        // Ask for the mic up-front so the OS prompt appears and WebView voice
        // (getUserMedia) can be granted — otherwise there's no way to allow it.
        try {
            if (checkSelfPermission(Manifest.permission.RECORD_AUDIO)
                    != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 7001);
            }
        } catch (Exception ignored) {}
    }
}
