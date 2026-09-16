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
| `\pos`・`\move` | `check` が警告する。重なりとはみ出しの検査から外す |
| `\fn` | そのフォントも探す。見つからなければエラー |
| `\r<スタイル名>` | そのスタイルが無ければエラー。フォントも探す |
| `\fs`・`\fscx`・`\fsp`・`\q`・`\N`・`\n`・`\h` | はみ出しの概算に反映する |

はみ出しの概算は `\bord` と縦書き（`@` 付きのフォント名）を反映しません。

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
| 拡大の方法 | `scale_flags`（ドット絵は `neighbor`） |
| 解像度・縦長 | `size` と .ass の `PlayResX`・`PlayResY` を同じ偶数にする。歌詞を入れた後は Aegisub の「解像度の変換（Resample Resolution）」 |
| フレームレート | `fps` |
| 画質・書き出しの速さ | `crf`（小さいほど高画質）・`preset` |

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
| 公開したときの文章を残す | `[description]` があれば `release` が動画と同じ名前の `.txt` を書く |

## 曲フォルダとコマンド

| やりたいこと | 書き方 |
|---|---|
| 曲フォルダの外から実行 | `-C <曲フォルダ>`（省略時はカレントディレクトリから親へ `utavideo.toml` を探す） |
| ファイルの置き場所 | toml のパスは相対（`utavideo.toml` から）か絶対。`src/` の分け方は自由。歌詞は `lyrics.file` |
| 作る場所・日付 | `new --root <場所> --date YYYYMMDD` |
| 曲名・アーティスト | `new "曲名" --artist "…"`、`init --title "…" --artist "…"` |
| 雛形を自分用にする | Aegisub のスタイルマネージャのストレージからスタイルをコピーする。または自分用のファイルを置いたフォルダで `init`（既にあるファイルは残る） |

## 動画編集ソフトと組み合わせる

| やりたいこと | 書き方 |
|---|---|
| 歌詞だけの透過動画 | `utavideo overlay` → `build/overlay.mov`（背景のファイルは不要） |
| 編集ソフトで作った映像でプレビュー | その映像を `build/preview/bg.mp4` に置く（`preview-bg` を実行すると上書きされる） |

## 確かめる

| やりたいこと | 書き方 |
|---|---|
| 実際に描画した .ass を見る | `build/.work/final.ass`・`preview.ass`・`overlay.ass`（自動のフェードと曲名表示が入っている） |
| 書き出す前に検査 | `utavideo check` |

## 設定とキャッシュの場所

環境変数 `XDG_CONFIG_HOME`・`XDG_CACHE_HOME` で変えられます（[一覧](config-reference.md#環境変数)）。

## 今は変えられないもの

- 出力の形式（[一覧](commands.md#出力の形式変更不可)）
- 曲名表示の区間・レイヤー・フェード・数
- 背景の重ね合わせ、アバターの合成（[roadmap.md](roadmap.md)）
- 雛形の中身、1曲で複数の .ass
- 概要欄の通し番号・前後の動画へのリンク（[roadmap.md](roadmap.md)）
