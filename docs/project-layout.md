# 曲フォルダの構成

1曲につき1フォルダを作ります。`utavideo new <パス>` は、渡したパスに次の構成で作成します。

```
20260915-song/            # フォルダ名は自分で決める（この例は日付 ＋ slug）
├── utavideo.toml        # 曲の情報と画面の構成
├── README.md            # 作業のチェックリストとメモ
├── src/                 # 動画の材料（自分で用意するもの）
│   ├── lyrics.ass       # 歌詞・コメント（Aegisub で編集）
│   ├── thumbnail.ass    # サムネイルの文字（Aegisub で編集。サイズ違いは thumbnail-square.ass など）
│   ├── vertical.ass     # 縦型のショートの歌詞（utavideo vertical-ass で作り、Aegisub で編集）
│   ├── mix/             # 音源
│   ├── bg/              # 背景の画像 / GIF / 動画
│   ├── avatar/          # アバターなどの動画素材
│   └── ref/             # 参考資料（原曲の動画など。書き出しには使わない）
├── build/               # utavideo が作るもの。丸ごと消してよい
│   ├── main.mp4
│   ├── overlay.mov
│   ├── preview/
│   │   ├── bg.mp4
│   │   └── vertical-bg.mp4  # utavideo preview-bg --vertical（縦用 .ass の下敷き）
│   ├── title.txt        # utavideo description
│   ├── description.txt
│   ├── thumbnail/       # utavideo thumbnail
│   │   ├── main.png     # [[thumbnails]] の name ごと
│   │   └── bg/main.png  # --bg-only（Aegisub の下敷き）
│   ├── shorts/          # utavideo shorts
│   │   ├── chorus.mp4   # [[shorts]] の name ごと
│   │   └── wide/chorus.mp4  # wide = true の 16:9 版
│   ├── inst/            # utavideo inst（歌唱練習用のカラオケ動画）
│   │   └── key-1.mp4    # --keys のキーごと
│   ├── announce.txt     # utavideo announce
│   └── .work/           # 書き出しに使った中間ファイル（描画に使った .ass など）、入力の記録（main-inputs.json・shorts-<name>-inputs.json・thumbnail-<name>-inputs.json）、release の一致の記録（release-match.json）
├── release/             # 公開した動画（概要欄を残すなら自分でコピー）。消さない
└── share/               # 人とやり取りしたファイル
    └── YYYYMMDD-相手/
```

## どこに置くか

| ファイルの性質 | 置き場所 |
|---|---|
| utavideo で作り直せる | `build/` |
| 公開した・公開する完成品 | `release/` |
| 人に送った・人から受け取った | `share/YYYYMMDD-相手/` |
| 動画の材料で、作り直せない | `src/` |
| 参考にするだけで、動画には使わない | `src/ref/` |

utavideo が読むのは `utavideo.toml` で指定したファイルだけなので、`src/` の中の細かい分け方は自由に変えてかまいません。

## 名前の付け方

ファイル名には曲名ではなく、`utavideo.toml` の `song.slug`（曲名の短い形）を使います。曲名を後から直してもファイル名が変わらず、日本語を避けたいときも曲名はそのままにできます。

| もの | 名前 | 例 |
|---|---|---|
| フォルダ | 自由（`utavideo new` に渡したパスのまま） | `20260915-song/` |
| 音源 | `<slug>-vX.Y.wav` | `src/mix/song-v1.2.wav` |
| 公開する動画 | `<slug>-vX.Y.N.mp4`（`utavideo release` が付ける） | `release/song-v1.2.0.mp4` |
| サムネイル | `build/thumbnail/<name>.png`（`name` は `[[thumbnails]]` に書く。使える文字は slug と同じ） | `build/thumbnail/square.png` |
| やり取り | `share/YYYYMMDD-相手/` | `share/20260913-to-mixer/`、`share/20260920-from-illustrator/` |

- slug は `new` / `init` が `utavideo.toml` に書きます。省略したときはフォルダ名（先頭に `YYYYMMDD` があれば除いたもの）です
- 自分で指定した slug は書き換えません。ファイル名に使えない名前（`\ / : * ? " < > |`・制御文字・先頭の `-`・末尾の空白と点・`CON` などの Windows の予約語・200 バイト超）はエラーです
- ASCII 以外の文字を含む slug は `check` が警告します（使えないわけではありません）
- `song.slug` が無い曲フォルダでは、曲名から slug を作ります（使えない文字と空白は `-`、`NUL.曲` のように予約語になる名前は `NUL-1.曲`）。`song.slug` より前に公開した `曲名 vX.Y[.N].mp4` も、同じ音源の動画として数えます
- 生成する名前の区切りは `-` です。空白は使いません（コマンドで打つときに引用が要るため）

- `vX.Y` は音源のバージョンです。ファイル名に含まれる `v` と、先頭に 0 の付かない整数2つ（`v1.2`・`V0.10`）で、複数あれば最後のものを使います。`v1`・`v1.2.3`・`v1.02`・`v1.2a` は対象外です。無いときは `utavideo release --version` で指定します
- `N` は、その音源で何本目かです。0 から始まり、`release/` にある同じ音源の動画の番号の最大値 + 1 が付きます。番号は音源のバージョンごとに別々に付きます
- 枝番を手で付けていた頃の `<名前> vX.Y.mp4` は、1本目（`vX.Y.0` にあたるもの）として数えます
- `build/main.mp4` は書き出すたびに上書きされます。残したい版は `release/` にコピーしてください

## 既存のフォルダで使い始める

`utavideo init <フォルダ>` を実行すると、足りないファイルとフォルダだけが追加されます。既存のファイルやフォルダは移動も上書きもされません。
古い構成のファイルを新しい構成に合わせたいときは、手で移動してから `utavideo.toml` のパスを直してください。
