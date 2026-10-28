package com.mitsuyoshi.bandnow;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;

/** 今の1つをスマホの通知に出す。Mi Fitness がこれをバンドへ転送する */
final class Notifier {
    private static final String CHANNEL = "now";
    private static final int ID = 1;

    static void show(Context c) {
        String text = Store.text(c);
        if (text.isEmpty()) return;
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel(CHANNEL, "今やる1つ", NotificationManager.IMPORTANCE_DEFAULT));
        PendingIntent open = PendingIntent.getActivity(c, 0, new Intent(c, MainActivity.class), PendingIntent.FLAG_IMMUTABLE);
        Notification n = new Notification.Builder(c, CHANNEL)
                .setSmallIcon(R.drawable.ic_launcher)
                .setContentTitle("今やる1つ")
                .setContentText(text)
                .setContentIntent(open)
                .setOnlyAlertOnce(false)
                .build();
        nm.notify(ID, n);
    }
}
