package com.mitsuyoshi.bandnow;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.text.InputType;
import android.util.TypedValue;
import android.view.View;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

/** スマホ側の画面：今の1つを見る・手で送る・Jarvisから取る・自動のオン/オフ */
public class MainActivity extends Activity {
    private TextView now;
    private TextView log;
    private EditText input;
    private EditText url;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(16);
        box.setPadding(pad, pad, pad, pad);

        box.addView(label("バンドに出ている1つ"));
        now = new TextView(this);
        now.setTextSize(TypedValue.COMPLEX_UNIT_SP, 24);
        box.addView(now);

        box.addView(label("手で決めて送る"));
        input = new EditText(this);
        input.setHint("例：JELP課題の1問目だけ開く");
        box.addView(input);
        box.addView(button("バンドに送る", v -> {
            Store.setText(this, input.getText().toString());
            input.setText("");
            show();
            Bridge.get(this).send();
        }));

        box.addView(label("Jarvisから取る"));
        url = new EditText(this);
        url.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        url.setText(Store.url(this));
        box.addView(url);
        box.addView(button("今すぐJarvisから取る", v -> {
            Store.setUrl(this, url.getText().toString());
            line("Jarvisを見に行っています…");
            Fetch.run(this, (changed, error) -> runOnUiThread(() -> {
                if (error != null) { line(error); return; }
                show();
                if (changed) Bridge.get(this).send();
                else line("Jarvisの1つは前と同じでした");
            }));
        }));

        CheckBox auto = new CheckBox(this);
        auto.setText("15分ごとに自動でJarvisを見る");
        auto.setChecked(Store.auto(this));
        auto.setOnCheckedChangeListener((b, on) -> {
            Store.setUrl(this, url.getText().toString());
            Store.setAuto(this, on);
            FetchJob.schedule(this, on);
            line(on ? "自動をオンにしました" : "自動をオフにしました");
        });
        box.addView(auto);

        box.addView(button("バンドでアプリを開く", v -> Bridge.get(this).openOnBand()));

        box.addView(label("ようす"));
        log = new TextView(this);
        log.setTextColor(Color.GRAY);
        box.addView(log);

        ScrollView scroll = new ScrollView(this);
        scroll.addView(box);
        setContentView(scroll);

        Bridge.get(this).setLog(this::line);
        if (android.os.Build.VERSION.SDK_INT >= 33
                && checkSelfPermission("android.permission.POST_NOTIFICATIONS") != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, 1);
        }
        takeShared(getIntent());
        show();
        Bridge.get(this).ready(() -> { });
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        takeShared(intent);
    }

    @Override
    protected void onDestroy() {
        Bridge.get(this).setLog(null);
        super.onDestroy();
    }

    /** 他のアプリの「共有」で届いた文字をそのまま送る */
    private void takeShared(Intent intent) {
        if (intent == null || !Intent.ACTION_SEND.equals(intent.getAction())) return;
        if (Store.setText(this, intent.getStringExtra(Intent.EXTRA_TEXT))) {
            show();
            Bridge.get(this).send();
        }
    }

    private void show() {
        String t = Store.text(this);
        now.setText(t.isEmpty() ? "（まだありません）" : t + "\n" + Store.at(this) + " 更新");
    }

    private void line(String s) {
        CharSequence old = log.getText();
        log.setText(s + (old.length() == 0 ? "" : "\n" + old));
    }

    private TextView label(String s) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextColor(0xFF8AB4F8);
        t.setPadding(0, dp(20), 0, dp(4));
        return t;
    }

    private Button button(String s, View.OnClickListener l) {
        Button b = new Button(this);
        b.setText(s);
        b.setOnClickListener(l);
        return b;
    }

    private int dp(int v) {
        return (int) (v * getResources().getDisplayMetrics().density);
    }
}
