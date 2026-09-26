# ロードマップ

## 実装済み

背景（画像・GIF・動画）＋ 歌詞 ＋ 曲名表示 ＋ 音声の動画を書き出す。

- コマンド: `new` / `init` / `preview-bg` / `check` / `build` / `overlay` / `thumbnail` / `description` / `release` / `announce` / `fonts` / `status` / `build-all`
- `check`: 設定・素材・スタイル・フォントの検査、行の重なり・`\pos`・はみ出しの警告
- 概要欄: `utavideo.toml` のクレジット・素材から概要欄とタイトルを作る（書式はユーザー設定）
- 告知文: 投稿した動画の URL（`[[uploads]]`）と曲の情報から SNS（X）の告知文を作り、URL の形・ハッシュタグ・X での長さを検査する

- サムネイル: 背景のフレーム（`at`）にサムネイル用の .ass を描いた PNG。サイズ違いは `[[thumbnails]]` を並べる。背景の残す位置（`focus`）は動画にも効く
- 縦型のショート（1段目）: `preview-bg` が本編の .ass から縦用 .ass を自動で作る（スタイルの幅の比での縮小）。`LayoutResX`・`LayoutResY` の縦横比が PlayRes と違う .ass をエラーにする
- 縦型のショート（2段目）: `preview-bg` で縦の下敷き（`vertical.focus`）。区間は縦用 .ass のコメント行（スタイル `Short`、本文がショートの名前）に置き、`[[shorts]]` の `name` とつなぐ。`check` で縦用 .ass と区間を検査する
- 縦型のショート（3段目）: `utavideo shorts` で区間を書き出す（`build/shorts/<name>.mp4`、`wide = true` の 16:9 版、区間のフレームの丸め、区間の端の音声のフェード、`shorts[].focus`、`vertical.overlay_text`、投稿先の長さの上限の警告）。本編の映像を上下中央に置き、上下を背景だけをぼかした帯で埋める（`preview-bg` の下敷きも同じ画面にする）
- 歌唱練習用のカラオケ動画（issue #69・#70・#71・#72）: `utavideo inst --keys -1,-2,-3` で、ffmpeg の `rubberband`（無ければ `asetrate`+`atempo`）によりキーを変えた伴奏動画を、キーごとに別ファイルで書き出す（`build/inst/<slug>-key<キー>.mp4`）。`loudnorm`（2パス）で音量をそろえる。画面には既定で曲名・アーティスト・キーだけを表示する（YouTube 限定公開／非公開で自分が聴く用途なので、クレジット画面は作らない）。`--lyrics` を付けると本編と同じ歌詞も焼き込める（`--keys` によるキー変更と両立）
- 曲フォルダの状態の一覧（issue #77・#78・#79）: `utavideo status` で、`build`・概要欄・告知文・`[[shorts]]`・`[[thumbnails]]`・release の状態を git status 風に一覧する。`check`（今書き出しても大丈夫か）とは別に「前回書き出したときから何が変わったか」を見る。入力の比較は size・mtime_ns が一致すれば読まずに済ませ、違うときだけ中身で確かめる二層判定にした（ショート・サムネイルはフォント依存の検出を簡略化し、歌詞・設定ファイル自体の変化だけを見る）
- 今作れるものをまとめて作る（issue #85）: `utavideo build-all` で、`build`・`description`・`announce`・`thumbnail` について、既に済んでいるものはスキップし、書き出し前の検査（`analyze.py`）でエラーがあるものは「要対応」として案内し、それ以外を書き出す
- 素材を重ねる（issue #111）: `[[layers]]` で、ユーザーが用意した画像・GIF・アルファ付き動画を背景の上に重ねる（位置・大きさ・表示する区間）。本編・`preview-bg`（本編・縦の両方）・サムネイルに共通で効く。`layer`（`.ass` の `Layer` と同じ尺度）で歌詞との前後関係を決める
- ショートも release で残す（issue #122）: `utavideo release --short <name>` で、ショートも本編と同じ規則（`release/<slug>-shorts-<name>-vX.Y.N.mp4`。`wide` は別番号）で `release/` にコピーする。`status` もショートの release の状態を追う
- 数値調整の高速プレビュー（issue #113）: `utavideo preview --at <時刻> [--duration <秒数>] [--watch]` で、指定した一瞬・短い区間だけを `build/.work/preview.png`・`preview.mp4` に書き出す。`preview-bg` とは別に、`utavideo.toml` の数値やスタイルを調整するたびに本番の `build` を待たなくて済む。`--watch` は `utavideo.toml`・歌詞・`[[layers]]`・背景の変更を mtime のポーリングで検知して自動的に作り直す。`check` 相当の検査はせず、今の状態をそのまま見せる
- アバターの合成（issue #112）: `[avatar]` で、ブルーバック・グリーンバックで録画したアバター動画を背景の上に合成する。クロマキー（ffmpeg の `colorkey`・`despill`）、音の頭出し（`sync = "auto"`、録画の音声と音源の相互相関。`check`・`build` がズレと際立ち（z 値）を表示し、低すぎれば手動指定を促す）、動きの遅延（`delay_ms`、手動）は「答えが一つに決まるもの」として `build/.work/` に中間動画をキャッシュする。位置・大きさ・前後関係（`scale`・`anchor`・`margin`・`layer`）は「気分で変えたいもの」として `[[layers]]`（issue #111）と同じ `LayerSpec` に変換し、同じ合成コードに乗せる（本編・`preview-bg`・`shorts`・サムネイル・`preview` に共通で効く）

## 予定

### 概要欄の文章（続き）

- 通し番号、前後の動画へのリンク（他の曲フォルダの情報が要る。手で書くと番号や URL を間違えやすい）
- 他サイト版へのリンク（告知文と同じ `[[uploads]]` の URL を使う）
- よく使う素材をユーザー設定に登録し、名前で参照する

### 背景の演出

- 背景をゆっくり拡大・移動させる（Ken Burns 効果）

### 縦型のショート（続き）

- ショートのタイトル・概要欄を作る（本編の URL が要るので、`[[uploads]]`（issue #21）と一緒に考える）
- アバターの合成を、縦では別の位置に置く

### 歌唱練習用のカラオケ動画（続き）

- MuseScore で作るボーカル用楽譜との連携（issue #139）：`inst` に楽譜を音源に合わせて横に流して表示する。要件・調査を issue #139 にまとめ、実装単位のissue（#140〜#147）に分解して進めている。楽譜の描画パイプライン（`.mscz` → MusicXML → Verovio → PNG、issue #140）は実装済み（`inst` コマンドへの組み込みはこれから）

### サムネイル（続き）

- 同じサイズで何枚か書き出して見比べる
- サムネイルごとに別の背景を使う（例: 動画は小さい GIF、サムネイルは高解像度の静止画）
- `release` へのコピー
- 投稿先の容量の上限に収まらない例が出たら、JPEG での書き出しか容量の警告を足す
