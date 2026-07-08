package com.aarth.app;

import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;

/** Fires at the scheduled time and posts a full-screen-intent notification that
 *  launches CallActivity (rings over the lock screen). Reschedules daily if asked. */
public class CallReceiver extends BroadcastReceiver {

    static final String CHANNEL = "aarth-fs-call-v1";

    @Override
    public void onReceive(Context ctx, Intent intent) {
        int notifId = intent.getIntExtra("notifId", 1);
        String title = intent.getStringExtra("title");
        String body = intent.getStringExtra("body");
        long repeat = intent.getLongExtra("repeatMillis", 0L);
        if (title == null) title = "AARTH";
        if (body == null) body = "";

        ensureChannel(ctx);

        Intent full = new Intent(ctx, CallActivity.class);
        full.putExtra("body", body);
        full.putExtra("notifId", notifId);
        full.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent fsPi = PendingIntent.getActivity(ctx, notifId, full,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        Notification n = new NotificationCompat.Builder(ctx, CHANNEL)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(title)
            .setContentText(body)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_CALL)
            .setFullScreenIntent(fsPi, true)
            .setContentIntent(fsPi)
            .setAutoCancel(true)
            .build();
        try {
            NotificationManagerCompat.from(ctx).notify(notifId, n);
        } catch (SecurityException ignored) {}

        if (repeat > 0) {
            schedule(ctx, notifId, System.currentTimeMillis() + repeat, title, body, repeat);
        }
    }

    private static void ensureChannel(Context ctx) {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationManager nm = (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm == null) return;
            NotificationChannel ch = new NotificationChannel(
                CHANNEL, "AARTH calls", NotificationManager.IMPORTANCE_HIGH);
            ch.setDescription("Full-screen call-style reminders");
            ch.setSound(null, null);          // CallActivity plays the ring; keep the notif silent
            ch.enableVibration(false);
            ch.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
            nm.createNotificationChannel(ch);
        }
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
