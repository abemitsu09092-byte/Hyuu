package com.mitsuyoshi.bandnow;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;

/** 15分ごとにJarvisを見に行き、変わっていたらバンドへ送る */
public class FetchJob extends JobService {
    private static final int ID = 1;

    static void schedule(Context c, boolean on) {
        JobScheduler js = c.getSystemService(JobScheduler.class);
        if (!on) { js.cancel(ID); return; }
        js.schedule(new JobInfo.Builder(ID, new ComponentName(c, FetchJob.class))
                .setPeriodic(15 * 60 * 1000L)
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPersisted(true)
                .build());
    }

    @Override
    public boolean onStartJob(JobParameters params) {
        Fetch.run(this, (changed, error) -> {
            if (changed) Bridge.get(this).send();
            else Bridge.get(this).ready(() -> { });   // バンドから呼ばれたら答えられるように待ち受けだけ
            // 送信の返事を少し待ってから終える
            new android.os.Handler(android.os.Looper.getMainLooper())
                    .postDelayed(() -> jobFinished(params, false), 10_000);
        });
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) { return true; }
}
