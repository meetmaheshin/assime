package com.aarth.app;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;

import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;

import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;

import java.util.Map;

/** Receives FCM even when the app is CLOSED or backgrounded. The server sends
 *  DATA-only messages (so this always runs); for {@code alert=call} we launch the
 *  full-screen ringing CallActivity over the lock screen — the same experience as
 *  a local alarm — instead of a silent tray entry. Everything else posts a normal
 *  heads-up notification that opens the app. */
public class AarthMessagingService extends FirebaseMessagingService {

    static final String CHANNEL_FCM = "aarth-fcm";

    @Override
    public void onMessageReceived(RemoteMessage msg) {
        Map<String, String> d = msg.getData();
        String title = d.get("title");
        String body = d.get("body");
        String alert = d.get("alert");
        // Tolerate a notification-style payload too, just in case.
        if ((title == null || title.isEmpty()) && msg.getNotification() != null)
            title = msg.getNotification().getTitle();
        if ((body == null || body.isEmpty()) && msg.getNotification() != null)
            body = msg.getNotification().getBody();
        if (title == null || title.isEmpty()) title = "AARTH";
        if (body == null) body = "";

        int notifId = (int) (System.currentTimeMillis() % 100000);
        try {
            String idStr = d.get("notifId");
            if (idStr != null) notifId = Integer.parseInt(idStr);
        } catch (Exception ignored) {}

        if ("call".equals(alert)) {
            ringCall(notifId, title, body);
        } else {
            postNormal(notifId, title, body);
        }
    }

    /** Full-screen, ringing, over-the-lock-screen — even if the app was killed. */
    private void ringCall(int notifId, String title, String body) {
        CallReceiver.ensureChannels(this);           // reuse the call channels
        boolean fs = CallReceiver.canFullScreen(this);

        Intent full = new Intent(this, CallActivity.class);
        full.putExtra("body", body.isEmpty() ? title : body);
        full.putExtra("notifId", notifId);
        full.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        PendingIntent pi = PendingIntent.getActivity(this, notifId, full,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        NotificationCompat.Builder b = new NotificationCompat.Builder(
                this, fs ? CallReceiver.CHANNEL_FS : CallReceiver.CHANNEL_RING)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(title)
            .setContentText(body)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_CALL)
            .setContentIntent(pi)
            .setAutoCancel(true);
        if (fs) b.setFullScreenIntent(pi, true);
        try {
            NotificationManagerCompat.from(this).notify(notifId, b.build());
        } catch (SecurityException ignored) {}
    }

    /** Ordinary heads-up notification that opens the app when tapped. */
    private void postNormal(int notifId, String title, String body) {
        ensureFcmChannel();
        Intent open = new Intent(Intent.ACTION_VIEW, Uri.parse("aarth://action/open"));
        open.setPackage(getPackageName());
        open.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent pi = PendingIntent.getActivity(this, notifId, open,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        NotificationCompat.Builder b = new NotificationCompat.Builder(this, CHANNEL_FCM)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(title)
            .setContentText(body)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setDefaults(NotificationCompat.DEFAULT_ALL)
            .setContentIntent(pi)
            .setAutoCancel(true);
        try {
            NotificationManagerCompat.from(this).notify(notifId, b.build());
        } catch (SecurityException ignored) {}
    }

    private void ensureFcmChannel() {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm == null || nm.getNotificationChannel(CHANNEL_FCM) != null) return;
        NotificationChannel ch = new NotificationChannel(
            CHANNEL_FCM, "AARTH updates", NotificationManager.IMPORTANCE_HIGH);
        ch.setDescription("Task updates, delegations and reminders");
        ch.enableVibration(true);
        nm.createNotificationChannel(ch);
    }
}
