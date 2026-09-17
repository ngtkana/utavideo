# 設定リファレンス

曲ごとの `utavideo.toml`、すべての曲に共通するユーザー設定、環境変数の全項目です。やりたいこと別の書き方は [customization.md](customization.md) を参照してください。

`utavideo.toml` は曲フォルダの直下に置く設定ファイルです。パスは `utavideo.toml` からの相対パスで書きます（絶対パスも使えます）。
存在しない項目を書くとエラーになります（書き間違いに気づけるようにするためです）。

## [song]

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `title` | 文字列 | 必須 | 曲名。曲名表示・概要欄に使う |
| `slug` | 文字列 | 空（`title` から作る） | フォルダ名・ファイル名に使う識別子。曲名を変えてもファイル名が変わらないように分けてある（[名前の付け方](project-layout.md#名前の付け方)）。ファイル名に使えない名前はエラー |
| `artist` | 文字列 | `""` | アーティスト名 |
| `label` | 文字列 | `""` | チャンネル名やシリーズ名など、曲名表示に添える文字 |
| `original_urls` | 文字列の配列 | `[]` | 原曲の URL。概要欄の原曲の見出しの下に並べる |

## [audio]

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `file` | パス | 必須 | 音源。この長さが動画の長さになる。ファイル名の `vX.Y` が `release` の名前に使われる |

## [video]

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `background` | パス | 必須 | 背景。画像（png / jpg / webp / bmp）、GIF、動画（mp4 / mov / webm / mkv / m4v / avi）。GIF と動画は音声の長さまで繰り返す |
| `size` | `[幅, 高さ]` | `[1920, 1080]` | 出力の解像度（偶数）。`src/lyrics.ass` の PlayRes と同じにする |
| `fps` | 整数 | `30` | フレームレート |
| `crf` | 整数 0〜51 | `18` | 画質。小さいほど高画質で、ファイルが大きくなる |
| `preset` | 文字列 | `"slow"` | x264 のプリセット。`ultrafast` / `superfast` / `veryfast` / `faster` / `fast` / `medium` / `slow` / `slower` / `veryslow` / `placebo`。速く書き出したいときは `"medium"` や `"fast"` |
| `fit` | `"cover"` / `"contain"` | `"cover"` | 背景の縦横比が出力と違うとき。`cover` ははみ出した部分を切り取り、`contain` は余白を `pad_color` で埋める |
| `focus` | `[x, y]`（0〜1 の数） | `[0.5, 0.5]` | 背景の縦横比が出力と違うとき、どこを基準に合わせるか（CSS の `object-position` と同じ考え方。`[0, 0]` が左上、`[1, 1]` が右下）。`cover` では切り取って残す位置、`contain` では余白の中で背景を寄せる位置。サムネイルにも使う |
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

## [[credits]]

概要欄のクレジットです。1人につき1つ書きます。`roles` の並びが同じ人は、1つの見出しにまとめます。

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `roles` | 文字列の配列（1つ以上） | 必須 | 役割。見出しになる（例: `["Vocal", "Mix"]` →「Vocal, Mix」） |
| `name` | 文字列 | 必須 | 名前。敬称を付けるならここに書く |
| `urls` | 文字列の配列 | `[]` | リンク |

## [[materials]]

使った素材です。1つの素材につき1つ書きます。同じ `section` は、1つの見出しにまとめます。

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `section` | 文字列 | 必須 | 見出し（例: イラスト、Inst、使用素材） |
| `urls` | 文字列の配列 | `[]` | 素材の URL。空なら概要欄に出さない（自作の素材など） |
| `files` | パスの配列 | `[]` | その素材を使ったファイル。`check` がクレジットの書き忘れを見つけるのに使う |

## [description]

概要欄の中身です。この表があると、`check` と `description` が概要欄を検査します。概要欄とタイトルの書き出し先は [commands.md](commands.md#description) にあります。

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `text` | 文字列 | `""` | 冒頭の文章（TOML の `"""` で複数行を書ける）。前後の空行は取り除く |
| `hashtags` | 文字列の配列 | `[]` | ハッシュタグ。`#` と空白は付けない |
| `title` | 文字列 | なし | タイトル。書くと、ユーザー設定の `description.title` から作るタイトルの代わりに使う |

## [[thumbnails]]

サムネイル（`utavideo thumbnail`）です。サイズ違いなど、1枚につき1つ書きます。背景・`fit`・`scale_flags`・`pad_color` は `[video]` のものを使います。

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `name` | 文字列 | 必須 | 出力の名前（`build/thumbnail/<name>.png`）。使える文字は `song.slug` と同じ（[名前の付け方](project-layout.md#名前の付け方)）で、末尾に `.partial` は付けられない。大文字小文字を区別せずに比べて、重複はエラー（Windows のファイルシステムで同じ名前になるため） |
| `file` | パス | 必須 | サムネイル用の .ass。0 秒の状態を描く |
| `size` | `[幅, 高さ]` | `video.size` | 出力の大きさ。.ass の PlayRes と同じにする。動画と違い奇数でもよい |
| `at` | `"M:SS"`・`"M:SS.fff"` の文字列、または秒の数 | `0` | 背景が GIF・動画のとき、使うフレームの時刻（例: `"1:23.5"`、`83.5`）。背景が画像なら書けない。背景の長さ以上はエラー |
| `focus` | `[x, y]`（0〜1 の数） | `video.focus` | `[video]` の `focus` を上書きする |

## [vertical]

縦型のショートの共通設定です。書かなければ既定値を使います。

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `size` | `[幅, 高さ]` | `[1080, 1920]` | 縦の解像度（偶数）。縦用 .ass の PlayRes と同じにする。`utavideo vertical-ass` はこの大きさに変換する |
| `lyrics` | パス | `"src/vertical.ass"` | 縦用 .ass。`utavideo vertical-ass` がここに作る。ショートの区間もここに書く（[`[[shorts]]`](#shorts)） |
| `focus` | `[x, y]`（0〜1 の数） | `video.focus` | 背景を縦に合わせるとき、どこを基準にするか（意味は `[video]` の `focus` と同じ）。`preview-bg --vertical` と `shorts` に使う |
| `overlay_text` | 真偽値 | `true` | 縦で曲名表示（`[overlay_text]`）を出すか。`false` にすると、本編では出したまま縦だけ消せる（`shorts`・`preview-bg --vertical`） |
| `audio_fade_ms` | `[イン, アウト]`（0 以上の整数） | `[300, 1000]` | 区間の端の音声のフェード（ミリ秒）。16:9 版（`wide`）にも効く。イン ＋ アウトが区間の長さを超えるとエラー。映像はフェードしない（ショートは繰り返し再生されるので、暗転を挟まない） |

## [[shorts]]

縦型のショートです。1本につき1つ書きます。区間は縦用 .ass（`vertical.lyrics`）に、スタイル `Short` のコメント行で置きます。行の本文を `name` と同じにします（前後の空白は除いて、大文字小文字も含めて比べる）。

```
Comment: 0,0:01:05.20,0:01:45.65,Short,,0,0,0,,chorus
```

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `name` | 文字列 | 必須 | ショートの名前。区間の行の本文と同じにする。出力は `build/shorts/<name>.mp4`。使える文字と重複の扱いは `[[thumbnails]]` の `name` と同じ |
| `focus` | `[x, y]`（0〜1 の数） | `vertical.focus` | このショートだけ、背景の残す位置を変える |
| `wide` | 真偽値 | `false` | 同じ区間の 16:9 版（`build/shorts/wide/<name>.mp4`）も書き出す。本編と同じ画面で、SNS の告知に添える用 |

この表があると、`check` が縦用 .ass と区間を検査し（[commands.md](commands.md#ショートの検査)）、`utavideo shorts` で書き出せます（[commands.md](commands.md#shorts)）。

## ユーザー設定（~/.config/utavideo/config.toml）

すべての曲に共通する設定です。ファイルが無くても動きます。

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `font_dirs` | パスの配列 | 下記 | フォントを探すディレクトリ（サブディレクトリも探す） |

`font_dirs` の既定値:

- Linux / WSL2: `/mnt/c/Windows/Fonts`、`/mnt/c/Users/*/AppData/Local/Microsoft/Windows/Fonts` と、fontconfig が既定で見る `/usr/share/fonts`、`/usr/local/share/fonts`、`$XDG_DATA_HOME/fonts`（既定は `~/.local/share/fonts`）、`~/.fonts`（存在するものだけ）
- Windows: `%WINDIR%\Fonts`、`%LOCALAPPDATA%\Microsoft\Windows\Fonts`

`~` から始まるパスはホームディレクトリに展開されます。

フォントの一覧は `~/.cache/utavideo/` にキャッシュされます（消しても次回作り直されます）。

### ユーザー設定の [description]

概要欄とタイトルの書式です。

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `title` | 文字列 | `"{title} / {artist}（Cover: {singers}）"` | タイトルの形。`{title}`・`{artist}`・`{label}`・`{singers}` が使える |
| `singer_roles` | 文字列の配列 | `["Vocal"]` | `{singers}` に入れる人の役割（`roles` にどれかを持つ人を、書いた順に並べる） |
| `singer_separator` | 文字列 | `", "` | `{singers}` の名前の区切り |
| `heading` | 文字列 | `"■{section}"` | 見出しの形。`{section}` が見出しの名前になる |
| `original_heading` | 文字列 | `"原曲"` | 原曲の URL の見出しの名前 |
| `role_separator` | 文字列 | `", "` | 見出しにする役割の区切り |
| `name_url_separator` | 文字列 | `" "` | クレジットの名前と URL の区切り。`"\n"` なら別の行 |
| `section_gap` | 整数（0 以上） | `0` | 見出し同士の間の空行の数 |
| `hashtags_gap` | 整数（0 以上） | `1` | ハッシュタグの前の空行の数 |
| `order` | 配列 | `["text", "original", "credits", "materials", "hashtags"]` | ブロックの順番。書かなかったブロックは出さない |

それ以外のブロックの間は、空行1つです。

### ユーザー設定の [defaults]

`utavideo new` / `init` が、曲の `utavideo.toml` にコピーする既定値です。ユーザー設定を後で変えても、既存の曲は変わりません。

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `credits` | `[[credits]]` と同じ | `[]` | 毎回同じクレジット（`[[defaults.credits]]` と書く） |
| `hashtags` | 文字列の配列 | `[]` | 毎回同じハッシュタグ（`#` は付けない） |

## 環境変数

| 変数 | 内容 |
|---|---|
| `UTAVIDEO_FONT_DIRS` | フォントを探すディレクトリ（`:` 区切り。Windows では `;`）。`font_dirs` より優先 |
| `XDG_CONFIG_HOME` | ユーザー設定の場所（既定は `~/.config`。`utavideo/config.toml` を読む） |
| `XDG_CACHE_HOME` | キャッシュの場所（既定は `~/.cache`。`utavideo/` の下に置く） |
| `XDG_DATA_HOME` | `font_dirs` の既定値に含める `fonts/` の場所（既定は `~/.local/share`） |
