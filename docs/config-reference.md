# utavideo.toml リファレンス

曲フォルダの直下に置く設定ファイルです。パスは `utavideo.toml` からの相対パスで書きます（絶対パスも使えます）。
存在しない項目を書くとエラーになります（書き間違いに気づけるようにするためです）。

## [song]

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `title` | 文字列 | 必須 | 曲名。`release` のファイル名にも使う |
| `artist` | 文字列 | `""` | アーティスト名 |
| `label` | 文字列 | `""` | チャンネル名やシリーズ名など、曲名表示に添える文字 |

## [audio]

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `file` | パス | 必須 | 音源。この長さが動画の長さになる。ファイル名の `vX.Y` が `release` のバージョンになる |

## [video]

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `background` | パス | 必須 | 背景。画像（png / jpg / webp / bmp）、GIF、動画（mp4 / mov / webm / mkv / m4v / avi）。GIF と動画は音声の長さまで繰り返す |
| `size` | `[幅, 高さ]` | `[1920, 1080]` | 出力の解像度（偶数）。`src/lyrics.ass` の PlayRes と同じにする |
| `fps` | 整数 | `30` | フレームレート |
| `crf` | 整数 0〜51 | `18` | 画質。小さいほど高画質で、ファイルが大きくなる |
| `preset` | 文字列 | `"slow"` | x264 のプリセット。`ultrafast` / `superfast` / `veryfast` / `faster` / `fast` / `medium` / `slow` / `slower` / `veryslow` / `placebo`。速く書き出したいときは `"medium"` や `"fast"` |
| `fit` | `"cover"` / `"contain"` | `"cover"` | 背景の縦横比が出力と違うとき。`cover` ははみ出した部分を切り取り、`contain` は余白を `pad_color` で埋める |
| `scale_flags` | `"lanczos"` / `"bicubic"` / `"bilinear"` / `"area"` / `"neighbor"` | `"lanczos"` | 背景の拡大縮小の方法。ドット絵をくっきり見せたいときは `"neighbor"` |
| `pad_color` | 文字列 | `"black"` | `fit = "contain"` のときの余白の色（ffmpeg の色指定。例: `"pink"`、`"0xF8D8E8"`） |

## [lyrics]

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `file` | パス | `"src/lyrics.ass"` | 歌詞・コメントの .ass |
| `fade_ms` | `[イン, アウト]`（0 以上） | `[150, 150]` | `\fad` が無い行に自動で付けるフェード（ミリ秒）。`[0, 0]` で付けない |

## [overlay_text]

動画の最初から最後まで表示する曲名表示です。.ass には書かず、この設定から自動で作ります。

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `enabled` | 真偽値 | `true` | 表示するかどうか |
| `style` | 文字列 | `"Title"` | 使う .ass のスタイル。位置・フォント・色はスタイルで調整する |
| `text` | 文字列 | `"{title} / {artist}"` | 表示する文字。`{title}`・`{artist}`・`{label}` が使える。改行は `\N`（TOML では `"\\N"` と書く） |

## 書き出しの設定（変更不可）

| 出力 | 映像 | 音声 |
|---|---|---|
| `build/main.mp4` | H.264（`crf`・`preset`）、yuv420p、BT.709 | AAC 320kbps、48kHz |
| `build/preview/bg.mp4` | H.264（ultrafast、CRF 28、15 フレームごとにキーフレーム） | AAC 160kbps、48kHz |
| `build/overlay.mov` | ProRes 4444（アルファ付き）、BT.709 | PCM 24bit、48kHz |

## ユーザー設定（~/.config/utavideo/config.toml）

すべての曲に共通する設定です。ファイルが無くても動きます。

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `font_dirs` | パスの配列 | 下記 | フォントを探すディレクトリ（サブディレクトリも探す） |

`font_dirs` の既定値:

- Linux / WSL2: `/mnt/c/Windows/Fonts`、`/mnt/c/Users/*/AppData/Local/Microsoft/Windows/Fonts` と、fontconfig が既定で見る `/usr/share/fonts`、`/usr/local/share/fonts`、`$XDG_DATA_HOME/fonts`（既定は `~/.local/share/fonts`）、`~/.fonts`（存在するものだけ）
- Windows: `%WINDIR%\Fonts`、`%LOCALAPPDATA%\Microsoft\Windows\Fonts`

`~` から始まるパスはホームディレクトリに展開されます。

環境変数 `UTAVIDEO_FONT_DIRS`（`:` 区切り。Windows では `;`）を設定すると、`font_dirs` より優先されます。
フォントの一覧は `~/.cache/utavideo/` にキャッシュされます（消しても次回作り直されます）。
