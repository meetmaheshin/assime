package com.aarth.app;

import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.media.AudioAttributes;
import android.net.Uri;
import android.os.Build;

import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;

/** Fires at the scheduled time and posts a full-screen-intent notification that
 *  launches CallActivity (rings over the lock screen). If full-screen isn't
 *  allowed, falls back to a ringing heads-up notification. Reschedules daily. */
public class CallReceiver extends BroadcastReceiver {

    static final String CHANNEL_FS = "aarth-fs-call-v1";     // silent; CallActivity rings
    static final String CHANNEL_RING = "aarth-ring-v2";       // rings itself (fallback)

    @Override
    public void onReceive(Context ctx, Intent intent) {
        int notifId = intent.getIntExtra("notifId", 1);
        String title = intent.getStringExtra("title");
        String body = intent.getStringExtra("body");
        long repeat = intent.getLongExtra("repeatMillis", 0L);
        if (title == null) title = "AARTH";
        if (body == null) body = "";

        ensureChannels(ctx);
        boolean fs = canFullScreen(ctx);

        Intent full = new Intent(ctx, CallActivity.class);
        full.putExtra("body", body);
        full.putExtra("notifId", notifId);
        full.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent fsPi = PendingIntent.getActivity(ctx, notifId, full,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        NotificationCompat.Builder b = new NotificationCompat.Builder(
                ctx, fs ? CHANNEL_FS : CHANNEL_RING)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(title)
            .setContentText(body)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_CALL)
            .setContentIntent(fsPi)
            .setAutoCancel(true);
        if (fs) b.setFullScreenIntent(fsPi, true);
        try {
            NotificationManagerCompat.from(ctx).notify(notifId, b.build());
        } catch (SecurityException ignored) {}

        if (repeat > 0) {
            schedule(ctx, notifId, System.currentTimeMillis() + repeat, title, body, repeat);
        }
    }

    static boolean canFullScreen(Context ctx) {
        if (Build.VERSION.SDK_INT >= 34) {
            NotificationManager nm = (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
            return nm != null && nm.canUseFullScreenIntent();
        }
        return true;
    }

    static void ensureChannels(Context ctx) {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationManager nm = (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm == null) return;
        NotificationChannel fs = new NotificationChannel(
            CHANNEL_FS, "AARTH calls", NotificationManager.IMPORTANCE_HIGH);
        fs.setDescription("Full-screen call-style reminders");
        fs.setSound(null, null);              // CallActivity plays the ring
        fs.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
        nm.createNotificationChannel(fs);

        NotificationChannel ring = new NotificationChannel(
            CHANNEL_RING, "AARTH ringing reminders", NotificationManager.IMPORTANCE_HIGH);
        ring.setDescription("Ringing reminders when full-screen isn't allowed");
        Uri snd = Uri.parse("android.resource://" + ctx.getPackageName() + "/" + R.raw.aarth_ring);
        ring.setSound(snd, new AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE)
            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build());
        ring.enableVibration(true);
        ring.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
        nm.createNotificationChannel(ring);
    }

    /** Schedule a call at an absolute epoch-ms time. repeat=0 for one-shot. */
    public static void schedule(Context ctx, int id, long at, String title, String body, long repeat) {
        Intent i = new Intent(ctx, CallReceiver.class);
        i.putExtra("notifId", id);
        i.putExtra("title", title);
        i.putExtra("body", body);
        i.putExtra("repeatMillis", repeat);
        PendingIntent pi = PendingIntent.getBroadcast(ctx, id, i,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        AlarmManager am = (AlarmManager) ctx.getSystemService(Context.ALARM_SERVICE);
        if (am == null) return;
        try {
            am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi);
        } catch (SecurityException e) {
            am.set(AlarmManager.RTC_WAKEUP, at, pi);
        }
    }

    public static void cancel(Context ctx, int id) {
        Intent i = new Intent(ctx, CallReceiver.class);
        PendingIntent pi = PendingIntent.getBroadcast(ctx, id, i,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        AlarmManager am = (AlarmManager) ctx.getSystemService(Context.ALARM_SERVICE);
        if (am != null) am.cancel(pi);
    }
}
