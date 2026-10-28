# band-now（今やる1つ）

Xiaomi Smart Band 9 Pro（Vela OS、画面 336×480）に「今やる1つ」を1行だけ出す自作アプリ。

## 段階
1. 【いまここ】「Hello」だけのアプリをバンドに入れる
2. スマホから文字を送ってバンドの表示を変える（interconnect。9 Pro は公式表に無く実機確認が必要）
3. Jarvis の締め切り箱とつなぐ

## 作り方（PC・クラウドどちらでも）
```
npm install
npx aiot build        # dist/com.mitsuyoshi.bandnow.debug.0.1.0.rpk ができる
```
署名は `sign/debug/private.pem` と `certificate.pem`（Git には入れない。段階2でスマホ側アプリと同じ鍵が必要になるので無くさない）。

## バンドへの入れ方（公式アプリの開発者メニュー）
1. スマホの Mi Fitness（小米运动健康）→ プロフィール → 「について / About」を何度も連打
2. 開発者メニュー（Debug）が出たら「サードパーティアプリ / 第三方应用」→ パッケージ名 `com.mitsuyoshi.bandnow` → rpk ファイルを選ぶ
3. 出ないとき（グローバル版で隠れている場合）は AstroBox などの有志ツールを検討

参考: VoidTerminal-Vela（gitea.com/sisheng-mirror-4/VoidTerminal-Vela）、xiaomi-band-development（github.com/mhdbaselar/xiaomi-band-development）、Vela 公式 https://iot.mi.com/vela/quickapp
