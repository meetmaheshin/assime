package com.aarth.app;

import android.app.Activity;
import android.app.KeyguardManager;
import android.app.NotificationManager;
import android.content.Context;
import android.content.Intent;
import android.media.AudioAttributes;
import android.media.MediaPlayer;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.os.VibratorManager;
import android.view.WindowManager;
import android.widget.TextView;

/** Full-screen "AARTH is calling" screen shown over the lock screen. Rings +
 *  vibrates until Open (→ chat) or Decline. */
public class CallActivity extends Activity {

    private MediaPlayer player;
    private Vibrator vibrator;
    private int notifId = 0;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // Show over the lock screen and turn the screen on.
        if (Build.VERSION.SDK_INT >= 27) {
            setShowWhenLocked(true);
            setTurnScreenOn(true);
            KeyguardManager km = (KeyguardManager) getSystemService(Context.KEYGUARD_SERVICE);
            if (km != null) km.requestDismissKeyguard(this, null);
        }
        getWindow().addFlags(
            WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON
            | WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
            | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
            | WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD);

        setContentView(R.layout.activity_call);

        Intent i = getIntent();
        String body = i != null ? i.getStringExtra("body") : null;
        notifId = i != null ? i.getIntExtra("notifId", 0) : 0;
        if (body != null && body.length() > 0) {
            ((TextView) findViewById(R.id.callBody)).setText(body);
        }

        findViewById(R.id.btnAnswer).setOnClickListener(v -> answer());
        findViewById(R.id.btnDecline).setOnClickListener(v -> dismiss());

        startRinging();
    }

    private void startRinging() {
        try {
            player = MediaPlayer.create(this, R.raw.aarth_ring);
            if (player != null) {
                player.setLooping(true);
                player.setAudioAttributes(new AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build());
                player.start();
            }
        } catch (Exception ignored) {}
        try {
            if (Build.VERSION.SDK_INT >= 31) {
                VibratorManager vm = (VibratorManager) getSystemService(Context.VIBRATOR_MANAGER_SERVICE);
                vibrator = vm != null ? vm.getDefaultVibrator() : null;
            } else {
                vibrator = (Vibrator) getSystemService(Context.VIBRATOR_SERVICE);
            }
            if (vibrator != null) {
                long[] pattern = {0, 700, 800};
                vibrator.vibrate(VibrationEffect.createWaveform(pattern, 0));
            }
        } catch (Exception ignored) {}
    }

    private void stopRinging() {
        try { if (player != null) { player.stop(); player.release(); player = null; } } catch (Exception ignored) {}
        try { if (vibrator != null) { vibrator.cancel(); vibrator = null; } } catch (Exception ignored) {}
        try {
            NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm != null && notifId != 0) nm.cancel(notifId);
        } catch (Exception ignored) {}
    }

    private void answer() {
        stopRinging();
        try {
            Intent open = new Intent(Intent.ACTION_VIEW, Uri.parse("aarth://action/open"));
            open.setPackage(getPackageName());
            open.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
            startActivity(open);
        } catch (Exception ignored) {}
        finish();
    }

    private void dismiss() {
        stopRinging();
        finish();
    }

    @Override
    protected void onDestroy() {
        stopRinging();
        super.onDestroy();
    }
}
