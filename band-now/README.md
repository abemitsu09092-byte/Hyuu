# band-now（今やる1つ）

Xiaomi Smart Band 9 Pro に「今やる1つ」を1行だけ出す仕組み。3つの部品でできている。

```
Jarvis（PC） ──Tailscale──▶ スマホの中継アプリ ──Mi Fitness経由──▶ バンドのアプリ
締め切り箱/今やる1つ.md      15分ごと or 手で送る          開くと最新を表示・タップで取り直し
```

| 部品 | 場所 | 中身 |
|---|---|---|
| バンドのアプリ | `src/` | Vela クイックアプリ。受け取った1つを保存して表示。通信できなくても落ちない |
| スマホの中継アプリ | `phone/` | Android（Java）。手で入力／他アプリの「共有」／Jarvis の URL から取って、バンドへ送る |
| PCの窓口 | `pc/` | `今やる1つ.md` の1行目を `http://cagent09:8765/now.txt` で返すだけ。Tailscale からのみ |

## 作り方
- バンド: `npm install && npx aiot build` → `dist/*.rpk`
- スマホ: `phone/app/libs/` に小米の `xms-wearable-lib_1.4_release.aar` を置き（[公式デモ](https://cdn.cnbj3-fusion.fds.api.mi-img.com/quickapp-vela/interconnect_dev_test_demo.zip)に同梱、Git には入れない）、`cd phone && gradle assembleRelease`
- 署名: `sign/`（Git には入れない）。**バンドとスマホは同じ鍵・同じパッケージ名 `com.mitsuyoshi.bandnow` でないと通信できない**

## 入れ方
1. バンド: Notify for Xiaomi →「Device」→「Third party app」→ rpk
2. スマホ: apk をそのまま開いてインストール（提供元不明アプリの許可が要る）。開くと Mi Fitness の許可が出るので許可
3. PC: `pc/setup-pc.ps1` の中身を PowerShell に貼る

## わかっていない所
- 9 Pro は小米の公式通信対応表に載っていない。グローバル版 Mi Fitness で通るかは実機で確認するしかない
- スマホのアプリは常駐しないので、バンドから「取り直し」を押しても、スマホ側がしばらく寝ていると返事が無いことがある（15分ごとの自動取得のときは起きている）
