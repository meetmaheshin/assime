package com.aarth.app;

import android.app.NotificationManager;
import android.content.Context;
import android.os.Build;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/** JS bridge to schedule full-screen "call" reminders (AlarmManager -> CallReceiver). */
@CapacitorPlugin(name = "CallReminder")
public class CallPlugin extends Plugin {

    @PluginMethod
    public void schedule(PluginCall call) {
        int id = call.getInt("id", 0);
        Double at = call.getDouble("at");
        Double rep = call.getDouble("repeatMillis");
        String title = call.getString("title", "AARTH");
        String body = call.getString("body", "");
        long atMs = at != null ? at.longValue() : 0L;
        long repeat = rep != null ? rep.longValue() : 0L;
        if (atMs <= 0) { call.reject("bad time"); return; }
        CallReceiver.schedule(getContext(), id, atMs, title, body, repeat);
        call.resolve();
    }

    @PluginMethod
    public void cancel(PluginCall call) {
        int id = call.getInt("id", 0);
        CallReceiver.cancel(getContext(), id);
        call.resolve();
    }

    @PluginMethod
    public void canUseFullScreen(PluginCall call) {
        boolean ok = true;
        if (Build.VERSION.SDK_INT >= 34) {
            NotificationManager nm = (NotificationManager) getContext()
                .getSystemService(Context.NOTIFICATION_SERVICE);
            ok = nm != null && nm.canUseFullScreenIntent();
        }
        JSObject r = new JSObject();
        r.put("granted", ok);
        call.resolve(r);
    }
}
