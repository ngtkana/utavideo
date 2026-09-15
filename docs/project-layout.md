# 曲フォルダの構成

1曲につき1フォルダを作ります。`utavideo new` は次の構成で作成します。

```
YYYYMMDD 曲名/
├── utavideo.toml        # 曲の情報と画面の構成
├── README.md            # 作業のチェックリストとメモ
├── src/                 # 動画の材料（自分で用意するもの）
│   ├── lyrics.ass       # 歌詞・コメント（Aegisub で編集）
│   ├── mix/             # 音源
│   ├── bg/              # 背景の画像 / GIF / 動画
│   ├── avatar/          # アバターなどの動画素材
│   └── ref/             # 参考資料（原曲の動画など。書き出しには使わない）
├── build/               # utavideo が作るもの。丸ごと消してよい
│   ├── main.mp4
│   ├── overlay.mov
│   ├── preview/bg.mp4
│   ├── title.txt        # utavideo description
│   ├── description.txt
│   └── .work/           # 書き出しに使った中間ファイル
├── release/             # 公開した動画と概要欄。消さない
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

| もの | 名前 | 例 |
|---|---|---|
| フォルダ | `YYYYMMDD 曲名`（`utavideo new` が付ける） | `20260915 曲名/` |
| 音源 | `曲名 vX.Y.wav` | `src/mix/曲名 v1.2.wav` |
| 公開する動画 | `曲名 vX.Y.mp4`（`utavideo release` が付ける） | `release/曲名 v1.2.mp4` |
| 公開したときの概要欄 | `曲名 vX.Y.txt`（`[description]` がある曲で `utavideo release` が書く） | `release/曲名 v1.2.txt` |
| やり取り | `share/YYYYMMDD-相手/` | `share/20260913-to-mixer/`、`share/20260920-from-illustrator/` |

- バージョンは、音源のファイル名に含まれる `v` と数字（`v1`・`v1.2`・`V1.2.3`）です。複数あれば最後のものを使い、`v1.2a` のように英数字が続くものは対象外です。無いときは `utavideo release --version` で指定します
- 公開する動画のバージョンは、音源のバージョンにそろえます。歌詞や見た目だけを直したときは `utavideo release --version v1.2.1` のように枝番を付けます
- `build/main.mp4` は書き出すたびに上書きされます。残したい版は `release/` にコピーしてください

## 既存のフォルダで使い始める

`utavideo init <フォルダ>` を実行すると、足りないファイルとフォルダだけが追加されます。既存のファイルやフォルダは移動も上書きもされません。
古い構成のファイルを新しい構成に合わせたいときは、手で移動してから `utavideo.toml` のパスを直してください。
