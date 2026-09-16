# ロードマップ

## 実装済み

背景（画像・GIF・動画）＋ 歌詞 ＋ 曲名表示 ＋ 音声の動画を書き出す。

- コマンド: `new` / `init` / `preview-bg` / `check` / `build` / `overlay` / `thumbnail` / `description` / `release`
- `check`: 設定・素材・スタイル・フォントの検査、行の重なり・`\pos`・はみ出しの警告
- 概要欄: `utavideo.toml` のクレジット・素材から概要欄とタイトルを作る（書式はユーザー設定）

- サムネイル: 背景のフレーム（`at`）にサムネイル用の .ass を描いた PNG。サイズ違いは `[[thumbnails]]` を並べる。背景の残す位置（`focus`）は動画にも効く

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
- `[[shorts]]`：`name`・`start`・`end`・`variant`（時刻の書式は `[[thumbnails]]` の `at` と同じ）。`build --shorts` で `build/shorts-<name>.mp4` を書き出す
- はみ出しの検査を派生版ごとに行う。`\pos` の行も、位置と配置から幅を概算して対象にする

### カラオケ用の音源動画

- 概要欄と同じ `[[credits]]` から、クレジットを並べた画面を自動で作る
- `utavideo inst --keys -1,-2,-3`：ffmpeg の `rubberband` でキーを変えた版を書き出す
- 音量をそろえる（`loudnorm`）

### サムネイル（続き）

- `[[layers]]` で、背景の上に画像を重ねる（ass の `[Graphics]` は libass が表示しないので、ffmpeg の `overlay` を使う）
- 同じサイズで何枚か書き出して見比べる
- サムネイルごとに別の背景を使う（例: 動画は小さい GIF、サムネイルは高解像度の静止画）
- `release` へのコピー
- 投稿先の容量の上限に収まらない例が出たら、JPEG での書き出しか容量の警告を足す
