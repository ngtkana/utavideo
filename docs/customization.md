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

`preview-bg` が縦用 .ass を作るときは、座標と大きさのタグを縦の解像度に変換します（[対象のタグ](commands.md#preview-bg--build--overlay)）。

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

## 曲名カード

最初の間奏など、一部の区間だけ曲名をロゴのように大きく出したいときは、新しい仕組みは使わず、歌詞の .ass に直接 `Dialogue` 行を書きます。区間はその行自体の Start・End でそのまま決まります（雛形にコメント行で例あり）。

| やりたいこと | 書き方 |
|---|---|
| 出す区間 | その `Dialogue` 行の Start・End |
| 見た目・大きさ | 曲名カード用のスタイル（雛形の `TitleCard`・`TitleCardSub`） |
| 複数パーツ（例:「曲名 / アーティスト」と「Cover: 歌った人」） | 別行にせず、`\r<スタイル名>` によるインラインのスタイル切り替えと `\N` 改行で1行にまとめる。例: `{\an8}曲名 / アーティスト\N{\rTitleCardSub}Cover: 歌った人` |
| 位置 | `\pos`。Aegisub の動画プレビュー上で「Visual typesetting」の Standard モードでドラッグして置ける（`\pos`・`\move` を使った行は `check` が警告します。曲名カードでは想定通りの使い方なので、出ても無視してかまいません） |
| 動き | `\move`・`\t`・`\fad` |
| 縁取り・影・ぼかし | スタイルの `Outline`・`Shadow`、オーバーライドタグ `\bord`・`\shad`・`\blur`・`\be`（[utavideo が読むタグ](#utavideo-が読むタグ)はすべて使える） |
| どうしても行を分けざるを得ない場合の時刻調整 | Aegisub の「Timing > Shift Times」で複数行をまとめて動かす |

曲名・アーティストは `.ass` に直接文字を打つので `utavideo.toml` の `[song]` とは別管理になりますが、曲ごとに1回書けばよく変更頻度が低いので許容します。

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

## 素材を重ねる（`[[layers]]`）

ユーザーが用意した画像・GIF・アルファ付き動画を、背景の上に重ねます。位置・大きさは区間を通して固定です（動かす演出はできません）。本編・`preview-bg`・`shorts`・サムネイルに共通で効きます。

| やりたいこと | 書き方 |
|---|---|
| 重ねる素材 | `[[layers]]` の `file`（画像・GIF・アルファ付き動画）。本編より短ければ繰り返す |
| 出す・消す区間 | `start`・`end`（`"1:23.5"` か秒の数）。省略した方は最初から・最後まで |
| 大きさ | `scale`（拡大率） |
| 位置 | `anchor`（9方向のアンカー）・`margin`（アンカーの辺からの距離。負の値で画面外に出せる） |
| 歌詞との前後関係 | `layer`。`.ass` の `Layer` と同じ尺度で、負なら歌詞の奥、0 以上（既定）なら歌詞の手前 |
| 複数の素材を重ねる | `[[layers]]` をもう1つ書き、`name`・`file`・`layer` などを変える |
| アルファ付き動画（VP9 / `.webm`）の書き出し | `-auto-alt-ref 0` を付けてエンコードする（付けないとアルファが欠けることがある） |
| `anchor`・`margin`・`scale` を素早く確かめる | `utavideo preview --at <表示される時刻> --watch`。macOS ならプレビュー.app で `build/.work/preview.png` を開いておくと、`utavideo.toml` を保存するたびに位置・大きさが更新された絵が自動で表示される（[commands.md](commands.md#preview)） |

## アバターの合成（`[avatar]`）

ブルーバック・グリーンバックで録画したアバター動画を、背景の上に合成します。撮影後にやることは3つ（クロマキー、位置と大きさ、タイミング）で、`[avatar]` 1つのテーブルに書きます（`utavideo avatar prepare` のような手動の前処理コマンドはなく、`build`・`check`・`preview` 等が内部で自動的に判定します。項目の全体は [config-reference.md](config-reference.md#avatar)）。

| やりたいこと | 書き方 |
|---|---|
| 録画を指定する | `avatar.file`（音声トラック入り） |
| 背景の色を抜く（クロマキー） | `key`（既定はブルーバック `"0x0000ff"`。グリーンバックは `"0x00ff00"`）・`similarity` |
| 被写体に残る色かぶりを消す | `despill`（`type` は `key` の色から自動判定） |
| 音の頭出し | `sync = "auto"`（既定）。録画の音声と `audio.file` の相互相関で自動的に求め、`check`・`build` がズレの秒数と際立ち（z 値）を表示する |
| 際立ちが低くて自動推定を信頼できないとき | `sync` に秒数を直接書いて手動指定する（際立ちが低い理由の多くは、録画の音声にノイズが多い・曲の一部しか重なっていない、など） |
| 動きの遅延を合わせる | `delay_ms`（手動。モーションキャプチャ・描画の遅延ぶん、動きが録画の音声より遅れる分を目視で測って入力する。機材ごとに一度決めたら基本固定） |
| 大きさ・位置・前後関係 | `scale`・`anchor`・`margin`・`layer`（`[[layers]]` と同じ書き方・同じ尺度。曲を通して固定） |
| `anchor`・`margin`・`scale` を素早く確かめる | `utavideo preview --at <表示される時刻> --watch`（[[layers]] と同じ。[commands.md](commands.md#preview)） |

- キー抜き・頭出し済みの中間動画は `build/.work/` に自動でキャッシュされ、`file`・`key`・`similarity`・`despill`・`sync`・`delay_ms` が前回と変わっていなければ作り直しません（60fps などの重い録画に毎回キーをかけずに済む）
- 縦型のショート・サムネイルにも、本編と同じ位置・大きさで重なります（縦だけ別の位置に置くことはまだできません。[roadmap.md](roadmap.md)）
- クロマキーの品質が実用に届かないときは、utavideo 側では ML マッティング等の高品質化はしません。録画側でアルファ付き録画（OBS + `alphaPacker` 等）に切り替えてください

## サムネイル

`utavideo thumbnail` で `build/thumbnail/<name>.png` に書き出します。手順は [workflow.md](workflow.md#9-サムネイルを作る)。

| やりたいこと | 書き方 |
|---|---|
| 文字の位置・見た目 | `[[thumbnails]]` の `file` の .ass。Aegisub で `utavideo preview-bg --target thumbnail` の下敷き（`build/thumbnail/bg/<name>.png`）を開いて組む |
| 背景の GIF・動画のどの時刻を使うか | `at`（`"1:23.5"` か秒の数） |
| 正方形などのサイズ違いを足す | `[[thumbnails]]` をもう1つ書き、`name`・`file`・`size` を変える。.ass の PlayRes も `size` に合わせる |
| サイズ違いで背景の残す位置を変える | そのサムネイルの `focus` |
| 1枚だけ書き出す | `thumbnail --name <name>` |
| 曲名・アーティストを直す | 雛形の `src/thumbnail.ass` には作ったときの `song` が書き込まれている。`song` を直しても変わらないので、.ass も直す |
| 図形 | .ass の `\p`・`\clip` |
| 画像・GIF・アルファ付き動画を重ねる | `[[layers]]`（[素材を重ねる](#素材を重ねるlayers)）。`start`・`end` の区間に `at`（無ければ 0 秒）が入っているものだけを重ねる |

サムネイルごとに別の背景を使うことはまだできません（[roadmap.md](roadmap.md)）。

## 縦型のショート

縦型のショートに使う歌詞は、本編とは別の縦用 .ass に組みます。手順は [workflow.md](workflow.md#10-ショートの縦用-ass-を作り区間を置く)。

縦型のショートは、本編の映像を上下中央に置き、ぼかした帯を上下に敷く画面（blur）で作ります。曲名表示（`overlay_text`）は上下の帯に自動で入ります。

| やりたいこと | 書き方 |
|---|---|
| 縦用 .ass を作る | `[vertical]` を書いてから `utavideo preview-bg`。無ければ本編の .ass のスタイルだけを写し、幅の比で縮める（歌詞は本編の映像に入るので行は写さない） |
| 縦の解像度 | `vertical.size`（縦用 .ass を作る前に決める。後から変えるなら、縦用 .ass の PlayRes も同じにする） |
| 縦用 .ass の場所・名前 | `vertical.lyrics` |
| 縦用 .ass を作り直す | 縦用 .ass を消してから `preview-bg`（直した内容は残らない） |
| 縦の下敷き（Aegisub で開く） | `preview-bg`（`build/preview/vertical-bg.mp4`。`[vertical]` があれば本編の下敷きと一緒に作る） |
| 縦で背景のどこを残すか | `vertical.focus`（既定は `video.focus`）。上下の帯の切り取りに効く |
| 切り抜く区間 | 縦用 .ass に、スタイル `Short` のコメント行を置き、本文をショートの名前にする。`utavideo.toml` に同じ `name` の `[[shorts]]` を書く（書き方の詳細は[区間の書き方（文法）](workflow.md#区間の書き方文法)） |
| ショートを何本も作る | 区間の行と `[[shorts]]` を、名前を変えて並べる |
| 帯に文字を足す（曲名表示以外） | 縦用 .ass に、スタイル名を `Vertical` で始める行を足す（例: `VerticalBand`） |
| ショートを書き出す | `utavideo shorts`（`--name <name>` で1本だけ） |
| 区間ごとに背景の残す位置を変える | `shorts[].focus`（既定は `vertical.focus`） |
| 同じ区間の 16:9 版も書き出す | `shorts[].wide = true`（`build/shorts/wide/<name>.mp4`） |
| 区間の端の音声のフェード | `vertical.audio_fade_ms`（16:9 版にも効く）。映像はフェードしない |
| 縦だけ曲名表示を消す | `vertical.overlay_text = false`（本編と 16:9 版には出たまま、帯からも消える） |
| 帯に出る曲名表示の位置を細かく変える | 縦用 .ass のスタイル `VerticalBand` の `MarginV`（既定は縦用 .ass を作った時点の、本編を中央に置いたときの帯に合わせて自動計算） |
| 帯の文字にフェードを入れない | スタイル名を `Vertical` で始める（自動のフェードを入れない。`\fad` を自分で書けば効く） |

帯のぼかしの強さは変えられません（帯が落ち着いて見える強さに決めています。[検証記録](verification/20260919-blur-band.md)）。

## 音源と公開

| やりたいこと | 書き方 |
|---|---|
| 音源 | `audio.file`。ffmpeg が読める形式なら可（`init` の自動設定は wav / flac / mp3 / m4a / aac / ogg / opus） |
| 歌唱練習用の動画（inst）の音源 | `inst.audio`。本編の `audio.file` とは別に、声を抜いた伴奏などを指定する必須の項目（[commands.md](commands.md#inst)） |
| inst に楽譜を表示 | `[inst.score]` の `file` に MuseScore 4 の楽譜(`.mscz`)を指定する。MuseScore 4 のインストールが要る。`first_bar_offset_s` で1小節目と音源の頭を合わせ、`play_x`・`y` で画面上の位置を決める（[config-reference.md](config-reference.md#score)） |
| バージョン | 音源のファイル名の `v1.2` など。公開する動画には、その音源で何本目かも付く（規則は [project-layout.md](project-layout.md#名前の付け方)） |
| 音源のバージョンを指定して公開 | `release --version v1.2`（小文字の `v`） |
| `build` の後に入力が変わっていても公開 | `release --allow-stale` |
| 公開ファイル名 | `song.title`（ファイル名に使えない文字は `_` になる） |

## フォント

| やりたいこと | 書き方 |
|---|---|
| 探す場所（全曲） | ユーザー設定の `font_dirs`（書くと既定の場所は探さない） |
| 探す場所（その場だけ） | 環境変数 `UTAVIDEO_FONT_DIRS`（`:` 区切り。`font_dirs` より優先） |
| 曲フォルダのフォント | `UTAVIDEO_FONT_DIRS=./fonts utavideo build`（相対パスは実行した場所から） |
| 名前の照合 | Windows platform のファミリー名・フルネームと、大文字小文字と Unicode の正規化（NFC / NFD）の違いを区別せずに照合。Mac platform の名前・PostScript 名・タイプグラフィック・ファミリー名は libass が照合しないため対象外（実測: [検証記録](verification/20260927-libass-font-matching.md)）。同じ名前のファイルはすべて libass に渡す |
| 描画のときの名前 | libass は名前をそのまま比べるので、書き出しに使う .ass ではフォント名をフォントファイルが実際に持つ表記に揃える（一律 NFC にはしない。macOS で名前をコピーすると NFD になりやすいが、フォント側の表記に合わせるので正しく描ける。元の .ass は変えない） |
| 使える名前を調べる | `utavideo fonts`（[commands.md](commands.md#fonts)）。`.ass` に書くのはフォント名です。`.ttc` などのファイル名ではありません |
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

## SNS の告知文

動画を投稿したら、`utavideo.toml` の `[[uploads]]` に URL を書き、`utavideo announce` で `build/announce.txt` に書き出します。長さは X の数え方で数えます（[commands.md](commands.md#長さの数え方)）。

| やりたいこと | 書き方 |
|---|---|
| 動画のリンクを載せる | `[[uploads]]` の `url`（1つの動画につき1つ。サイト名は URL から決まる） |
| 冒頭の文章・ハッシュタグ | `[announce]` の `text`・`hashtags` |
| 見出し | ユーザー設定の `announce.header`（`""` で出さない） |
| 作品の行の形・区切り | ユーザー設定の `announce.work`（`{title}`・`{artist}`・`{label}`・`{singers}`） |
| リンクの行の形 | ユーザー設定の `announce.link`（`{site}`・`{url}`） |
| サイト名・リンクの順番 | ユーザー設定の `announce.sites`（書いた順に並ぶ。書くと既定は丸ごと置き換わる） |
| 空行・ブロックの順番 | ユーザー設定の `announce.order`（`""` の位置に空行。書かなかったブロックは出さない） |
| 長さの警告の上限 | ユーザー設定の `announce.max_weight` |
| 毎回同じハッシュタグ | ユーザー設定の `[defaults].announce_hashtags`（`new` / `init` が曲の toml にコピーする） |
| 投稿前に文章だけ作る | `[[uploads]]` を書かずに `announce`（警告は出るが、リンクの無い下書きを書き出す） |

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
| サムネイルの下敷き | `utavideo preview-bg --target thumbnail` → `build/thumbnail/bg/<name>.png` |
| 数値・スタイルの調整を、本番の `build` を待たずに確かめる | `utavideo preview --at <時刻> [--duration <秒数>] [--watch]`（[commands.md](commands.md#preview)。`check` 相当の検査はしない） |
| 実際に描画した .ass を見る | `build/.work/final.ass`・`preview.ass`・`overlay.ass`（自動のフェードと曲名表示が入っている） |
| 書き出す前に検査 | `utavideo check` |

## 設定とキャッシュの場所

環境変数 `XDG_CONFIG_HOME`・`XDG_CACHE_HOME` で変えられます（[一覧](config-reference.md#環境変数)）。

## 今は変えられないもの

- 出力の形式（[一覧](commands.md#出力の形式変更不可)）
- 曲名表示の区間・レイヤー・フェード・数
- `[[layers]]`・`[avatar]` の位置・大きさを動かす演出、出力ごとの上書き・除外
- アバターの動きの遅延（`delay_ms`）の自動推定（口の形と音素が対応しないため、手入力にしている）
- サムネイルごとの背景（[roadmap.md](roadmap.md)）
- サムネイルの形式（PNG だけ）
- 雛形の中身、1曲で複数の .ass
- サムネイルに描く .ass の時刻と加工の有無（[commands.md](commands.md#thumbnail)）
- 概要欄の通し番号・前後の動画へのリンク（[roadmap.md](roadmap.md)）
- 告知文の対象のサイト（YouTube・ニコニコ動画だけ）、ショート動画の告知、長さの数え方
