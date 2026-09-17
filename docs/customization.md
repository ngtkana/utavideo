# カスタマイズ一覧

変えられることの一覧です。基本の手順は [workflow.md](workflow.md)、項目の型と既定値は [config-reference.md](config-reference.md)、コマンドの詳細は [commands.md](commands.md) を参照してください。

## 歌詞の見た目（.ass のスタイル）

| やりたいこと | 書き方 |
|---|---|
| フォント・大きさ | `Fontname`・`Fontsize` |
| 色 | `PrimaryColour`（文字）・`OutlineColour`（縁）・`BackColour`（影）。`&HAABBGGRR` で、`AA` が `00` なら不透明 |
| 太字・斜体 | `Bold`・`Italic` を `-1` |
| 縁取り・影 | `Outline`・`Shadow` |
| 文字の後ろに帯 | `BorderStyle` を `3`（帯の色は `OutlineColour`） |
| 字間・横幅 | `Spacing`・`ScaleX` |
| 位置 | `Alignment`（テンキーの配置）・`MarginL`・`MarginR`・`MarginV`。行ごとの余白は行の `MarginL` など |
| 位置を何種類も使う | スタイルを分ける（`LyricsLeft`・`LyricsRight` など） |
| 同時に複数行（ハモリなど） | レイヤーを分ける。同じスタイル・同じレイヤーで重なると `check` が警告する |
| 手前・奥 | レイヤーの数字が大きいほど手前。曲名表示は 100 |
| 書き出さないメモ | Aegisub で行を「コメント」にする（書き出しにも検査にも使わない） |
| 長い行 | `\N` で改行。空白の無い日本語は自動で折り返されない。折り返しの方式は `WrapStyle`（ファイル全体）・`\q`（行） |
| フェード | 全行は `lyrics.fade_ms`、付けないなら `[0, 0]`。`\fad`・`\fade` を書いた行には自動で付かない |

## utavideo が読むタグ

libass のタグはすべて使えます。次のタグは utavideo の検査にも影響します。

| タグ | 扱い |
|---|---|
| `\pos`・`\move` | `check` が歌詞で警告する（サムネイルでは警告しない）。重なりとはみ出しの検査から外す |
| `\fad`・`\fade` | 歌詞では自動のフェードを付けない。サムネイルでは、0 秒にフェードインが終わっていない行を警告する |
| `\fn` | そのフォントも探す。見つからなければエラー |
| `\r<スタイル名>` | そのスタイルが無ければエラー。フォントも探す |
| `\fs`・`\fscx`・`\fsp`・`\q`・`\N`・`\n`・`\h` | はみ出しの概算に反映する |

はみ出しの概算は `\bord` と縦書き（`@` 付きのフォント名）を反映しません。

`vertical-ass` が縦用 .ass を作るときは、座標と大きさのタグを縦の解像度に変換します（[対象のタグ](commands.md#vertical-ass)）。

## 曲名表示

動画の最初から最後まで、レイヤー 100 に入ります。自動のフェードは付きません。

| やりたいこと | 書き方 |
|---|---|
| 見た目・位置 | .ass の `Title` スタイル |
| 別のスタイルを使う | `overlay_text.style` |
| 文字 | `overlay_text.text`。`{title}`・`{artist}`・`{label}` が使える |
| 改行 | `\N`（TOML では `"\\N"`） |
| タグ | `{` `}` を二重にする。例: `"{{\\an7}}{title}\\N{artist}"`（左上に2行） |
| 表示しない | `overlay_text.enabled = false`（`Title` のフォントも不要になる） |

## 背景と映像（`[video]`）

| やりたいこと | 書き方 |
|---|---|
| 背景 | `background`。画像・GIF・動画（GIF と動画は繰り返す。動画の音声は使わない） |
| 縦横比が違う背景 | `fit`（`cover` で切り取り / `contain` で余白）・`pad_color` |
| 背景のどこを残すか・寄せるか | `focus`（`[0, 0.5]` で左端、`[1, 0.5]` で右端。既定は中央） |
| 拡大の方法 | `scale_flags`（ドット絵は `neighbor`） |
| 解像度・縦長 | `size` と .ass の `PlayResX`・`PlayResY` を同じ偶数にする。歌詞を入れた後は Aegisub の「解像度の変換（Resample Resolution）」 |
| フレームレート | `fps` |
| 画質・書き出しの速さ | `crf`（小さいほど高画質）・`preset` |

## サムネイル

`utavideo thumbnail` で `build/thumbnail/<name>.png` に書き出します。手順は [workflow.md](workflow.md#9-サムネイルを作る)。

| やりたいこと | 書き方 |
|---|---|
| 文字の位置・見た目 | `[[thumbnails]]` の `file` の .ass。Aegisub で `utavideo thumbnail --bg-only` の下敷き（`build/thumbnail/bg/<name>.png`）を開いて組む |
| 背景の GIF・動画のどの時刻を使うか | `at`（`"1:23.5"` か秒の数） |
| 正方形などのサイズ違いを足す | `[[thumbnails]]` をもう1つ書き、`name`・`file`・`size` を変える。.ass の PlayRes も `size` に合わせる |
| サイズ違いで背景の残す位置を変える | そのサムネイルの `focus` |
| 1枚だけ書き出す | `thumbnail --name <name>` |
| 曲名・アーティストを直す | 雛形の `src/thumbnail.ass` には作ったときの `song` が書き込まれている。`song` を直しても変わらないので、.ass も直す |
| 図形 | .ass の `\p`・`\clip` |

画像を重ねること、サムネイルごとに別の背景を使うことはまだできません（[roadmap.md](roadmap.md)）。

## 縦型のショート

縦型のショートに使う歌詞は、本編とは別の縦用 .ass に組みます。手順は [workflow.md](workflow.md#10-ショートの縦用-ass-を作り区間を置く)。

| やりたいこと | 書き方 |
|---|---|
| 縦用 .ass を作る | `utavideo vertical-ass`。本編の .ass の行を写し、大きさと座標を縦の解像度に変換する |
| 縦の解像度 | `vertical.size`（`vertical-ass` の前に決める。後から変えるなら、縦用 .ass の PlayRes も同じにする） |
| 縦用 .ass の場所・名前 | `vertical.lyrics` |
| 縦だけ文字を大きくする・改行する | 縦用 .ass のスタイル `Lyrics` の大きさ、行の `\N`（本編の .ass は変わらない） |
| 縦用 .ass を作り直す | 縦用 .ass を消してから `vertical-ass`（直した内容は残らない） |
| 縦の下敷き（Aegisub で開く） | `preview-bg --vertical`（`build/preview/vertical-bg.mp4`） |
| 縦で背景のどこを残すか | `vertical.focus`（既定は `video.focus`） |
| 切り抜く区間 | 縦用 .ass に、スタイル `Short` のコメント行を置き、本文をショートの名前にする。`utavideo.toml` に同じ `name` の `[[shorts]]` を書く |
| ショートを何本も作る | 区間の行と `[[shorts]]` を、名前を変えて並べる |
| 縦だけの文字（帯の曲名など） | スタイル名を `Vertical` で始める（例: `VerticalBand`）。歌詞として扱わず、区間の端の検査と本編との突き合わせをしない |
| 本編の行を縦では出さない | 縦用 .ass の対応する行をコメント行にする（[本編との突き合わせ](commands.md#本編との突き合わせ)で警告しない） |
| ショートを書き出す | `utavideo shorts`（`--name <name>` で1本だけ） |
| 区間ごとに背景の残す位置を変える | `shorts[].focus`（既定は `vertical.focus`） |
| 同じ区間の 16:9 版も書き出す | `shorts[].wide = true`（`build/shorts/wide/<name>.mp4`） |
| 区間の端の音声のフェード | `vertical.audio_fade_ms`（16:9 版にも効く）。映像はフェードしない |
| 縦だけ曲名表示を消す | `vertical.overlay_text = false`（本編と 16:9 版には出る） |
| 帯の文字にフェードを入れない | スタイル名を `Vertical` で始める（自動のフェードを入れない。`\fad` を自分で書けば効く） |

画面の作り方は、背景を縦に切り取る形だけです（本編をぼかした帯に置く形は [roadmap.md](roadmap.md)）。

## 音源と公開

| やりたいこと | 書き方 |
|---|---|
| 音源 | `audio.file`。ffmpeg が読める形式なら可（`init` の自動設定は wav / flac / mp3 / m4a / aac / ogg / opus） |
| バージョン | 音源のファイル名の `v1.2` など。公開する動画には、その音源で何本目かも付く（規則は [project-layout.md](project-layout.md#名前の付け方)） |
| 音源のバージョンを指定して公開 | `release --version v1.2`（小文字の `v`） |
| 入力の方が新しくても公開 | `release --allow-stale` |
| 公開ファイル名 | `song.title`（ファイル名に使えない文字は `_` になる） |

## フォント

| やりたいこと | 書き方 |
|---|---|
| 探す場所（全曲） | ユーザー設定の `font_dirs`（書くと既定の場所は探さない） |
| 探す場所（その場だけ） | 環境変数 `UTAVIDEO_FONT_DIRS`（`:` 区切り。`font_dirs` より優先） |
| 曲フォルダのフォント | `UTAVIDEO_FONT_DIRS=./fonts utavideo build`（相対パスは実行した場所から） |
| 名前の照合 | ファミリー名・フルネーム・PostScript 名・タイプグラフィック・ファミリー名と、大文字小文字を区別せずに照合。同じ名前のファイルはすべて libass に渡す |
| 一覧を作り直す | `~/.cache/utavideo/` を消す |

Aegisub で同じ見た目にするには、Aegisub 側にもフォントをインストールします。

## 概要欄とタイトル

`utavideo description` で `build/title.txt`・`build/description.txt` に書き出します。

| やりたいこと | 書き方 |
|---|---|
| 原曲・クレジット・素材を載せる | `song.original_urls`・`[[credits]]`・`[[materials]]` |
| 冒頭の文章・ハッシュタグ | `[description]` の `text`・`hashtags` |
| タイトルを手で決める | 曲の `description.title` |
| 同じ見出しに複数人を並べる / 役割ごとに分ける | `roles` の並びが同じ人は1つの見出しにまとまる |
| 見出しの記号・区切り・空行・順番 | ユーザー設定の `[description]`（`heading`・`original_heading`・`role_separator`・`name_url_separator`・`section_gap`・`hashtags_gap`・`order`） |
| タイトルの形 | ユーザー設定の `description.title`（`{title}`・`{artist}`・`{label}`・`{singers}`）・`singer_roles`・`singer_separator` |
| 毎回同じクレジット・ハッシュタグ | ユーザー設定の `[defaults]`（`new` / `init` が曲の toml にコピーする） |
| 自作の素材を検査で扱う | `[[materials]]` に `urls` を書かず `files` だけ書く（概要欄には出ない） |
| 公開したときの文章を残す | `build/title.txt`・`build/description.txt` を自分で `release/` にコピーする（`release` がそれらをどう扱うかは [commands.md](commands.md#release)） |

## 曲フォルダとコマンド

| やりたいこと | 書き方 |
|---|---|
| 曲フォルダの外から実行 | `-C <曲フォルダ>`（省略時はカレントディレクトリから親へ `utavideo.toml` を探す） |
| ファイルの置き場所 | toml のパスは相対（`utavideo.toml` から）か絶対。`src/` の分け方は自由。歌詞は `lyrics.file` |
| 作る場所・フォルダ名 | `new <パス>`（渡したパスがそのままフォルダになる） |
| 曲名・アーティスト | `new <パス> --title "…" --artist "…"`、`init --title "…" --artist "…"` |
| ファイル名を曲名と別にする | `new <パス> --slug <名前>`、`utavideo.toml` の `song.slug` |
| 雛形を自分用にする | Aegisub のスタイルマネージャのストレージからスタイルをコピーする。または自分用のファイルを置いたフォルダで `init`（既にあるファイルは残る） |

## 動画編集ソフトと組み合わせる

| やりたいこと | 書き方 |
|---|---|
| 歌詞だけの透過動画 | `utavideo overlay` → `build/overlay.mov`（背景のファイルは不要） |
| 編集ソフトで作った映像でプレビュー | その映像を `build/preview/bg.mp4` に置く（`preview-bg` を実行すると上書きされる） |

## 確かめる

| やりたいこと | 書き方 |
|---|---|
| サムネイルの下敷き | `utavideo thumbnail --bg-only` → `build/thumbnail/bg/<name>.png` |
| 実際に描画した .ass を見る | `build/.work/final.ass`・`preview.ass`・`overlay.ass`（自動のフェードと曲名表示が入っている） |
| 書き出す前に検査 | `utavideo check` |

## 設定とキャッシュの場所

環境変数 `XDG_CONFIG_HOME`・`XDG_CACHE_HOME` で変えられます（[一覧](config-reference.md#環境変数)）。

## 今は変えられないもの

- 出力の形式（[一覧](commands.md#出力の形式変更不可)）
- 曲名表示の区間・レイヤー・フェード・数
- 背景の重ね合わせ、アバターの合成、サムネイルごとの背景（[roadmap.md](roadmap.md)）
- サムネイルの形式（PNG だけ）
- 雛形の中身、1曲で複数の .ass
- サムネイルに描く .ass の時刻と加工の有無（[commands.md](commands.md#thumbnail)）
- 概要欄の通し番号・前後の動画へのリンク（[roadmap.md](roadmap.md)）
