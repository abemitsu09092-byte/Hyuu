package com.mitsuyoshi.bandnow;

import android.content.Context;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** Jarvis（PC）から今の1つを取ってくる */
final class Fetch {
    interface Done { void result(boolean changed, String error); }

    static void run(Context c, Done done) {
        new Thread(() -> {
            HttpURLConnection http = null;
            try {
                http = (HttpURLConnection) new URL(Store.url(c)).openConnection();
                http.setConnectTimeout(8000);
                http.setReadTimeout(8000);
                if (http.getResponseCode() != 200) {
                    done.result(false, "Jarvisの返事が " + http.getResponseCode());
                    return;
                }
                InputStream in = http.getInputStream();
                ByteArrayOutputStream buf = new ByteArrayOutputStream();
                byte[] b = new byte[2048];
                int n;
                while ((n = in.read(b)) > 0 && buf.size() < 8192) buf.write(b, 0, n);
                done.result(Store.setText(c, new String(buf.toByteArray(), StandardCharsets.UTF_8)), null);
            } catch (Exception e) {
                done.result(false, "Jarvisにつながりません（PCとTailscaleを確認）：" + e.getMessage());
            } finally {
                if (http != null) http.disconnect();
            }
        }).start();
    }
}
