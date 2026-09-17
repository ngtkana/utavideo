# ロードマップ

## 実装済み

背景（画像・GIF・動画）＋ 歌詞 ＋ 曲名表示 ＋ 音声の動画を書き出す。

- コマンド: `new` / `init` / `preview-bg` / `check` / `build` / `overlay` / `thumbnail` / `description` / `release`
- `check`: 設定・素材・スタイル・フォントの検査、行の重なり・`\pos`・はみ出しの警告
- 概要欄: `utavideo.toml` のクレジット・素材から概要欄とタイトルを作る（書式はユーザー設定）

- サムネイル: 背景のフレーム（`at`）にサムネイル用の .ass を描いた PNG。サイズ違いは `[[thumbnails]]` を並べる。背景の残す位置（`focus`）は動画にも効く
- 縦型のショート（1段目）: `vertical-ass` で本編の .ass から縦用 .ass を作る（大きさ・座標の変換）。`check` で縦用 .ass を検査する。`LayoutResX`・`LayoutResY` の縦横比が PlayRes と違う .ass をエラーにする

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

### 縦型のショート（続き）

本編から区間を指定して、縦型の切り抜きショートを書き出す（issue #22）。

- `preview-bg --vertical`：Aegisub で開く縦の下敷き（`build/preview/vertical-bg.mp4`）
- 区間は縦用 .ass のコメント行（スタイル `Short`、本文がショートの名前）に置き、`[[shorts]]` の `name` とつなぐ。区間の検査
- 縦用 .ass の歌詞と本編の歌詞の突き合わせ（本編を直して縦を直し忘れたら警告する）
- `utavideo shorts`：`build/shorts/<name>.mp4`。同じ区間の 16:9 版（`build/shorts/wide/<name>.mp4`）、区間の端の音声のフェード
- 画面の作り方 `layout = "blur"`：本編をぼかした背景の帯に置く
- 後で: ショートのタイトル・概要欄、`release` でショートも残す、アバターを縦で別の位置に置く

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
