# 設定リファレンス

曲ごとの `utavideo.toml`、すべての曲に共通するユーザー設定、環境変数の全項目です。やりたいこと別の書き方は [customization.md](customization.md) を参照してください。

`utavideo.toml` は曲フォルダの直下に置く設定ファイルです。パスは `utavideo.toml` からの相対パスで書きます（絶対パスも使えます）。
存在しない項目を書くとエラーになります（書き間違いに気づけるようにするためです）。

## エディタの補完

`utavideo new` / `utavideo init` / `utavideo sample` が作る `utavideo.toml` の1行目には `#:schema <パス>` が入っています。これは taplo（TOML の言語サーバー）が認識する規約で、次のエディタでキー名の補完・型の検証が効きます。

- VSCode: [Even Better TOML](https://marketplace.visualstudio.com/items?itemName=tamasfe.even-better-toml) 拡張を入れるだけで、設定は不要です
- Neovim: [taplo](https://taplo.tamasfe.dev/) を LSP として起動する設定を `toml` の filetype に追加します
- JetBrains 系 IDE: 標準の TOML プラグインが対応しています

エディタで効くのは項目名・型・配列の要素数のような構造の検証だけで、ハッシュタグの重複禁止のような意味の検証は `utavideo check` に任せています。

`#:schema` が指すのは、インストールした utavideo に同梱された JSON Schema です（同梱ファイルなので、既存の曲フォルダの `utavideo.toml` に手で1行目として足しても使えます）。

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

## [[layers]]

背景の上に重ねる画像・GIF・アルファ付き動画です。1個の素材につき1つ書きます。本編・`preview-bg`（本編・縦の両方）・`shorts`（縦・`wide` の両方）・サムネイルで共通に使います（出力ごとの上書き・除外はまだできません）。

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `name` | 文字列 | 必須 | 名前。使える文字と重複の扱いは `[[thumbnails]]` の `name` と同じ |
| `file` | パス | 必須 | 画像・GIF・アルファ付き動画。長さが本編より短ければ繰り返す |
| `start` | `"M:SS"`・`"M:SS.fff"` の文字列、または秒の数 | なし（最初から） | 出す時刻 |
| `end` | `"M:SS"`・`"M:SS.fff"` の文字列、または秒の数 | なし（最後まで） | 消す時刻 |
| `scale` | 数 | `1.0` | 拡大率 |
| `anchor` | `"top-left"` / `"top"` / `"top-right"` / `"left"` / `"center"` / `"right"` / `"bottom-left"` / `"bottom"` / `"bottom-right"` | `"center"` | アンカー（.ass の `Alignment` と同じテンキー配置） |
| `margin` | `[横, 縦]`（ピクセル） | `[0, 0]` | アンカーの辺から内側への距離。負の値も使える（画面外に出す構図のため）。`anchor` が中央に寄る軸（例: `"top"` の横方向）では効かない |
| `layer` | 整数 | `0` | 前後関係。`.ass` の `Layer` と同じ尺度で、数字が大きいほど手前。0 未満は歌詞より奥、0 以上（既定）は歌詞より手前に重なる |

- 動画・GIF は libass の `subtitles` フィルタと同じ位置（歌詞の手前・奥）に重ねられるよう、`layer` が負のものと 0 以上のものを別々に合成する。同じ側の中では `layer` の小さい順に重ねる
- `.webm` はアルファ付き VP9 を想定する（書き出し方は [customization.md](customization.md#素材を重ねるlayers)）
- サムネイルでは、`start`・`end` の区間に `[[thumbnails]]` の `at`（無ければ 0 秒）が入っているレイヤーだけを重ねる

## [avatar]

ブルーバック・グリーンバックで録画したアバター動画を、背景の上に合成します（1つの曲に1つ）。`key`・`similarity`・`despill`・`sync`・`delay_ms`（撮影・機材ごとに答えが一つに決まるもの）は `utavideo` が内部でキャッシュし、`scale`・`anchor`・`margin`・`layer`（気分で変えたいもの）は `[[layers]]` と同じレイヤーとして本編・`preview-bg`（本編・縦の両方）・`shorts`（縦・`wide` の両方）・サムネイル・`preview` に重なります。

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `file` | パス | 必須 | 録画した動画（音声トラック入り） |
| `key` | 文字列（`"0xRRGGBB"`） | `"0x0000ff"` | 抜く色。既定はブルーバック（`"0x00ff00"` でグリーンバック） |
| `similarity` | 0〜1 の数 | `0.3` | `key` にどれだけ近い色まで抜くか（ffmpeg の `colorkey` の `similarity`） |
| `despill` | 0〜1 の数 | `0.2` | 被写体に残る `key` の色かぶりを消す強さ（ffmpeg の `despill` の `mix`）。`type`（`blue`/`green`）は `key` の色から自動で決める |
| `sync` | `"auto"` または秒の数 | `"auto"` | 音の頭出し。`"auto"` は録画の音声と `audio.file` の相互相関で自動的に求める（`check`・`build` が値と際立ち（z 値）を表示する）。z 値が低い（5 未満）ときはエラーになるので、秒数を直接書いて手動で指定する |
| `delay_ms` | 数（ミリ秒） | `0` | 動きの遅延。モーションキャプチャ・描画の遅延ぶん、アバターの動きが録画の音声より遅れる分を手動で足す（機材ごとに一度決めたら基本固定） |
| `scale` | 数 | `1.0` | 拡大率 |
| `anchor` | `[[layers]]` の `anchor` と同じ9方向 | `"center"` | アンカー |
| `margin` | `[横, 縦]`（ピクセル） | `[0, 0]` | アンカーの辺から内側への距離。`[[layers]]` の `margin` と同じ |
| `layer` | 整数 | `0` | 前後関係。`[[layers]]` の `layer` と同じ尺度 |

- 大きさと位置は曲を通して固定です（時間で動かす演出はできません）
- キー抜き・頭出し済みの中間動画は `build/.work/` に自動でキャッシュされます（`utavideo avatar prepare` のような手動コマンドはありません）。`file`・`key`・`similarity`・`despill`・`sync`・`delay_ms` が前回の書き出しから変わっていなければ作り直しません
- 品質が実用に届かないときは、utavideo 側で ML マッティング等の高品質化はしません。録画側でアルファ付き録画（OBS + `alphaPacker` 等）に切り替えてください（詳しくは [customization.md](customization.md#アバターの合成avatar)）

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
| `hashtags` | 文字列の配列 | `[]` | ハッシュタグ。`#` と空白は付けない。重複はエラー（大文字と小文字の違いだけのものも重複） |
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

縦型のショートの共通設定です。書かなければ既定値を使います。本編の映像を上下中央に置き、ぼかした帯を上下に敷く画面（blur）で作ります。

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `size` | `[幅, 高さ]` | `[1080, 1920]` | 縦の解像度（偶数）。縦用 .ass の PlayRes と同じにする。`utavideo preview-bg` はこの大きさに変換する |
| `lyrics` | パス | `"src/vertical.ass"` | 縦用 .ass。`utavideo preview-bg` が無ければここに作る。ショートの区間もここに書く（[`[[shorts]]`](#shorts)） |
| `focus` | `[x, y]`（0〜1 の数） | `video.focus` | 背景を縦に合わせるとき、どこを基準にするか（意味は `[video]` の `focus` と同じ）。上下の帯の切り取りに使う |
| `overlay_text` | 真偽値 | `true` | 縦で曲名表示（`[overlay_text]`）を出すか。`false` にすると、本編では出したまま縦だけ消せる（`shorts`・縦の下敷き） |
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

## [[uploads]]

投稿した動画です。投稿して URL が決まってから、1つの動画につき1つ書きます。`utavideo announce` が、URL からサイトを判定してリンクを並べます。

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `url` | 文字列 | 必須 | 投稿した動画の URL。受け付ける形は [commands.md](commands.md#announce) |

## [announce]

SNS の告知文の中身です。この表があると、`check` が告知文も検査します。

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `text` | 文字列 | `""` | 手書きの文章（TOML の `"""` で複数行を書ける）。前後の空白・空行は取り除く |
| `hashtags` | 文字列の配列 | `[]` | ハッシュタグ。`#` と空白は付けない。重複はエラー（`[description]` と同じ）。X でタグが途中で切れる文字は `check`・`announce` でエラー |

## [inst]

`utavideo inst`（歌唱練習用の動画）が使う音源と、表示する文字です。既定では歌詞は描かず、この文字だけを表示します（`inst --lyrics` を付けると本編と同じ歌詞も焼き込みます。[commands.md](commands.md#inst)）。

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `text` | 文字列 | `"{title} / {artist}（Key: {key}）"` | 表示する文字。`{title}`・`{artist}`・`{label}`・`{key}` が使える。スタイルは `[overlay_text]` の `style` を使う |
| `audio` | パス | 必須（`inst` を使うとき） | inst に使う音源。声を抜いた伴奏など、本編の `audio.file` とは別のファイルを指定する |
| `score` | `[score]` | 無し | 楽譜を音源に合わせて横スクロールで表示する。指定しなければ楽譜は表示しない |

### [score]

`[inst]` の中の表です。MuseScore 4 で作った楽譜(`.mscz`)を、音源のテンポに合わせて画面上を
横スクロールさせます（MuseScore 4 のインストールが要る。[commands.md](commands.md#inst)）。
曲フォルダの外にあるファイルも指定できます。`--keys` で移調したキーごとに楽譜も移調して表示します
（MuseScore CLIの移調機能を使い、調号・臨時記号の♯系/♭系のスペリングはMuseScore側の判断に従います）。
楽譜の帯は不透明なので、`y`（縦位置）が曲名・キーの表示（画面上部）や`--lyrics`の歌詞（画面下部）
と重なると、その下に隠れます。既定（`y`を省略）では画面の縦方向の中央に自動配置するので、
標準的なスタイルとは重なりません（`--lyrics`の歌詞にも音節単位の歌詞が入っているので、
`--lyrics`無しでも楽譜だけで歌詞は読めます）。楽譜と音源の食い違いの検知はまだ対応していません。

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `file` | パス | 必須 | 楽譜(`.mscz`)のパス |
| `first_bar_offset_s` | 数値（秒） | `0.0` | 楽譜の1小節目の頭が、inst の音源上の何秒目にあたるか。楽譜と音源は頭出しが揃っている保証が無いため、目で見て合わせる（弱起の楽譜では負の値もありうる） |
| `play_x` | 0〜1の比率 | `0.5` | 楽譜が流れていく先の再生位置。画面の横幅に対する比率（0が左端、1が右端） |
| `y` | 整数（px） | 画面の縦方向の中央 | 楽譜の帯を置く縦位置（上端）。指定すると自動配置をやめて絶対位置になる |

## ユーザー設定（~/.config/utavideo/config.toml）

すべての曲に共通する設定です。ファイルが無くても動きます。

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `font_dirs` | パスの配列 | 下記 | フォントを探すディレクトリ（サブディレクトリも探す） |

`font_dirs` の既定値（存在するディレクトリだけを使います）:

- Linux / WSL2: `/mnt/c/Windows/Fonts`、`/mnt/c/Users/*/AppData/Local/Microsoft/Windows/Fonts` と、fontconfig が既定で見る `/usr/share/fonts`、`/usr/local/share/fonts`、`$XDG_DATA_HOME/fonts`（既定は `~/.local/share/fonts`）、`~/.fonts`
- macOS: `/System/Library/Fonts`（`Supplemental` はこの下なので一緒に探します）、`/Library/Fonts`、`~/Library/Fonts`に加え、fontconfig が既定で見る `/usr/share/fonts`、`/usr/local/share/fonts`、`$XDG_DATA_HOME/fonts`（既定は `~/.local/share/fonts`）、`~/.fonts`（Homebrew や、Linux から dotfiles ごと持ってきた環境でフォントを置いていることがあるため）。`/Network/Library/Fonts` は、マウントされていないと遅くなるため含みません。必要なら `font_dirs` に書き足してください
- Windows: `%WINDIR%\Fonts`、`%LOCALAPPDATA%\Microsoft\Windows\Fonts`

読むのは `.ttf`・`.otf`・`.ttc`・`.otc` です。それ以外（macOS の dfont など）は黙って飛ばすので、そのフォントを使いたい場合は `.ttf` や `.otf` のものを入れてください。

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

### ユーザー設定の [announce]

SNS の告知文の書式です。長さの上限は X の数え方に合わせています。

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `header` | 文字列 | `"【動画投稿】"` | 1行目。`{…}` は置き換えない |
| `work` | 文字列 | `"『{title} / {artist}』"` | 作品の行。`{title}`・`{artist}`・`{label}`・`{singers}` が使える。`{singers}` は `description.singer_roles`・`singer_separator` で決まる |
| `link` | 文字列 | `"{site} » {url}"` | 動画の URL の行（1つの URL を1行）。`{site}`・`{url}` が使える |
| `sites` | 表 | `{ youtube = "YouTube", niconico = "ニコニコ動画" }` | `{site}` に入れる名前。キーは `youtube`・`niconico` だけ。リンクはここに書いた順に並べる。書くと既定は丸ごと置き換わる（書かなかったサイトの URL はエラー） |
| `order` | 配列 | `["header", "text", "", "work", "", "links", "", "hashtags"]` | ブロックの順番。`""` は空行。書かなかったブロックは出さない。`""` 以外の重複はエラー |
| `max_weight` | 整数（1 以上） | `280` | 告知文の長さ（X の数え方）がこれを超えたら警告する。280 は X で「さらに表示」に折りたたまれない長さ |

- ブロックの間は改行1つで、`order` の `""` の位置に空行を1つ入れます
- 中身の無いブロック（`header` が空、`text` が空、`[[uploads]]` が無い、`hashtags` が空）は出しません。その結果、空行が続けば1つにまとめ、先頭と末尾の空行は捨てます（空行を2つ続けることはできません）

### ユーザー設定の [defaults]

`utavideo new` / `init` が、曲の `utavideo.toml` にコピーする既定値です。ユーザー設定を後で変えても、既存の曲は変わりません。

| 項目 | 型 | 既定値 | 説明 |
|---|---|---|---|
| `credits` | `[[credits]]` と同じ | `[]` | 毎回同じクレジット（`[[defaults.credits]]` と書く） |
| `hashtags` | 文字列の配列 | `[]` | 概要欄に毎回付けるハッシュタグ（`#` は付けない）。`[description].hashtags` にコピーする |
| `announce_hashtags` | 文字列の配列 | `[]` | 告知文に毎回付けるハッシュタグ（`#` は付けない）。`[announce].hashtags` にコピーする |

## 環境変数

| 変数 | 内容 |
|---|---|
| `UTAVIDEO_FONT_DIRS` | フォントを探すディレクトリ（`:` 区切り。Windows では `;`）。`font_dirs` より優先 |
| `UTAVIDEO_MUSESCORE` | MuseScore 4 の実行ファイルのパス。PATH・既定のインストール先から見つからないときに指定する（`[inst.score]` を設定したときの `inst` が使う） |
| `XDG_CONFIG_HOME` | ユーザー設定の場所（既定は `~/.config`。`utavideo/config.toml` を読む） |
| `XDG_CACHE_HOME` | キャッシュの場所（既定は `~/.cache`。`utavideo/` の下に置く） |
| `XDG_DATA_HOME` | `font_dirs` の既定値に含める `fonts/` の場所（既定は `~/.local/share`） |
