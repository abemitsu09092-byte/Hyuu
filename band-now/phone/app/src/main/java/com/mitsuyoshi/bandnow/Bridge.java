package com.mitsuyoshi.bandnow;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;

import com.xiaomi.xms.wearable.Wearable;
import com.xiaomi.xms.wearable.auth.AuthApi;
import com.xiaomi.xms.wearable.auth.Permission;
import com.xiaomi.xms.wearable.message.MessageApi;
import com.xiaomi.xms.wearable.message.OnMessageReceivedListener;
import com.xiaomi.xms.wearable.node.Node;
import com.xiaomi.xms.wearable.node.NodeApi;

import java.nio.charset.StandardCharsets;
import java.util.List;

/** Mi Fitness を通してバンドの「今やる1つ」アプリと話す */
final class Bridge {
    interface Log { void line(String s); }

    private static Bridge instance;

    static synchronized Bridge get(Context c) {
        if (instance == null) instance = new Bridge(c.getApplicationContext());
        return instance;
    }

    private final Context ctx;
    private final NodeApi nodeApi;
    private final AuthApi authApi;
    private final MessageApi messageApi;
    private final Handler main = new Handler(Looper.getMainLooper());
    private String nodeId;
    private boolean listening;
    private Log log = s -> { };

    private Bridge(Context ctx) {
        this.ctx = ctx;
        nodeApi = Wearable.getNodeApi(ctx);
        authApi = Wearable.getAuthApi(ctx);
        messageApi = Wearable.getMessageApi(ctx);
    }

    void setLog(Log l) { log = l == null ? s -> { } : l; }

    private void say(String s) { main.post(() -> log.line(s)); }

    /** バンドを見つけて、許可をもらって、バンドからの声を聞く準備をしてから then を実行 */
    void ready(Runnable then) {
        if (nodeId != null && listening) { then.run(); return; }
        nodeApi.getConnectedNodes()
                .addOnSuccessListener((List<Node> nodes) -> {
                    if (nodes == null || nodes.isEmpty()) {
                        say("バンドが見つかりません。Mi Fitnessでバンドがつながっているか見てください");
                        return;
                    }
                    nodeId = nodes.get(0).id;
                    askPermission(then);
                })
                .addOnFailureListener(e -> say("Mi Fitnessにつながりません：" + e.getMessage()));
    }

    private void askPermission(Runnable then) {
        authApi.checkPermission(nodeId, Permission.DEVICE_MANAGER)
                .addOnSuccessListener((Boolean ok) -> {
                    if (Boolean.TRUE.equals(ok)) { listen(then); return; }
                    authApi.requestPermission(nodeId, Permission.DEVICE_MANAGER, Permission.NOTIFY)
                            .addOnSuccessListener(p -> listen(then))
                            .addOnFailureListener(e -> say("Mi Fitnessの許可がもらえませんでした：" + e.getMessage()));
                })
                .addOnFailureListener(e -> say("許可の確認に失敗：" + e.getMessage()));
    }

    private void listen(Runnable then) {
        if (listening) { then.run(); return; }
        OnMessageReceivedListener onBand = (String from, byte[] msg) -> {
            // バンドから何か届いたら「今の1つちょうだい」の合図とみなして送り返す
            say("バンドから呼ばれました");
            send();
        };
        messageApi.addListener(nodeId, onBand)
                .addOnSuccessListener(v -> { listening = true; say("バンドとつながりました"); then.run(); })
                .addOnFailureListener(e -> say("バンドの声を聞く準備に失敗：" + e.getMessage()));
    }

    /** 今の1つをバンドへ送る */
    void send() {
        if (Store.text(ctx).isEmpty()) { say("まだ送る1つがありません"); return; }
        Notifier.show(ctx);
        say("通知に出しました（Mi Fitnessがバンドへ転送します）：" + Store.text(ctx));
        ready(() -> messageApi.sendMessage(nodeId, Store.json(ctx).getBytes(StandardCharsets.UTF_8))
                .addOnSuccessListener(v -> say("バンドのアプリにも送りました"))
                .addOnFailureListener(e -> { }));
    }

    /** バンドの「今やる1つ」アプリを開く */
    void openOnBand() {
        ready(() -> nodeApi.launchWearApp(nodeId, "/pages/index")
                .addOnSuccessListener(v -> say("バンドでアプリを開きました"))
                .addOnFailureListener(e -> say("バンドで開けませんでした：" + e.getMessage())));
    }
}
