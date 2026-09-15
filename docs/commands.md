# コマンドリファレンス

各コマンドのオプション、読み書きするファイル、検査項目、出力の形式です。手順は [workflow.md](workflow.md) を参照してください。

## 共通

- `check`・`preview-bg`・`build`・`overlay`・`release` は曲フォルダで実行します。`-C <曲フォルダ>` で指定でき、省略するとカレントディレクトリから親へ向かって `utavideo.toml` を探します
- `check`・`preview-bg`・`build`・`overlay` には ffmpeg と ffprobe が必要です
- 書き出しは `<名前>.partial.<拡張子>` に書いてから名前を変えます。失敗・中断しても、前に書き出したファイルは残ります
- 出力先のファイルを他のアプリ（動画プレイヤー、エクスプローラーのプレビューなど）で開いていると、WSL2 で Windows のドライブ（`/mnt/c` など）にある曲フォルダでは名前を変えられずに止まります。書き出したものは `.partial` の付いた名前で残るので、アプリを閉じて実行し直します（`release` も同じ）
- WSL2 で `/mnt/<ドライブ>/` 以下に書き出したときは、Windows のパスも表示します
- エラーがあると終了コード 1 で終わります

## new

```sh
utavideo new <曲名> [--artist <名前>] [--root <場所>] [--date YYYYMMDD]
```

`<場所>/YYYYMMDD 曲名/` を作り、雛形のフォルダとファイルを置きます（構成は [project-layout.md](project-layout.md)）。

| オプション | 既定値 | 内容 |
|---|---|---|
| `--artist` | `""` | `song.artist` に書く |
| `--root` | `.` | 曲フォルダを作る場所 |
| `--date` | 今日 | フォルダ名の日付 |

- フォルダが既にあるとエラーです（既存のフォルダには `init` を使います）
- フォルダ名では、ファイル名に使えない文字を `_` にします

## init

```sh
utavideo init [<フォルダ>] [--title <曲名>] [--artist <名前>]
```

既存のフォルダに、足りないフォルダとファイルだけを作ります。既にあるファイルは移動も上書きもしません。

| オプション | 既定値 | 内容 |
|---|---|---|
| `<フォルダ>` | `.` | 対象のフォルダ（存在しないとエラー） |
| `--title` | フォルダ名から先頭の日付を除いたもの | `song.title` に書く |
| `--artist` | `""` | `song.artist` に書く |

`src/`（`src/ref/` を除く）に音源と背景がちょうど1つずつあれば、`utavideo.toml` の `audio.file`・`video.background` に設定します。対象の拡張子は、音源が wav / flac / mp3 / m4a / aac / ogg / opus、背景が [config-reference.md](config-reference.md#video) の `background` と同じです。

## check

```sh
utavideo check [-C <曲フォルダ>]
```

[検査項目](#検査項目)を調べ、曲名・音源の長さ・歌詞の行数・使うフォントのファイル・`release` の書き出し先を表示します。

## preview-bg / build / overlay

```sh
utavideo preview-bg [-C <曲フォルダ>]
utavideo build [-C <曲フォルダ>]
utavideo overlay [-C <曲フォルダ>]
```

| コマンド | 出力 | 入るもの |
|---|---|---|
| `preview-bg` | `build/preview/bg.mp4` | 背景・曲名表示・音声（歌詞の行は入れない） |
| `build` | `build/main.mp4` | 背景・歌詞・曲名表示・音声 |
| `overlay` | `build/overlay.mov` | 歌詞・曲名表示（背景は透明）・音声。背景のファイルは不要 |

- 書き出す前に[検査](#検査項目)し、エラーがあれば書き出しません。警告は表示して続けます
- `preview-bg` は、歌詞の行についての検査を行いません
- 動画の長さは音源の長さです
- 描画に使った .ass を `build/.work/final.ass`・`preview.ass`・`overlay.ass` に書きます（自動のフェードと曲名表示が入ったもの）

## release

```sh
utavideo release [-C <曲フォルダ>] [--version <バージョン>] [--allow-stale]
```

`build/main.mp4` を `release/<曲名> <バージョン>.mp4` にコピーします。

| オプション | 既定値 | 内容 |
|---|---|---|
| `--version` | 音源のファイル名から（規則は [project-layout.md](project-layout.md#名前の付け方)） | `v1`・`v1.2.1` の形（小文字の `v`） |
| `--allow-stale` | 無効 | 入力が `build/main.mp4` より新しくてもコピーする |

次のときは止まります。

- `build/main.mp4` が無い
- バージョンが決まらない、または形式が違う
- 同じ名前のファイルが `release/` にある（上書きしない）
- `utavideo.toml`・音源・背景・歌詞のどれかが `build/main.mp4` より新しい（`--allow-stale` で無視）

## 検査項目

### エラー（書き出さない）

| 対象 | 内容 |
|---|---|
| 設定 | `utavideo.toml` が無い、TOML の構文が不正、未知の項目や不正な値がある。ユーザー設定も同じ |
| 素材 | `audio.file`・`lyrics.file`・`video.background`（`overlay` では不要）のファイルが無い、背景の形式に対応していない、音源に音声が入っていない |
| 歌詞 | .ass が読めない、`PlayResX`・`PlayResY` が無い、`video.size` と違う、未定義のスタイル（`\r` の切り替え先を含む）を使っている |
| 曲名表示 | `overlay_text.style` のスタイルが .ass に無い、`overlay_text.text` の書式が不正 |
| フォント | 使っているフォントが見つからない |
| 実行環境 | ffmpeg・ffprobe が無い |

### 警告

| 対象 | 内容 |
|---|---|
| 歌詞の行 | `\pos`・`\move` を使っている、表示時間が 0 以下、音声が終わった後に始まる、音声の終わりで途中で切られる、同じスタイル・同じレイヤーで重なる、画面からはみ出しそう |
| `check` だけ | 音源のファイル名にバージョン（`vX.Y`）が無い、`song.artist` が空 |

はみ出しの概算で反映するタグは [customization.md](customization.md#utavideo-が読むタグ) を参照してください。

## 出力の形式（変更不可）

| 出力 | 映像 | 音声 |
|---|---|---|
| `build/main.mp4` | H.264（`video.crf`・`video.preset`）、yuv420p、BT.709 | AAC 320kbps、48kHz |
| `build/preview/bg.mp4` | H.264（ultrafast、CRF 28、15 フレームごとにキーフレーム） | AAC 160kbps、48kHz |
| `build/overlay.mov` | ProRes 4444（アルファ付き）、BT.709 | PCM 24bit、48kHz |
