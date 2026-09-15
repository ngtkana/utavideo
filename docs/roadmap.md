# ロードマップ

## 実装済み

背景（画像・GIF・動画）＋ 歌詞 ＋ 曲名表示 ＋ 音声の動画を書き出す。

- コマンド: `new` / `init` / `preview-bg` / `check` / `build` / `overlay` / `description` / `release`
- `check`: 設定・素材・スタイル・フォントの検査、行の重なり・`\pos`・はみ出しの警告
- 概要欄: `utavideo.toml` のクレジット・素材から概要欄とタイトルを作る（書式はユーザー設定、`release` で公開時の文章を残す）

## 予定

### 概要欄の文章（続き）

- 通し番号、前後の動画へのリンク、他サイト版へのリンク（他の曲フォルダの情報や投稿後に決まる URL が要る。手で書くと番号や URL を間違えやすい）
- よく使う素材をユーザー設定に登録し、名前で参照する

### アバターの合成

ブルーバック・グリーンバックで録画したアバター動画を背景に合成する。

- `[avatar]`
  - `file`：録画した動画
  - `key`：抜く色、`similarity`、`blend`、`despill`（ffmpeg の `colorkey` と `despill` を使う）
  - `scale`・`position`：大きさと、アンカー＋余白での位置
  - `offset`：録画と音源のズレ（秒）
- `sync = "auto"`：録画に入っている音声と音源の相互相関を取り、ズレを自動で求める。`check` で求めた値を表示する
- `[[layers]]`：背景の上に画像・GIF を複数重ねる（位置・大きさ・表示する区間）
- 背景をゆっくり拡大・移動させる（Ken Burns 効果）

### 縦型版・ショート動画

- `[variants.<名前>]`：`size` とスタイルの上書き（例: `styles.Lyrics = { fontsize = 56, alignment = 5 }`）
  - 同じ `lyrics.ass` から、PlayRes を書き換えた .ass を作る
  - `\pos` の座標は解像度の比で変換する
  - `build --variant vertical`、`preview-bg --variant vertical`
- `[[shorts]]`：`name`・`start`・`end`・`variant`。`build --shorts` で `build/shorts-<name>.mp4` を書き出す
- はみ出しの検査を派生版ごとに行う。`\pos` の行も、位置と配置から幅を概算して対象にする

### カラオケ用の音源動画

- 概要欄と同じ `[[credits]]` から、クレジットを並べた画面を自動で作る
- `utavideo inst --keys -1,-2,-3`：ffmpeg の `rubberband` でキーを変えた版を書き出す
- 音量をそろえる（`loudnorm`）

### その他

- `utavideo still --at 1:23`：サムネイル用の静止画（歌詞・曲名表示の有無を選べる）
