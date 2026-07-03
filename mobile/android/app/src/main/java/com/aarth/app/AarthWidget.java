package com.aarth.app;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.widget.RemoteViews;

/**
 * Home-screen widget: quick "＋ Task" and "🎤 Speak" buttons that deep-link into
 * the app (aarth://action/...). The web layer reads the action and opens chat /
 * starts the mic.
 */
public class AarthWidget extends AppWidgetProvider {

    @Override
    public void onUpdate(Context ctx, AppWidgetManager mgr, int[] ids) {
        for (int id : ids) {
            RemoteViews v = new RemoteViews(ctx.getPackageName(), R.layout.widget_aarth);
            v.setOnClickPendingIntent(R.id.widgetRoot, pi(ctx, "aarth://action/open", 1));
            v.setOnClickPendingIntent(R.id.widgetAdd, pi(ctx, "aarth://action/add", 2));
            v.setOnClickPendingIntent(R.id.widgetVoice, pi(ctx, "aarth://action/voice", 3));
            mgr.updateAppWidget(id, v);
        }
    }

    private PendingIntent pi(Context ctx, String uri, int req) {
        Intent i = new Intent(Intent.ACTION_VIEW, Uri.parse(uri));
        i.setPackage(ctx.getPackageName());
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        return PendingIntent.getActivity(
            ctx, req, i,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }
}
