# コマンドリファレンス

各コマンドのオプション、読み書きするファイル、検査項目、出力の形式です。手順は [workflow.md](workflow.md) を参照してください。

## 共通

- `check`・`preview-bg`・`build`・`overlay`・`thumbnail`・`description`・`release`・`vertical-ass` は曲フォルダで実行します。`-C <曲フォルダ>`（`--project`）で指定でき、省略するとカレントディレクトリから親へ向かって `utavideo.toml` を探します
- `check`・`preview-bg`・`build`・`overlay`・`thumbnail` には ffmpeg と ffprobe が必要です
- 書き出しは `<名前>.partial.<拡張子>` に書いてから名前を変えます。失敗・中断しても、前に書き出したファイルは残ります
- 出力先のファイルを他のアプリ（動画プレイヤー、エクスプローラーのプレビューなど）で開いていると、WSL2 で Windows のドライブ（`/mnt/c` など）にある曲フォルダでは名前を変えられずに止まります。書き出したものは `.partial` の付いた名前で残るので、アプリを閉じて実行し直します（`release` も同じ）
- WSL2 で `/mnt/<ドライブ>/` 以下に書き出したときは、Windows のパスも表示します
- エラーがあると終了コード 1 で終わります

## new

```sh
utavideo new <パス> [--title <曲名>] [--artist <名前>] [--slug <名前>]
```

渡したパスに曲フォルダを作り、雛形のフォルダとファイルを置きます（構成は [project-layout.md](project-layout.md)）。フォルダ名はパスのままで、日付などは付けません。

| オプション | 既定値 | 内容 |
|---|---|---|
| `<パス>` | 必須 | 作る曲フォルダのパス（例: `work/20260916-song`） |
| `--title` | slug と同じ | `song.title` に書く |
| `--artist` | `""` | `song.artist` に書く |
| `--slug` | フォルダ名（先頭の `YYYYMMDD` は除く） | `song.slug` に書く（[名前の付け方](project-layout.md#名前の付け方)） |

- 省略したオプションは、端末で実行したときは入力を促します。パイプや CI から実行したときは聞かずに既定値を使います
- 決まった値は `utavideo.toml` に書き込みます。後から曲名を変えても、ファイル名は変わりません
- フォルダが既にあるとエラーです（既存のフォルダには `init` を使います）
- slug がファイル名に使えないとエラーです（端末では入力を促します）

## init

```sh
utavideo init [<フォルダ>] [--title <曲名>] [--artist <名前>] [--slug <名前>]
```

既存のフォルダに、足りないフォルダとファイルだけを作ります。既にあるファイルは移動も上書きもしません。オプションの決め方は `new` と同じです。

| オプション | 既定値 | 内容 |
|---|---|---|
| `<フォルダ>` | `.` | 対象のフォルダ（存在しないとエラー） |
| `--title` | slug と同じ | `song.title` に書く |
| `--artist` | `""` | `song.artist` に書く |
| `--slug` | フォルダ名（先頭の `YYYYMMDD` は除く） | `song.slug` に書く |

`src/`（`src/ref/` を除く）に音源と背景がちょうど1つずつあれば、`utavideo.toml` の `audio.file`・`video.background` に設定します。対象の拡張子は、音源が wav / flac / mp3 / m4a / aac / ogg / opus、背景が [config-reference.md](config-reference.md#video) の `background` と同じです。

## check

```sh
utavideo check [-C <曲フォルダ>]
```

[検査項目](#検査項目)を調べ、曲名・音源の長さ・歌詞の行数・使うフォントのファイル・`release` で次に付く名前・サムネイルの名前と大きさ・縦用 .ass の場所と大きさ・ショートの名前を表示します。`[[thumbnails]]` があれば、すべてのサムネイルも検査します（[thumbnail](#thumbnail) の検査と同じ）。`[[shorts]]` があれば、縦用 .ass とすべてのショートの区間も検査します（[ショートの検査](#ショートの検査)）。`[[shorts]]` が無ければ、縦用 .ass のファイルがあっても見ません。

## preview-bg / build / overlay

```sh
utavideo preview-bg [-C <曲フォルダ>] [--vertical]
utavideo build [-C <曲フォルダ>]
utavideo overlay [-C <曲フォルダ>]
```

| コマンド | 出力 | 入るもの |
|---|---|---|
| `preview-bg` | `build/preview/bg.mp4` | 背景・曲名表示・音声（歌詞の行は入れない） |
| `preview-bg --vertical` | `build/preview/vertical-bg.mp4` | 縦型のショートの下敷き。背景を `vertical.size` に合わせたもの・曲名表示・音声（縦用 .ass の行は入れない） |
| `build` | `build/main.mp4` | 背景・歌詞・曲名表示・音声 |
| `overlay` | `build/overlay.mov` | 歌詞・曲名表示（背景は透明）・音声。背景のファイルは不要 |

- 書き出す前に[検査](#検査項目)し、エラーがあれば書き出しません。警告は表示して続けます
- `preview-bg` は、歌詞の行についての検査を行いません
- 動画の長さは音源の長さです
- 描画に使った .ass を `build/.work/final.ass`・`preview.ass`・`overlay.ass`・`vertical-preview.ass` に書きます（自動のフェードと曲名表示が入ったもの）

`--vertical` は、Aegisub でショートの区間を置き、縦用 .ass を組むときに開く下敷きを、曲の頭から終わりまで書き出します。

- 背景は `[video]` の `fit`・`scale_flags`・`pad_color` と `vertical.focus` で `vertical.size` に合わせます
- 曲名表示は、縦用 .ass の `overlay_text.style` のスタイルとフォントで描きます。縦用 .ass が要るので、`vertical-ass` の後に実行します
- `[[shorts]]` は無くてもかまいません（区間を置く前に使うため）。検査は[ショートの検査](#ショートの検査)の表の `preview-bg --vertical` の列のとおりです
- 縦型のショートの画面の作り方のうち、背景を縦に切り取る形だけに対応しています（本編をぼかした帯に置く形は [roadmap.md](roadmap.md)）

## thumbnail

```sh
utavideo thumbnail [-C <曲フォルダ>] [--name <name>] [--bg-only]
```

`[[thumbnails]]`（[config-reference.md](config-reference.md#thumbnails)）ごとに、背景の1フレームにサムネイル用の .ass を描いた PNG を書き出します。

| オプション | 既定値 | 内容 |
|---|---|---|
| `--name` | すべて | この `name` のサムネイルだけを検査して書き出す |
| `--bg-only` | 無効 | 文字を描かず、背景だけを書き出す（Aegisub で文字を組むときの下敷き） |

| 出力 | 入るもの |
|---|---|
| `build/thumbnail/<name>.png` | 背景のフレーム＋ .ass |
| `build/thumbnail/bg/<name>.png`（`--bg-only`） | 背景のフレームだけ |

- 背景が GIF・動画のときは、`at` 秒以降の最初のフレームを使います（繰り返しません）
- .ass は加工せずに、**0 秒**の状態を描きます。`lyrics.fade_ms` の自動フェードと `[overlay_text]` の曲名表示は入りません。`\t`・`\move`・`\k` なども 0 秒の状態になります
- 書き出したら、パスとバイト数を表示します
- 書き出す前に[検査](#検査項目)し、エラーがあれば1枚も書き出しません。`--bg-only` では、背景と `at` だけを検査します（.ass はまだ無くてよい）

次のときは止まります。

- `[[thumbnails]]` が無い（書き足し方を表示します）
- `--name` の名前が `[[thumbnails]]` に無い（ある名前を表示します）
- ffmpeg が正常に終わっても何も書き出さなかった（背景の終わり近くの `at` で、それ以降のフレームが無いとき）

## vertical-ass

```sh
utavideo vertical-ass [-C <曲フォルダ>]
```

縦型のショートに使う縦用 .ass を、本編の歌詞 .ass（`lyrics.file`）から作り、`vertical.lyrics`（既定は `src/vertical.ass`）に書きます（[config-reference.md](config-reference.md#vertical)）。作るのは最初の1回だけです。その後は Aegisub で直し、utavideo は書き換えません。本編の .ass も書き換えません。

作るもの:

- 本編の .ass の行を、コメント行も含めてすべて写す
- `[Script Info]` の `PlayResX`・`PlayResY` を `vertical.size` にする。`LayoutResX`・`LayoutResY` が2つともあれば、それぞれ x・y の比を掛けた値に書き直す（本編で PlayRes と同じなら `vertical.size` になる。片方だけなら `vertical.size`、無ければ足さない。理由は [検証記録](verification/20260917-vertical-ass.md)）
- `[Aegisub Project Garbage]` の `Video File:` を、縦用 .ass から見た `build/preview/vertical-bg.mp4` の相対パスにする。`Audio File:` が本編の下敷きと同じなら、それも同じパスにする。そうでない `Audio File:` と `Keyframes File:`・`Timecodes File:` の相対パスは、本編の .ass と縦用 .ass のフォルダが違っても開けるよう、縦用 .ass から見たパスに付け替える（絶対パスと、`?video` などのパスでない値はそのまま）。`Video AR Mode`・`Video AR Value`・`Video Zoom Percent` は消す
- スタイル `Short`・`VerticalBand` を足す（既にあれば足さない）。どちらも変換後の `Lyrics` の写しで、`VerticalBand` は上中央揃え。`Lyrics` が無ければ最初のスタイルを写す

大きさと座標の変換（x の比は `vertical.size` の幅 ÷ 本編の `PlayResX`、y の比は高さ ÷ `PlayResY`。「幅の比」は x の比）:

| 種類 | 対象 | 変換 |
|---|---|---|
| 座標 | `\pos`・`\move`（5つ目・6つ目の時刻は変えない）・`\org`・矩形の `\clip`・`\iclip` | x・y をそれぞれの比で |
| 大きさ（スタイル） | `Fontsize`・`MarginL`・`MarginR`・`MarginV`・`Outline`・`Shadow`・`Spacing` | 幅の比で |
| 大きさ（行） | 行の `MarginL`・`MarginR`・`MarginV`、`\fs`・`\fsp`・`\bord`・`\xbord`・`\ybord`・`\shad`・`\xshad`・`\yshad`・`\blur` | 幅の比で |
| ぼかしの回数 | `\be` | 幅の比の2乗を掛けて四捨五入する（ぼかしの幅が回数の平方根に比例するため）。1回以上なら1回以上に保つ |
| 変えない | `\fs+N`・`\fs-N`（今の大きさからの相対指定）、`\fscx`・`\fscy` などの倍率、引数の数が合わないタグ | そのまま |
| 変換しない | 図形（`\p1` など）の座標、ベクターの `\clip`・`\iclip` | そのまま。該当する行を警告で表示する |

- 数は小数第2位で丸めます（余白は整数）
- 文字も余白も幅の比で一様に縮むので、本編で画面に収まっていた行は縦でも収まり、文字は小さくなります
- 縁取り・影は `ScaledBorderAndShadow` の値によらず、同じ比で縮めます

次のときは止まります。

- `vertical.lyrics` のファイルが既にある（上書きしない。作り直すときは消してから実行する）
- `lyrics.file` のファイルが無い、読めない、`PlayResX`・`PlayResY` が無い

## description

```sh
utavideo description [-C <曲フォルダ>]
```

`utavideo.toml` のクレジット・素材から、タイトルを `build/title.txt`、概要欄を `build/description.txt` に書き出し、画面にも表示します。書式はユーザー設定で決まります（[config-reference.md](config-reference.md#ユーザー設定の-description)）。

- `[description]` がある曲では、[概要欄の検査](#検査項目)の結果も表示します
- ffmpeg は使いません

## release

```sh
utavideo release [-C <曲フォルダ>] [--version <音源のバージョン>] [--allow-stale]
```

`build/main.mp4` を `release/<slug>-<音源のバージョン>.<何本目か>.mp4` にコピーします。何本目かは `release/` にある同じ音源の動画から決まります（規則は [project-layout.md](project-layout.md#名前の付け方)）。書くのは `.mp4` だけです。概要欄は `release/` に置きません（[description](#description) の `build/` の出力を使います）。`release/` にある `.mp4` 以外のファイル（`.txt` など）は読まず、書き換えず、番号にも数えません。

| オプション | 既定値 | 内容 |
|---|---|---|
| `--version` | 音源のファイル名から（規則は [project-layout.md](project-layout.md#名前の付け方)） | 音源のバージョン。`v1.2` の形（小文字の `v`）。何本目かは指定できない |
| `--allow-stale` | 無効 | 入力が `build/main.mp4` より新しくてもコピーする |

次のときは止まります。

- `build/main.mp4` が無い
- 音源のバージョンが決まらない、または `vX.Y` の形でない
- 同じ音源のバージョンで、`build/main.mp4` と中身が同じ動画を既に公開している
- 同じ名前の `.mp4` が `release/` にある（上書きしない）
- `utavideo.toml`・音源・背景・歌詞のどれかが `build/main.mp4` より新しい（`--allow-stale` で無視）。ファイルの更新時刻で比べるので、`build` の後に `utavideo.toml` の動画に効かない項目（`[[thumbnails]]`・`[description]`・`[[credits]]` など）だけを変えたときも止まります。このときは `--allow-stale` を付けます

## 検査項目

### エラー（書き出さない）

| 対象 | 内容 |
|---|---|
| 設定 | `utavideo.toml` が無い、TOML の構文が不正、未知の項目や不正な値がある（`[[thumbnails]]` の `name` の文字・重複、`focus` の範囲、`at` の書式を含む）。ユーザー設定も同じ |
| 素材 | `audio.file`・`lyrics.file`・`video.background`（`overlay` では不要）のファイルが無い、背景の形式に対応していない、音源に音声が入っていない |
| 歌詞 | .ass が読めない、`PlayResX`・`PlayResY` が無い、`video.size` と違う、`LayoutResX`・`LayoutResY` が2つともあって縦横比が PlayRes と違う（文字が潰れて描かれる。縦横比が同じで大きさだけ違うのは問題ない）、未定義のスタイル（`\r` の切り替え先を含む）を使っている |
| 曲名表示 | `overlay_text.style` のスタイルが .ass に無い、`overlay_text.text` の書式が不正 |
| フォント | 使っているフォントが見つからない |
| サムネイル（`thumbnail`・`check`） | 背景が画像なのに `at` を書いた、`at` が背景の長さ以上（長さは ffprobe で取る） |
| サムネイルの .ass（`thumbnail`・`check`。`--bg-only` では見ない） | `file` が無い・読めない、`PlayResX`・`PlayResY` が無い、`size` と違う、`LayoutResX`・`LayoutResY` の縦横比が PlayRes と違う、未定義のスタイルを使っている、フォントが見つからない |
| 縦用 .ass・ショートの区間 | [ショートの検査](#ショートの検査) |
| 概要欄（`[description]` がある曲の `check`） | ユーザー設定の `description.title`・`description.heading` の書式が不正 |
| 実行環境 | ffmpeg・ffprobe が無い |

### 警告

| 対象 | 内容 |
|---|---|
| 歌詞の行 | `\pos`・`\move` を使っている、表示時間が 0 以下、音声が終わった後に始まる、音声の終わりで途中で切られる、同じスタイル・同じレイヤーで重なる、画面からはみ出しそう |
| サムネイルの .ass（`thumbnail`・`check`。`--bg-only` では見ない） | 0 秒に表示されない行（始まりが 0 秒より後、または終わりが 0 秒以前）、`\fad`・`\fade` のフェードインが 0 秒で終わっていない、画面からはみ出しそう（`\pos` の行は対象外なので、サムネイルではほとんど検査されない） |
| サムネイル（`thumbnail`・`check`） | 背景の長さを取得できず、`at` を確かめられない |
| 縦用 .ass・ショートの区間 | [ショートの検査](#ショートの検査) |
| `check` だけ | 音源のファイル名にバージョン（`vX.Y`）が無い、`song.artist` が空、本編の .ass にスタイル `Short` の行がある（区間は縦用 .ass に書く） |
| 概要欄（`[description]` がある曲の `check`） | `video.background` がどの `materials.files` にも無い、`materials.files` のファイルが無い、タイトルの `{singers}` に入る人がいない、タイトルが 100 文字・概要欄が 5000 バイトを超える、`<` か `>` を含む（YouTube の上限） |

はみ出しの概算で反映するタグは [customization.md](customization.md#utavideo-が読むタグ) を参照してください。

### ショートの検査

縦用 .ass（`vertical.lyrics`）と、そこに置くショートの区間の検査です。縦用 .ass の誤りで本編の `build`・`preview-bg`・`overlay` は止めません。`check` は `[[shorts]]` があるときだけ行い、エラーがあれば終了コード 1 にします。

| 条件 | 扱い | `check` | `preview-bg --vertical` |
|---|---|---|---|
| 本編の .ass（`lyrics.file`）の `LayoutResX`・`LayoutResY` の縦横比が PlayRes と違う | エラー | ○（[歌詞](#エラー書き出さない)の検査） | ○（本編の .ass があるとき） |
| 縦用 .ass が無い（`utavideo vertical-ass` で作れる、と表示）・読めない | エラー | ○ | ○ |
| 縦用 .ass の `PlayResX`・`PlayResY` が無い・`vertical.size` と違う、`LayoutResX`・`LayoutResY` の縦横比が PlayRes と違う、未定義のスタイル、曲名表示を出すのに `overlay_text.style` のスタイルが無い、フォント（曲名表示を含む）が見つからない | エラー | ○ | ○ |
| `[[shorts]]` の `name` に対応する区間の行が無い・2つ以上ある | エラー | ○ | － |
| スタイル `Short` の行が、コメント行でなく Dialogue になっている（画面に出てしまう） | エラー | ○ | － |
| 区間の終わりが始まり以前、区間の終わりが音源の長さを超える | エラー | ○ | － |
| どの `[[shorts]]` の `name` にも合わない区間の行がある | 警告 | ○ | － |
| 区間の頭か終わりが、歌詞の行の途中にかかる（行の時刻を表示） | 警告 | ○ | － |
| 区間に入る行の、[歌詞の行](#警告)と同じ警告（`\pos`・`\move`、表示時間、音源の長さ、重なり、はみ出し） | 警告 | ○ | － |
| 区間に入る縦の歌詞が、本編の .ass と食い違う（[本編との突き合わせ](#本編との突き合わせ)） | 警告 | ○ | － |

- 区間の行は、スタイル `Short` の行で、本文の前後の空白を除いたものを `name` と大文字小文字も含めて比べます
- 歌詞の行は、Dialogue 行のうち、スタイルが `Short` でも `Vertical` で始まるもの（`VerticalBand` など、縦だけの文字）でもない行です
- 区間に入る行は、区間と時刻が重なる Dialogue 行（`Short` を除く）です。区間の外の行（本編から写したまま使わない行）は、行ごとの検査をしません
- 区間の長さ・音源の長さを確かめられない区間（区間の行の誤り、音源が無いとき）では、区間の端と区間に入る行の検査をしません

#### 本編との突き合わせ

本編の歌詞を直して縦用 .ass を直し忘れたときに、警告で気づけるようにします。縦で改行・位置・大きさ・スタイルを変えただけなら（2行を1行にまとめても）、何も出ません。本編のスタイルの変更（フォント・色）は比べません。

| 比べるもの | 行 |
|---|---|
| 本編 | 本編の .ass の Dialogue 行のうち、縦と同じくスタイルが `Short` でも `Vertical` で始まるものでもない行 |
| 縦 | 縦用 .ass の歌詞の行（スタイルが `Short` でも `Vertical` で始まるものでもない行）。Dialogue 行とコメント行の両方 |
| 比べない | 図形（`\p1` など）だけの行。図形と文字が混ざった行は、図形の部分を除いた文字を比べます |
| 文字から除くもの | タグ（`{...}`）・`\N`・`\n`・`\h`・空白（全角の空白も） |

1. 縦の行を、本編の行のうち**重なる時間がいちばん長い**行に割り当てます。同じ長さなら、文字を含む行、文字が同じ行、縦の文字を含む行（縦で2つに分けた行の後半を、時刻の重なる次の行に取られないため）、スタイルが同じ行、レイヤーが同じ行、まだ割り当てていない行、.ass の先の行の順に選びます
2. 区間に入る本編の行ごとに、割り当てた縦の行を見ます（下の表）。本編の続きの行までつなぐと食い違いが消えるなら、つないだものを1つの行として見ます（本編の2行を縦で1行にまとめたとき）

| 割り当てた縦の行 | 結果 |
|---|---|
| 文字のある Dialogue 行がある | その文字を開始の順につなぎ、本編の文字と違えば警告（両方の文字を表示）。その最初の開始・最後の終わりと、本編の行の開始・終わりの差が **10 ミリ秒**を超えれば警告 |
| 無い、または文字の無い行だけ | 本編と同じ文字のコメント行があれば、縦で出さないことにした行とみなし、何も出さない。無ければ警告（対応する行が無い）。本編の行の文字が空なら出さない |

3. 区間に入る縦の Dialogue 行のうち、時刻の重なる本編の行が無いもの（文字が空の行を除く）を警告します

| 起きたこと | 結果 |
|---|---|
| 本編で誤字を直し、縦を直し忘れた | 警告（文字） |
| 本編に行を足した | 警告（対応する行が無い） |
| 本編の行を消した | 警告（時刻の重なる本編の行が無い、または隣の行の文字） |
| 本編の行の時刻だけ変えた | 警告（時刻） |
| 縦で改行・位置・大きさ・スタイルを変えた、1行を2つの行に分けた、本編の2行を1行にまとめた | 何も出ない |
| 縦で行を出さないことにした | その行を、文字はそのままでコメント行にすれば、何も出ない |
| 本編に、歌詞と時刻の重なる別の行（`Comment` スタイル、掛け合い、ハモリ）がある | 何も出ない |
| 隣の行と数十ミリ秒重なっている | 何も出ない |

- 割り当てには区間の外の行も使い、警告は区間に入る行についてだけ出します。区間の端をまたぐ行を2つに分けていても、両方をつないで比べます
- 本編の .ass が無いときは、突き合わせをしません

## 出力の形式（変更不可）

| 出力 | 映像 | 音声 |
|---|---|---|
| `build/main.mp4` | H.264（`video.crf`・`video.preset`）、yuv420p、BT.709 | AAC 320kbps、48kHz |
| `build/preview/bg.mp4`・`build/preview/vertical-bg.mp4` | H.264（ultrafast、CRF 28、15 フレームごとにキーフレーム） | AAC 160kbps、48kHz |
| `build/overlay.mov` | ProRes 4444（アルファ付き）、BT.709 | PCM 24bit、48kHz |
| `build/thumbnail/<name>.png`・`build/thumbnail/bg/<name>.png` | PNG（RGB 8bit、圧縮レベル 9） | なし |
