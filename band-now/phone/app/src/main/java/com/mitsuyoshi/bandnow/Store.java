package com.mitsuyoshi.bandnow;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/** スマホに覚えておくもの：今の1つ・更新時刻・JarvisのURL・自動取得のオン/オフ */
final class Store {
    static final String DEFAULT_URL = "http://cagent09:8765/now.txt";
    static final int MAX_CHARS = 30;

    private static SharedPreferences prefs(Context c) {
        return c.getSharedPreferences("bandnow", Context.MODE_PRIVATE);
    }

    static String text(Context c) { return prefs(c).getString("text", ""); }
    static String at(Context c) { return prefs(c).getString("at", ""); }
    static String url(Context c) { return prefs(c).getString("url", DEFAULT_URL); }
    static boolean auto(Context c) { return prefs(c).getBoolean("auto", false); }
    static boolean stay(Context c) { return prefs(c).getBoolean("stay", false); }

    static void setUrl(Context c, String v) { prefs(c).edit().putString("url", v.trim()).apply(); }
    static void setAuto(Context c, boolean v) { prefs(c).edit().putBoolean("auto", v).apply(); }
    static void setStay(Context c, boolean v) { prefs(c).edit().putBoolean("stay", v).apply(); }

    /** 新しい1つを覚える。前と同じなら false を返す */
    static boolean setText(Context c, String raw) {
        String v = clean(raw);
        if (v.isEmpty() || v.equals(text(c))) return false;
        String now = new SimpleDateFormat("HH:mm", Locale.JAPAN).format(new Date());
        prefs(c).edit().putString("text", v).putString("at", now).apply();
        return true;
    }

    /** 最初の空でない行だけ使い、箇条書きの記号を落として短くする */
    static String clean(String raw) {
        if (raw == null) return "";
        raw = raw.replace("\uFEFF", "");
        for (String line : raw.split("\\r?\\n")) {
            String s = line.replaceFirst("^\\s*([-*+]\\s*(\\[[ xX]\\]\\s*)?|#+\\s*)", "").trim();
            if (s.isEmpty()) continue;
            return s.length() > MAX_CHARS ? s.substring(0, MAX_CHARS) : s;
        }
        return "";
    }

    static String json(Context c) {
        try {
            JSONObject o = new JSONObject();
            o.put("text", text(c));
            o.put("at", at(c));
            return o.toString();
        } catch (Exception e) {
            return "{}";
        }
    }
}
