# コマンドリファレンス

各コマンドのオプション、読み書きするファイル、検査項目、出力の形式です。手順は [workflow.md](workflow.md) を参照してください。

## 共通

- `check`・`preview-bg`・`preview`・`build`・`overlay`・`thumbnail`・`shorts`・`inst`・`description`・`release`・`announce`・`status`・`build-all` は曲フォルダで実行します。`-C <曲フォルダ>`（`--project`）で指定でき、省略するとカレントディレクトリから親へ向かって `utavideo.toml` を探します
- `sample`・`check`・`preview-bg`・`preview`・`build`・`overlay`・`thumbnail`・`shorts`・`inst`・`build-all` には ffmpeg と ffprobe が必要です。無ければ、何を入れればよいかを表示して始めに止まります
- 歌詞の描画には libass 付きの ffmpeg が必要です（[動作環境](../README.md#動作環境)）。無いと `preview-bg`・`preview`・`build`・`overlay`・`thumbnail`・`shorts`・`inst`・`build-all` は書き出す前に止まり、`check` は[エラー](#検査項目)として他の検査結果と一緒に出します。素材を合成するだけの `sample` には要りません
- `inst` はキー変更に rubberband フィルタを使いますが、無い ffmpeg では代わりに `asetrate`+`atempo` を使います（[inst](#inst)）
- 書き出しは `<名前>.partial.<拡張子>` に書いてから名前を変えます。失敗・中断しても、前に書き出したファイルは残ります
- 出力先のファイルを他のアプリ（動画プレイヤー、エクスプローラーのプレビューなど）で開いていると、WSL2 で Windows のドライブ（`/mnt/c` など）にある曲フォルダでは名前を変えられずに止まります。書き出したものは `.partial` の付いた名前で残るので、アプリを閉じて実行し直します（`release` も同じ）
- WSL2 で `/mnt/<ドライブ>/` 以下に書き出したときは、Windows のパスも表示します
- エラーがあると終了コード 1 で終わります（`preview` は検査を省略するため例外。[preview](#preview) 参照）

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
- `utavideo.toml` の1行目には、エディタの補完用の `#:schema`（[config-reference.md](config-reference.md#エディタの補完)）が入ります
- フォルダが既にあるとエラーです（既存のフォルダには `init` を使います）
- slug がファイル名に使えないとエラーです（端末では入力を促します）

## init

```sh
utavideo init [<フォルダ>] [--title <曲名>] [--artist <名前>] [--slug <名前>]
```

既存のフォルダに、足りないフォルダとファイルだけを作ります。既にあるファイルは移動も上書きもしません。オプションの決め方、新規に作る `utavideo.toml` への `#:schema` の埋め込みは `new` と同じです。

| オプション | 既定値 | 内容 |
|---|---|---|
| `<フォルダ>` | `.` | 対象のフォルダ（存在しないとエラー） |
| `--title` | slug と同じ | `song.title` に書く |
| `--artist` | `""` | `song.artist` に書く |
| `--slug` | フォルダ名（先頭の `YYYYMMDD` は除く） | `song.slug` に書く |

`src/`（`src/ref/` を除く）に音源と背景がちょうど1つずつあれば、`utavideo.toml` の `audio.file`・`video.background` に設定します。対象の拡張子は、音源が wav / flac / mp3 / m4a / aac / ogg / opus、背景が [config-reference.md](config-reference.md#video) の `background` と同じです。

## sample

```sh
utavideo sample <パス> [--font <フォント名>] [--small]
```

動作確認用の見本の曲フォルダを作ります。背景の静止画・音源は同梱の実素材、それ以外（ループ動画・GIF・inst 用の音源・フォント）はその場で合成するので、自分の曲を用意する前に一通りのコマンドを試せます。`new` が空の雛形（素材は自分で置く）なのに対して、`sample` は素材入りで、作った直後から書き出せます。

| オプション | 既定値 | 内容 |
|---|---|---|
| `<パス>` | 必須 | 作る見本の曲フォルダのパス。既にあるとエラー（作り直すときはフォルダごと消す） |
| `--font` | 同梱フォント（Noto Sans JP） | 歌詞に使う実在のフォント名 |
| `--small` | 無効 | 小さく速く作る（640x360・10fps・ultrafast）。テストと CI 用 |

作るものは 1920x1080・30fps・34 秒で、フォント込みで合計 8MB 程度です。途中で失敗したときは、作りかけのフォルダを消してから終わるので、同じパスでやり直せます。

| ファイル | 内容 |
|---|---|
| `utavideo.toml` | 架空の曲名・クレジット・素材。背景の変え方はコメントに書いてある（[エディタの補完](config-reference.md#エディタの補完)用の `#:schema` 付き） |
| `src/lyrics.ass` | 歌詞。警告の出る行がわざと入っている（下記） |
| `src/mix/sample-v1.0.flac` | 同梱の実素材（34 秒、器楽）。出所は見本の `README.md` |
| `src/mix/sample-inst-v1.0.flac` | inst（歌唱練習用の動画）用の音源（合成のサイン波、34 秒）。本編と別の音だと耳で分かる |
| `src/bg/loop.mp4` | カラーバー ＋ 5 秒で画面を横断する白い箱（合成）。背景の繰り返しが目で分かる |
| `src/bg/still.jpg` | 同梱の実素材（4:3）。`video.fit` を `"cover"`（上下が切り取られる）と `"contain"`（左右に余白が出る）で見比べられる。出所は見本の `README.md` |
| `src/bg/loop.gif` | `loop.mp4` と同じ絵の GIF（480x270・2 秒、合成）。GIF の背景と、拡大の効き方を試す用 |
| `src/fonts/NotoSansJP-Regular.ttf` | 同梱フォント Noto Sans JP（`--font` を渡したときは作らない） |
| `src/fonts/OFL.txt` | 同梱フォントのライセンス（SIL Open Font License） |
| `src/score.mscz` | `[inst.score]` の見本（見本用に作成したオリジナルの旋律、CC0）。`inst` の楽譜表示を試せる（MuseScore 4 のインストールが要る） |
| `README.md` | 試すコマンドの一覧と、実素材（背景・音源・楽譜）の出所 |

- 同梱フォントを使うときは、見本の曲フォルダで `UTAVIDEO_FONT_DIRS=src/fonts utavideo check` のように、コマンドごとに場所を渡します（`UTAVIDEO_FONT_DIRS` は探す場所を置き換えるので、`export` すると同じシェルで自分の曲に戻ったときに自分のフォントが見つかりません）
- 既定のまま実行すれば、実際の書体（Noto Sans JP）で見栄えを確かめられます。別の書体で確かめたいときは `--font` に手元のフォント名を渡します
- 見本は `check` で**警告が 2 件**出ます。警告の出方も見せるためで、`\pos` / `\move` を使っている行が 2 行と、空白も `\N` も無い長い行が 1 行入っています。はみ出しの警告は行の幅の概算から出すので、`--font` に細いフォントを渡すと出なくなることがあります
- 要らなくなったらフォルダごと消します

## fonts

```sh
utavideo fonts [名前]
```

`.ass` に書けるフォント名（`check` が照合する名前）を探します。曲フォルダの外でも実行できます。ffmpeg・ffprobe は要りません。

- 名前を渡さないとき: 探索先（`font_dirs`・`UTAVIDEO_FONT_DIRS`）を表示し、見つかったフォントを `<ファイル> | <名前>` の形で並べます。1つのファイルが複数の名前（ファミリー名・フルネームなど）を持つときは、名前ごとに1行になります
- 名前を渡したとき: その名前に一致するフォントファイルのパスだけを表示します。見つからなければ [検査項目](#エラー書き出さない)の「フォント」と同じメッセージで、終了コード 1 になります

## check

```sh
utavideo check [-C <曲フォルダ>]
```

[検査項目](#検査項目)を調べ、曲名・音源の長さ・歌詞の行数・使うフォントのファイル・`release` で次に付く名前・サムネイルの名前と大きさ・縦用 .ass の場所と大きさ・ショートの名前を表示します。`[avatar]` があり `sync = "auto"` なら、求めた頭出しのズレ（秒）と際立ち（z 値）も表示します。`[[thumbnails]]` があれば、すべてのサムネイルも検査します（[thumbnail](#thumbnail) の検査と同じ）。`[[shorts]]` があれば、縦用 .ass とすべてのショートの区間も検査します（[ショートの検査](#ショートの検査)。書き出しは [shorts](#shorts)）。`[[shorts]]` が無ければ、縦用 .ass のファイルがあっても見ません。

## preview-bg / build / overlay

```sh
utavideo preview-bg [-C <曲フォルダ>] [--target <target>]
utavideo build [-C <曲フォルダ>]
utavideo overlay [-C <曲フォルダ>]
```

| コマンド | 出力 | 入るもの |
|---|---|---|
| `preview-bg` | `build/preview/bg.mp4` | 背景・`[[layers]]`・`[avatar]`・曲名表示・音声（歌詞の行は入れない） |
| `build` | `build/main.mp4` | 背景・`[[layers]]`・`[avatar]`・歌詞・曲名表示・音声 |
| `overlay` | `build/overlay.mov` | 歌詞・曲名表示（背景・`[[layers]]`・`[avatar]` は無し）・音声。背景のファイルは不要 |

- 書き出す前に[検査](#検査項目)し、エラーがあれば書き出しません。警告は表示して続けます
- `preview-bg` は、歌詞の行についての検査を行いません
- 動画の長さは音源の長さです
- 描画に使った .ass を `build/.work/final.ass`・`preview.ass`・`overlay.ass`・`vertical-preview.ass` に書きます（自動のフェードと曲名表示が入ったもの）
- `build` は、書き出しに成功した後、使った入力の記録を `build/.work/main-inputs.json` に書きます（[release](#release) が比べる）。書き出しを始める前に前の記録を消すので、途中で止まったときは記録が残りません

### `--target`（下敷きの対象を選ぶ）

`preview-bg` は「Aegisub で何か手を入れる前に打つ」下敷き生成の唯一の入口です。`--target` を省略すると本編・縦型ショートの下敷き（上の表のとおり）、`thumbnail`・`thumbnail:<name>` を渡すとサムネイルの下敷きを書き出します。

| `--target` | 出力 | 内容 |
|---|---|---|
| （省略） | `build/preview/bg.mp4`・（`[vertical]` があれば）`build/preview/vertical-bg.mp4` | 本編・縦型ショートの下敷き |
| `thumbnail` | `build/thumbnail/bg/<name>.png`（すべての `[[thumbnails]]`） | サムネイルの下敷き |
| `thumbnail:<name>` | `build/thumbnail/bg/<name>.png`（指定した1本だけ） | サムネイルの下敷き |

- `--target thumbnail`・`thumbnail:<name>` では、背景と `at` だけを検査します（サムネイルの .ass はまだ無くてよい）。書き出したら、パスとバイト数を表示し、[status](#status) の記録対象にはしません
- 次のときは止まります: `[[thumbnails]]` が無い（書き足し方を表示）、`thumbnail:<name>` の `name` が `[[thumbnails]]` に無い（ある名前を表示）、ffmpeg が正常に終わっても何も書き出さなかった（背景の終わり近くの `at` で、それ以降のフレームが無いとき）

### 縦型のショートの下敷きと縦用 .ass

`utavideo.toml` に `[vertical]` があれば、`preview-bg` は本編の下敷きと一緒に、縦型のショートの下敷き（`build/preview/vertical-bg.mp4`）も、曲の頭から終わりまで書き出します。Aegisub でショートの区間を置き、縦用 .ass を組むときに使います。

縦用 .ass（`vertical.lyrics`。既定は `src/vertical.ass`）がまだ無ければ、本編の歌詞 .ass（`lyrics.file`）から自動で作ります。作るのは最初の1回だけです。その後は Aegisub で直し、utavideo は書き換えません（上書きしないので、作り直すときは縦用 .ass を消してから実行します）。本編の .ass も書き換えません。

縦用 .ass を作るときにするもの:

- 本編の .ass のスタイルだけを写す（歌詞は本編の映像に入るので、行は写さない）
- `[Script Info]` の `PlayResX`・`PlayResY` を `vertical.size` にする。`LayoutResX`・`LayoutResY` が2つともあれば、それぞれ x・y の比を掛けた値に書き直す（本編で PlayRes と同じなら `vertical.size` になる。片方だけなら `vertical.size`、無ければ足さない。理由は [検証記録](verification/20260917-vertical-ass.md)）
- `[Aegisub Project Garbage]` の `Video File:` を、縦用 .ass から見た `build/preview/vertical-bg.mp4` の相対パスにする。`Audio File:` が本編の下敷きと同じなら、それも同じパスにする。そうでない `Audio File:` と `Keyframes File:`・`Timecodes File:` の相対パスは、本編の .ass と縦用 .ass のフォルダが違っても開けるよう、縦用 .ass から見たパスに付け替える（絶対パスと、`?video` などのパスでない値はそのまま）。`Video AR Mode`・`Video AR Value`・`Video Zoom Percent` は消す
- スタイル `Short`・`VerticalBand` を足す（既にあれば足さない）。どちらも変換後の `Lyrics` の写しで、`VerticalBand` は上中央揃え。`Lyrics` が無ければ最初のスタイルを写す。`VerticalBand` の `MarginV` は、本編を中央に置いたときの帯にだいたい収まる値に計算し直す

スタイルの大きさの変換（幅の比 = `vertical.size` の幅 ÷ 本編の `PlayResX`）:

| 対象 | 変換 |
|---|---|
| `Fontsize`・`MarginL`・`MarginR`・`MarginV`・`Outline`・`Shadow`・`Spacing` | 幅の比で |

- 数は小数第2位で丸めます（余白は整数）
- 縁取り・影は `ScaledBorderAndShadow` の値によらず、同じ比で縮めます

縦の下敷きを書き出すとき:

- 本編の映像（本編の .ass の歌詞入り、`[[layers]]`・`[avatar]` も重ねる。曲名表示は入れません）を帯の上に置いた、完成図と同じ画面にします。曲名表示は帯（縦用 .ass の `VerticalBand` スタイル）に描きます。本編の合成とぼかしの分だけ、本編の下敷きより時間がかかります。描画に使った本編の .ass は `build/.work/vertical-preview-frame.ass` に書きます
- `[[shorts]]` は無くてもかまいません（区間を置く前に使うため）。検査は[ショートの検査](#ショートの検査)の表の `preview-bg` の列のとおりです
- 曲名表示は `vertical.overlay_text = false` で消せます（`shorts` と同じ）

次のときは止まります（縦の下敷きの分。本編の下敷きは別に[検査項目](#検査項目)のとおり止まります）。

- 縦用 .ass がまだ無いのに、`lyrics.file` のファイルが無い、読めない、`PlayResX`・`PlayResY` が無い

## preview

```sh
utavideo preview [-C <曲フォルダ>] [--at <時刻>] [--duration <秒数>] [--watch]
```

`utavideo.toml` の数値やスタイルを直すたびに、確認のためだけに本番の `build`（曲全体、`video.crf`・`video.preset`）を待つのは遅いので、指定した一瞬・短い区間だけをすばやく書き出します。`preview-bg` が歌詞を除いた曲全体の Aegisub 用の下敷きを作るのに対し、`preview` は歌詞・曲名表示・`[[layers]]`・`[avatar]` を含む完成に近い絵を、狭い範囲だけ速く確かめる用途です。

| オプション | 既定値 | 内容 |
|---|---|---|
| `--at` | `0` | 確認したい時刻（`"M:SS"` か秒の数） |
| `--duration` | 無指定 | この秒数だけの動画にする。無指定なら1フレームの静止画 |
| `--watch` | 無効 | `utavideo.toml`・歌詞（`lyrics.file`）・`[[layers]]` の各 `file`・`avatar.file`・背景（`video.background`）の変更を検知して自動的に作り直す（1秒間隔のポーリング。新しい依存は追加していない。`Ctrl+C` で終了） |

| `--duration` | 出力 | 中身 |
|---|---|---|
| 無指定 | `build/.work/preview.png` | `--at` の1フレーム（背景 ＋ `[[layers]]` ＋ `[avatar]` ＋ 歌詞 ＋ 曲名表示。フェードも入る） |
| あり | `build/.work/preview.mp4` | `--at` から `--duration` 秒（ffmpeg の ultrafast プリセット。`preview-bg` と同じ書き出しの速さ） |

- 出力先は毎回同じ名前に上書きします。macOS のプレビュー.app のように、ファイルの変更を検知して自動で再表示するビューアで開いておくと、保存するたびに表示が更新されます（Windows・Linux では、開きっぱなしで自動更新するビューアを別途探してください）
- `check` 相当の検査はしません。歌詞・フォント・素材にエラーがあっても、書き出せるところまではそのまま書き出し、検査で分かる内容は警告・エラーとして表示しますが、それだけでは止まりません（終了コードは 0 のままです）
- 音源（`audio.file`）か歌詞（`lyrics.file`）が読めないとき、`--at`・`--duration` の書式が不正なとき、`--duration` をフレームに丸めると長さ 0 になるときは、書き出さずにエラーで止まります（終了コード 1）
- `[[shorts]]` の区間指定とは独立しています。`--at`・`--duration` はコマンドラインだけで完結し、`utavideo.toml` は変更しません
- 動画・GIF の背景（`video.background`）は `build` と同じくループ再生されるので、`--duration` 無指定の静止画でも、素材の実長を超える `--at` は素材の頭からの繰り返しとして扱います

## thumbnail

```sh
utavideo thumbnail [-C <曲フォルダ>] [--name <name>]
```

`[[thumbnails]]`（[config-reference.md](config-reference.md#thumbnails)）ごとに、背景の1フレームにサムネイル用の .ass を描いた PNG を書き出します。背景だけの下敷き（`build/thumbnail/bg/<name>.png`）は [preview-bg の `--target`](#--target下敷きの対象を選ぶ) で書き出します。

| オプション | 既定値 | 内容 |
|---|---|---|
| `--name` | すべて | この `name` のサムネイルだけを検査して書き出す |

| 出力 | 入るもの |
|---|---|
| `build/thumbnail/<name>.png` | 背景のフレーム＋ `[[layers]]`（`at` の時刻に区間が入っているものだけ）＋ `[avatar]`（区間指定が無いので常に重なる）＋ .ass |

- 背景が GIF・動画のときは、`at` 秒以降の最初のフレームを使います（繰り返しません）
- .ass は加工せずに、**0 秒**の状態を描きます。`lyrics.fade_ms` の自動フェードと `[overlay_text]` の曲名表示は入りません。`\t`・`\move`・`\k` なども 0 秒の状態になります
- 書き出したら、パスとバイト数を表示します
- 書き出す前に[検査](#検査項目)し、エラーがあれば1枚も書き出しません
- 書き出しに成功した後、使った入力の記録を `build/.work/thumbnail-<name>-inputs.json` に書きます（[status](#status)が比べます）

次のときは止まります。

- `[[thumbnails]]` が無い（書き足し方を表示します）
- `--name` の名前が `[[thumbnails]]` に無い（ある名前を表示します）
- ffmpeg が正常に終わっても何も書き出さなかった（背景の終わり近くの `at` で、それ以降のフレームが無いとき）

## shorts

```sh
utavideo shorts [-C <曲フォルダ>] [--name <name>]
```

`[[shorts]]`（[config-reference.md](config-reference.md#shorts)）ごとに、縦用 .ass の区間を切り出した縦型のショートを書き出します。

| オプション | 既定値 | 内容 |
|---|---|---|
| `--name` | すべて | この `name` のショートだけを検査して書き出す |

| 出力 | 画面 | 使う .ass |
|---|---|---|
| `build/shorts/<name>.mp4` | 本編の映像（`[[layers]]`・`[avatar]` も重ねる）を `vertical.size` の幅いっぱいに縮めて上下中央に置き、上下の帯を背景だけをぼかして埋め、縦用 .ass の縦だけの文字（曲名表示を含む）を重ねる | 真ん中は本編の .ass、帯の上は縦用 .ass の、区間に入る `Vertical` で始まるスタイルの行 |
| `build/shorts/wide/<name>.mp4`（`wide = true`） | `build/main.mp4` と同じ画面（`video.size`・`video.focus`・`[[layers]]`・`[avatar]`） | 本編の .ass |

画面の作り方（本編の映像を帯の上に置く、blur 一本）:

- 本編の映像は `build/main.mp4` と同じ画面（`video.size`・`video.focus`・`video.fit`）に本編の .ass を描いてから、縦の幅に縮めます。高さが奇数にならないよう、偶数に丸めます（1080x1920 では 607.5 → 608）
- 上下の帯は、**背景だけ**をぼかした上に、縦用 .ass の縦だけの文字（曲名表示を含む）を重ねたものです。本編の歌詞は帯に写りません（本編の映像に入っています）
- 帯は背景を `cover` で `vertical.size` の 1/4 の大きさに切り取り（`shorts[].focus`）、`gblur`（縦の幅 1080 で `sigma=40` 相当）を掛けてから、元の大きさに戻したものです。ぼかしの強さは設定で変えられません（[検証記録](verification/20260919-blur-band.md)）
- 歌詞は本編の映像に入っているので、縦用 .ass の歌詞の行は描きません。帯に出す文字は、スタイル名を `Vertical` で始めます（`utavideo preview-bg` が作る `VerticalBand` など）
- 曲名表示は帯（`VerticalBand` スタイル）に入ります。`vertical.overlay_text = false` なら、そこからも消します
- 描画に使った本編の .ass は `build/.work/shorts/frame/<name>.ass` に書きます

- 区間の頭と終わりは、`round(時刻 × fps) / fps` でフレームに丸めます（Aegisub の時刻はセンチ秒なので、丸めないと映像が音声より最大1フレーム先に進みます）。映像・音声・.ass に同じ値を使います
- 背景は本編と同じコマを使います。`wide` の版のフレームは `build/main.mp4` の同じ区間と一致します（[検証記録](verification/20260918-shorts.md)）
- .ass の時刻はずらしません。区間の頭をまたぐ行の `\move`・`\fad`・`\k` が、本編と同じ状態で描かれます
- 音声は区間の端で `vertical.audio_fade_ms` のフェードをかけます。映像はフェードしません
- 曲名表示は `[overlay_text]` の書式を、帯（`VerticalBand` スタイル）に描きます。`vertical.overlay_text = false` なら縦には出しません（`wide` には出します）
- 自動のフェード（`lyrics.fade_ms`）は、`Vertical` で始まるスタイルの行には入れません（区間いっぱいに置く帯の文字が、繰り返し再生のつなぎ目で点滅しないため）
- fps・crf・preset・`video.fit` は `[video]` と同じです。出力の形式は `build/main.mp4` と同じです
- 描画に使った .ass を `build/.work/shorts/<name>.ass`（`wide` は `build/.work/shorts/wide/<name>.ass`）に書きます
- 書き出す前に[検査](#ショートの検査)し、エラーがあれば1本も書き出しません。`--name` を渡すと、そのショートだけを検査します（ほかのショートのエラーでは止まりません）
- 書き出しに成功した後、使った入力の記録を `build/.work/shorts-<name>-inputs.json` に書きます（[status](#status)が比べます。`wide` の版は個別の記録を持たず、この1本の記録で代表します）

次のときは止まります。

- `[[shorts]]` が無い（書き足し方を表示します）
- `--name` の名前が `[[shorts]]` に無い（ある名前を表示します）
- ffmpeg が正常に終わっても何も書き出さなかった

## inst

```sh
utavideo inst [-C <曲フォルダ>] [--keys <キー>] [--lyrics]
```

歌唱練習用に、キーを変えた伴奏の動画を `build/inst/<slug>-key<キー>.mp4`（例: `<slug>-key-1.mp4`、`<slug>-key+2.mp4`、`<slug>-key0.mp4`）に書き出します（[config-reference.md](config-reference.md#inst)）。既定では歌詞は描かず、曲名・アーティスト・キーだけを表示します。

| オプション | 既定値 | 内容 |
|---|---|---|
| `--keys` | `"0"` | 半音単位のキー。カンマ区切りで複数指定できる（例: `-1,-2,-3`）。キーごとに別ファイルを書き出す |
| `--lyrics` | 付けない | 本編と同じ歌詞も焼き込む（既定では曲名・アーティスト・キーだけ） |

- キーの変更には ffmpeg の `rubberband` フィルタを使います。使えない ffmpeg では、代わりに `asetrate`+`atempo` で変えます（音質は劣ります。どちらを使ったかは実行時に表示します）
- 音量は `loudnorm`（2パス）でそろえます（目標: 統合ラウドネス -16 LUFS、True Peak -1.5 dBTP、ラウドネスレンジ 11 LU）。計測は音源全体に対して1回だけ行い、`--keys` で複数指定したときも使い回します
- 背景は本編と同じです（`video.background`）。音源は本編と別に、`[inst]` の `audio` に指定します（声を抜いた伴奏など）
- 表示する文字は `[inst]` の `text`、スタイルは `[overlay_text]` の `style` です
- `[inst.score]` を設定すると、MuseScore 4 で作った楽譜（`.mscz`）を、音源のテンポに合わせて画面上を横スクロールで表示します（[config-reference.md](config-reference.md#score)）。MuseScore 4 のインストールが要ります（見つからない場所は環境変数 [`UTAVIDEO_MUSESCORE`](config-reference.md#環境変数) で指定できます）
  - `--keys` で指定したキーごとに、MuseScore CLIで楽譜も移調してから描きます。描いた楽譜のPNGは `build/.work/inst/score-key<キー>.png` に、キーごとに分けて書きます
  - 楽譜の帯は既定では画面の縦方向の中央に出るので、曲名・キーの表示（画面上部）や `--lyrics` の歌詞（画面下部）とは重なりません（`[inst.score]` の `y`）
  - 楽譜の1小節目のオフセット（`first_bar_offset_s`）＋理論値の総演奏時間が、音源の長さと3秒以上ずれていれば警告します（楽譜の小節数・間が音源と合っていないおそれがあるため。書き出しは止めません）
- `--lyrics` を付けると、`lyrics.file` の歌詞行も本編と同じ基準（[検査項目](#検査項目)のフォント・はみ出し・重なり等）で検査し、フェード（`lyrics.fade_ms`）も本編と同じように入れます。付けないときは歌詞の中身を問わず、曲名表示のスタイルがあるかだけを確かめます
- 書き出す前に検査し、エラーがあれば1本も書き出しません
- 描画に使った .ass を `build/.work/inst/key<キー>.ass` に書きます
- 書き出しに成功した後、キーごとに使った入力の記録を `build/.work/inst-key<キー>-inputs.json` に書きます（[status](#status)が比べます）

次のときは止まります。

- `--keys` が空、値が整数でない、重複している
- `[inst]` の `audio` が設定されていない、そのファイルが無い、`video.background` のファイルが無い、背景の形式に対応していない、音源に音声が入っていない（[検査項目](#検査項目)の「素材」と同じ）
- `lyrics.file` のファイルが無い（曲名表示のスタイルに使う）、`PlayResX`・`PlayResY` が無い、`video.size` と違う、`LayoutResX`・`LayoutResY` が2つともあって縦横比が `PlayRes` と違う
- `overlay_text.style` のスタイルが `lyrics.file` に無い、`[inst].text` の書式が不正
- `[inst.score]` を設定したときは、`file` のファイルが無い、MuseScore 4 の実行ファイルが見つからない、楽譜の変換・描画に失敗した
- `--lyrics` のときは、歌詞の行が未定義のスタイルを使っている、表示幅からはみ出しそう、など本編の check と同じ検査項目
- 音量の計測に失敗した
- ffmpeg が正常に終わっても何も書き出さなかった

## description

```sh
utavideo description [-C <曲フォルダ>]
```

`utavideo.toml` のクレジット・素材から、タイトルを `build/title.txt`、概要欄を `build/description.txt` に書き出し、画面にも表示します。書式はユーザー設定で決まります（[config-reference.md](config-reference.md#ユーザー設定の-description)）。

- `[description]` がある曲では、[概要欄の検査](#検査項目)の結果も表示します
- ffmpeg は使いません

## release

```sh
utavideo release [-C <曲フォルダ>] [--short <name>] [--version <音源のバージョン>] [--allow-stale]
```

`build/main.mp4` を `release/<slug>-<音源のバージョン>.<何本目か>.mp4` にコピーします。何本目かは `release/` にある同じ音源の動画から決まります（規則は [project-layout.md](project-layout.md#名前の付け方)）。書くのは `.mp4` だけです。概要欄は `release/` に置きません（[description](#description) の `build/` の出力を使います）。`release/` にある `.mp4` 以外のファイル（`.txt` など）は読まず、書き換えず、番号にも数えません。

`--short <name>` を付けると、本編の代わりに `build/shorts/<name>.mp4` を `release/<slug>-shorts-<name>-<音源のバージョン>.<何本目か>.mp4` にコピーします。ショートは公開する完成品という点で本編と変わらないため、同じ規則で `release/` に残します（issue #122）。何本目かは本編とは別に、ショート（`name`）ごとに数えます。`wide = true` のショートは、`build/shorts/wide/<name>.mp4` も `release/<slug>-shorts-<name>-wide-<音源のバージョン>.<何本目か>.mp4` として同時にコピーします（何本目かはこちらも別に数えます）。

- `wide = true` のショートは、通常版・`wide` 版の順に1本ずつコピーします。片方が成功した後にもう片方が失敗すると、次の実行では成功済みの側が「同じ内容が既にあります」で止まり、その回はもう片方のコピーまで進みません。`utavideo shorts` は常に両方を一緒に書き出すので、通常はここで内容がずれることはありません

| オプション | 既定値 | 内容 |
|---|---|---|
| `--short` | 無効（本編を release する） | `[[shorts]]` の `name`。指定するとそのショートを release する |
| `--version` | 音源のファイル名から（規則は [project-layout.md](project-layout.md#名前の付け方)） | 音源のバージョン。`v1.2` の形（小文字の `v`）。何本目かは指定できない |
| `--allow-stale` | 無効 | 書き出した後に入力が変わっていてもコピーする |

次のときは止まります。

- release する動画（`build/main.mp4`、または `--short` のときは `build/shorts/<name>.mp4`）が無い
- 音源のバージョンが決まらない、または `vX.Y` の形でない
- 同じ音源のバージョンで、中身が同じ動画を既に公開している
- 同じ名前の `.mp4` が `release/` にある（上書きしない）
- 書き出した後に、描画に効く入力が変わった（`--allow-stale` で無視）。変わった入力の名前を表示します

描画に効く入力は、`build` が記録したときと次のように比べます。

| 入力 | 比べるもの |
|---|---|
| 音源・背景・歌詞（`audio.file`・`video.background`・`lyrics.file`） | ファイルの中身 |
| `utavideo.toml` | 読み込んだ値から、描画に効かない項目（`song.slug`・`song.original_urls`・`[[credits]]`・`[[materials]]`・`[description]`・`[[uploads]]`・`[announce]`）を除いたもの。コメント・並び順・書き方の違いは比べない。`song.title`・`song.artist`・`song.label` は曲名表示に使えるので比べる |
| フォント | 使ったフォントファイルのパス・大きさ・更新時刻（中身は読まない） |

- 保存し直しただけのときや、`build` の後に概要欄の項目だけを変えたときは止まりません
- 確かめた一致を `build/.work/release-match.json`（`--short <name>` は `release-match-shorts-<name>.json`、`wide` は `release-match-shorts-<name>-wide.json`）に記録します。次回同じ対象を release・status したとき、出力の size・更新時刻が記録と同じなら、`release/` のファイルを読み直さずに記録を信じます
- 記録が無いとき（記録を始める前の版の `build`）や、記録の後に `build/main.mp4` が差し替わっているときは、`utavideo.toml`・音源・背景・歌詞のどれかの更新時刻が `build/main.mp4` より新しいと止まります
- フォントは、`build` で使ったファイルだけを見ます。同じ名前のフォントを別の場所に足して、使われるファイルが変わっても気付きません

## announce

```sh
utavideo announce [-C <曲フォルダ>]
```

`utavideo.toml` の曲の情報・`[announce]`・`[[uploads]]` の URL から、SNS の告知文を `build/announce.txt` に書き出し、画面にも表示します。X の数え方での長さも表示します。書式はユーザー設定で決まります（[config-reference.md](config-reference.md#ユーザー設定の-announce)）。

- 書き出す前に[告知文の検査](#検査項目)をします。エラーがあれば `build/announce.txt` を書かず、終了コード 1 で止まります（`description` と違い、誤った URL の告知文を投稿しないため）。警告だけなら書き出します
- `[[uploads]]` が無いときは「リンクがありません」と警告し、リンクの無い下書きを書き出します（投稿前に文章だけ作れます）。`check` はこの警告を出しません
- URL を開いて確かめることはしません（動画の公開と告知を同時に予約できるように）
- ffmpeg は使いません

### 受け付ける URL

サイトは URL のホストで判定します。ホストは完全一致か、そのサブドメインで比べます（`youtube.com.example` は通しません）。`https://` で始まらない URL はエラーです。

| サイト（`sites` のキー） | ホスト | 受け付ける形 |
|---|---|---|
| `youtube` | `youtube.com`・`*.youtube.com`・`youtu.be` | `/watch?v=ID`・`youtu.be/ID`。ID は `[A-Za-z0-9_-]` の 11 文字。`si` などの共有用のパラメータは無視する。`t`・`list`（`#t=30` のような fragment の `t` も）が付いていたら警告（動画の頭から再生されない）。`/shorts/`・`/live/` などはエラー |
| `niconico` | `nicovideo.jp`・`*.nicovideo.jp`・`nico.ms` | `/watch/ID`・`nico.ms/ID`。ID は `sm`・`so`・`nm` と数字。`from` が付いていたら警告（動画の頭から再生されない）。ほかのパラメータは無視する |

リンクは、ユーザー設定の `announce.sites` に書いた順に並べます。同じサイトの URL が2つあるとき、`sites` に無いサイトの URL があるときはエラーです（メッセージに `sites` に足す行の例を出します）。

### ハッシュタグ

X（twitter-text）でハッシュタグとしてつながる文字は、文字・結合文字・数字と、`_`・`・`・`〜`・`～`・`゛`・`゜`・`゠`・`〃`・`·` など一部の記号だけです。`[announce].hashtags` に `-`・`.`・`!`・`&`・`'`・`♪` などそれ以外の文字があるとき（そこでタグが切れる）と、文字を1つも含まない（数字や `_` だけの）ときはエラーです。

### 長さの数え方

[twitter-text の config/v3.json](https://github.com/twitter/twitter-text/blob/master/config/v3.json) の規則で数えます（[検証記録](verification/20260917-announce.md)）。

- 書き出す全文から末尾の改行を除き、NFC に正規化してから数えます
- 1文字（コードポイント）の重みは 2 です。U+0000–U+10FF・U+2000–U+200D・U+2010–U+201F・U+2032–U+2037 だけ 1 です（`»` と改行は 1、`【】『』・…` と全角空白は 2）
- URL は長さによらず 23 です。`https://`・`http://` で始まるものと、`example.com` のようなスキームの無いドメインを URL とみなします。スキームの無いものは、TLD が twitter-text の一覧にあるときだけ URL とみなします（`Mr.Children`・`feat.Ado` は URL ではない）。`text` に手で書いた URL も数えます。URL の形の細かい判定（使える文字・パスの終わり）は twitter-text より簡易です
- X は ZWJ でつないだ絵文字や肌の色の付いた絵文字を1つで 2 と数えますが、utavideo は部品ごとに数えるので多めになります（上限を超えない側に倒れます）

## status

```sh
utavideo status [-C <曲フォルダ>]
```

`build/main.mp4`・[description](#description)・[announce](#announce)・`[[shorts]]`・`[[thumbnails]]`・[inst](#inst)・[release](#release) の今の状態を一覧します。`check` が「今書き出しても大丈夫か」を検査するのに対し、`status` は「前回書き出したときから何が変わったか」を見ます。差分の無い項目は何も表示せず、変わっている項目だけを並べます。すべて差分が無ければ「クリーンです（差分はありません）」とだけ表示します。

| 項目 | 表示する条件 |
|---|---|
| main | `build/main.mp4` が無い（未生成）。または [release](#release) と同じ基準で、書き出した後に入力が変わっている（古い） |
| 概要欄 | `build/title.txt`・`build/description.txt` のどちらかが無い（有無だけを見ます。中身が古いかは見ません） |
| 告知文 | `build/announce.txt` が無い（有無だけを見ます） |
| ショート（`[[shorts]]` があるとき、1本ごと） | 出力（`build/shorts/<name>.mp4`）が無い。または縦用 .ass・本編歌詞・音源・背景・設定のいずれかが、書き出した後に変わっている |
| ショートの release（ショートの出力が最新のとき、1本ごと。`wide = true` なら2本） | [release](#release) と同じ基準で、音源のバージョンが分からない・まだ release していない・release 済みの内容と違う |
| サムネイル（`[[thumbnails]]` があるとき、1本ごと） | 出力（`build/thumbnail/<name>.png`）が無い（`preview-bg --target thumbnail` の実行だけでは生成済みになりません）。またはサムネイルの .ass・背景・設定のいずれかが、書き出した後に変わっている |
| inst（`build/inst/` に実在するキーごと） | 本編歌詞・音源・背景・設定のいずれかが、書き出した後に変わっている |
| release | 音源のバージョン（`vX.Y`）が `audio.file` の名前から分からない。まだ release していない。`build/main.mp4` と release 済みの内容が違う（次に release したときのファイル名を表示します） |

- main が未生成・古いときは release の行を表示しません（先に `build` を促します）。ショートも同様に、そのショートの出力が未生成・古いときは、そのショートの release の行を表示しません（先に `shorts` を促します）
- ショート・サムネイル・inst の「変わった」判定は、歌詞・設定ファイル自体の変化だけを見ます。フォントファイル単体の差し替えは検出しません
- inst は `--keys` で任意のキーを指定でき、`[[shorts]]` のような事前宣言された個数を持たないので、`build/inst/` に実在するキーだけを対象にします（一度も inst していなければ何も表示しません）
- ffmpeg は使いません

## build-all

```sh
utavideo build-all [-C <曲フォルダ>]
```

[build](#preview-bg--build--overlay)・[description](#description)・[announce](#announce)・[thumbnail](#thumbnail)（`shorts`・`inst`・`preview-bg`・`overlay`・`release` は対象外）について、今作れるものをまとめて作ります。対象ごとに、次のいずれかに分類します。

| 状態 | 意味 | 表示 |
|---|---|---|
| 対象外 | この曲では使っていない（`[[thumbnails]]` が無い） | 何も出しません |
| 要対応 | 書き出す前の[検査](#検査項目)でエラーがある。多くは Aegisub 等での作業待ちです | 対象名とエラーの内容を表示し、書き出しません |
| 済み（build・thumbnail のみ） | 既に最新の出力があります（[status](#status)の main・サムネイルと同じ基準） | 対象名だけを表示します |
| 実行 | 上記のいずれでもありません | 対象名と出力先を表示して書き出します |

`description`・`announce` は生成コストが低く ffmpeg も使わないため、済み判定をせず、要対応でなければ毎回実行し直します（`[[uploads]]` が無いことは、既存の `announce` コマンドと同じく警告どまりとし、要対応にはしません）。

すべて「済み・対象外」なら「クリーンです（作るものはありません）」とだけ表示します。

- 要対応の対象があっても終了コード 0 です（利用者への案内であり、`build-all` 自体の失敗ではありません）。実行しようとした対象が想定外のエラーで失敗したときだけ、終了コード 1 で止まります
- 書き出す対象は、それぞれのコマンド（`build`・`description`・`announce`・`thumbnail`）と同じ検査をもう一度行い、警告もあわせて表示します（分類の時点ではエラーの有無しか見ていないため）。分類してから書き出すまでの間に状態が変わり、announce・thumbnail でエラーになったときは、書き出さずに終了コード 1 で止まります（`description` は元のコマンドと同じく、エラーがあっても書き出します）
- `build` は既存の `build` コマンドと同じ処理をそのまま呼ぶので、検査を2回行います（`status` の判定と、書き出し前の検査）

## 検査項目

### エラー（書き出さない）

| 対象 | 内容 |
|---|---|
| 設定 | `utavideo.toml` が無い、TOML の構文が不正、未知の項目や不正な値がある（`[[thumbnails]]` の `name` の文字・重複、`focus` の範囲、`at` の書式、ハッシュタグの重複、`announce.order` の `""` 以外の重複、`announce.sites` の知らないキーを含む）。ユーザー設定も同じ |
| 素材 | `audio.file`・`lyrics.file`・`video.background`（`overlay` では不要）のファイルが無い、背景の形式に対応していない、音源に音声が入っていない |
| 歌詞 | .ass が読めない、`PlayResX`・`PlayResY` が無い、`video.size` と違う、`LayoutResX`・`LayoutResY` が2つともあって縦横比が PlayRes と違う（文字が潰れて描かれる。縦横比が同じで大きさだけ違うのは問題ない）、未定義のスタイル（`\r` の切り替え先を含む）を使っている |
| 曲名表示 | `overlay_text.style` のスタイルが .ass に無い、`overlay_text.text` の書式が不正 |
| フォント | 使っているフォントが見つからない |
| アバター（`[avatar]` がある曲） | `file` のファイルが無い、形式に対応していない、`sync = "auto"` で際立ち（z 値）が低すぎる（5 未満。求めたズレを信頼できないので、`sync` に秒数を直接書く） |
| サムネイル（`thumbnail`・`check`） | 背景が画像なのに `at` を書いた、`at` が背景の長さ以上（長さは ffprobe で取る） |
| サムネイルの .ass（`thumbnail`・`check`。`preview-bg --target thumbnail` では見ない） | `file` が無い・読めない、`PlayResX`・`PlayResY` が無い、`size` と違う、`LayoutResX`・`LayoutResY` の縦横比が PlayRes と違う、未定義のスタイルを使っている、フォントが見つからない |
| 縦用 .ass・ショートの区間 | [ショートの検査](#ショートの検査) |
| 概要欄（`[description]` がある曲の `check`） | ユーザー設定の `description.title`・`description.heading` の書式が不正 |
| 告知文（`announce`、`[announce]` がある曲の `check`） | ユーザー設定の `announce.work`・`announce.link` の書式が不正、`[[uploads]]` の URL が[受け付ける形](#受け付ける-url)でない・同じサイトが2つある・サイトが `announce.sites` に無い、`[announce].hashtags` に [X でタグが切れる文字](#ハッシュタグ)がある |
| 実行環境 | ffmpeg で `subtitles` フィルタ（libass）が使えない（ffmpeg・ffprobe が無いときは検査を始める前に止まります） |

### 警告

| 対象 | 内容 |
|---|---|
| 歌詞の行 | `\pos`・`\move` を使っている、表示時間が 0 以下、音声が終わった後に始まる、音声の終わりで途中で切られる、同じスタイル・同じレイヤーで重なる、画面からはみ出しそう |
| サムネイルの .ass（`thumbnail`・`check`。`preview-bg --target thumbnail` では見ない） | 0 秒に表示されない行（始まりが 0 秒より後、または終わりが 0 秒以前）、`\fad`・`\fade` のフェードインが 0 秒で終わっていない、画面からはみ出しそう（`\pos` の行は対象外なので、サムネイルではほとんど検査されない） |
| サムネイル（`thumbnail`・`check`） | 背景の長さを取得できず、`at` を確かめられない |
| アバター（`[avatar]` がある曲） | `sync = "auto"` で際立ちが低め（z 値が 5 以上 10 未満）。誤りがないか確認する |
| 縦用 .ass・ショートの区間 | [ショートの検査](#ショートの検査) |
| `check` だけ | 音源のファイル名にバージョン（`vX.Y`）が無い、`song.artist` が空、本編の .ass にスタイル `Short` の行がある（区間は縦用 .ass に書く） |
| 概要欄（`[description]` がある曲の `check`） | `video.background` がどの `materials.files` にも無い、`materials.files` のファイルが無い、タイトルの `{singers}` に入る人がいない、タイトルが 100 文字・概要欄が 5000 バイトを超える、`<` か `>` を含む（YouTube の上限） |
| 告知文（`announce`、`[announce]` がある曲の `check`） | `[[uploads]]` が無い（`announce` だけ）、URL に動画の頭から再生されないパラメータが付いている（[受け付ける URL](#受け付ける-url)）、`work` の `{singers}` に入る人がいない、[長さ](#長さの数え方)が `announce.max_weight` を超える |

はみ出しの概算で反映するタグは [customization.md](customization.md#utavideo-が読むタグ) を参照してください。

### ショートの検査

縦用 .ass（`vertical.lyrics`）と、そこに置くショートの区間の検査です。縦用 .ass の誤りで本編の `build`・`preview-bg`・`overlay` は止めません。`check` は `[[shorts]]` があるときだけ行い、エラーがあれば終了コード 1 にします。`shorts` はエラーがあれば書き出しません。`--name X` を渡したときの「X だけ」は、そのショートについてだけ検査することです。

| 条件 | 扱い | `check` | `shorts` | `shorts --name X` | `preview-bg` |
|---|---|---|---|---|---|
| 本編の .ass（`lyrics.file`）の `LayoutResX`・`LayoutResY` の縦横比が PlayRes と違う | エラー | ○（[歌詞](#エラー書き出さない)の検査） | ○ | ○ | ○（本編の .ass があるとき） |
| 縦用 .ass が無い（`check`・`shorts` は utavideo preview-bg で作れる、と表示。`preview-bg` は自動で作る） | エラー | ○ | ○ | ○ | － |
| 縦用 .ass が読めない（無いのではなく、既にあるファイルが壊れているとき） | エラー | ○ | ○ | ○ | ○ |
| 縦用 .ass が無いとき、本編の歌詞から自動で作れない（`lyrics.file` のファイルが無い、読めない、`PlayResX`・`PlayResY` が無い） | エラー | － | － | － | ○ |
| 縦用 .ass の `PlayResX`・`PlayResY` が無い・`vertical.size` と違う、`LayoutResX`・`LayoutResY` の縦横比が PlayRes と違う、未定義のスタイル、曲名表示を出すのに使うスタイル（`VerticalBand`）が無い、フォント（曲名表示を含む）が見つからない | エラー | ○ | ○ | ○ | ○ |
| 縦の幅に縮めた本編の映像が `vertical.size` の高さを超える（`video.size` が縦より縦長） | エラー | ○ | ○ | ○ | ○ |
| `[[shorts]]` の `name` に対応する区間の行が無い・2つ以上ある | エラー | ○ | ○ | X だけ | － |
| スタイル `Short` の行が、コメント行でなく Dialogue になっている（画面に出てしまう） | エラー | ○ | ○ | ○ | － |
| 区間の終わりが始まり以前、区間の終わりが音源の長さを超える（フレームに丸めた終わりでも見る） | エラー | ○ | ○ | X だけ | － |
| フレームに丸めると区間の長さが 0 になる | エラー | ○ | ○ | X だけ | － |
| `vertical.audio_fade_ms` のイン ＋ アウトが区間の長さを超える | エラー | ○ | ○ | X だけ | － |
| 区間の長さが投稿先の上限を超える（YouTube のショートは 3 分、`wide` では X の通常のアカウントの 2 分 20 秒。[検証記録](verification/20260918-shorts.md)） | 警告 | ○ | ○ | X だけ | － |
| どの `[[shorts]]` の `name` にも合わない区間の行がある | 警告 | ○ | ○ | － | － |
| 区間の頭か終わりが、歌詞の行の途中にかかる（行の時刻を表示） | 警告 | ○ | ○ | X だけ | － |
| 区間に入る行の、[歌詞の行](#警告)と同じ警告（`\pos`・`\move`、表示時間、音源の長さ、重なり、はみ出し） | 警告 | ○ | ○ | X だけ | － |

- 区間の行は、スタイル `Short` の行で、本文の前後の空白を除いたものを `name` と大文字小文字も含めて比べます
- 歌詞は本編の映像に入っているので、区間の端がかかる歌詞の行は、縦用 .ass ではなく**本編の .ass**の行で見ます
- 区間に入る行の警告は、縦用 .ass の描く行（`Vertical` で始まるスタイル）だけを見ます。区間の外の行は、行ごとの検査をしません
- 区間の行が無い・2つ以上ある・区間の終わりが始まり以前・区間の終わりが音源の長さを超える区間では、区間の端と区間に入る行の検査をしません（区間の行が Dialogue になっているだけなら、エラーを出したうえで検査します）
- 音源の長さが分からないとき（音源が無い・読めない）は、音源の長さとの比較と、区間に入る行の検査をしません。区間の端の検査はします
- 曲名表示は帯（縦用 .ass の `VerticalBand` スタイル）に描くので、`VerticalBand` のスタイルとフォントが要ります（`preview-bg` が自動で作ります）
- 本編の映像を描くとき（`wide = true` のショート、`preview-bg`）は、本編の .ass とフォントも `build` と同じ条件で検査します（同じ画面を描くため）
- 本編の .ass にスタイル `Short` の行があるときの警告は `check` だけです

## 出力の形式（変更不可）

| 出力 | 映像 | 音声 |
|---|---|---|
| `build/main.mp4`・`build/shorts/<name>.mp4`・`build/shorts/wide/<name>.mp4` | H.264（`video.crf`・`video.preset`）、yuv420p、BT.709 | AAC 320kbps、48kHz |
| `build/preview/bg.mp4`・`build/preview/vertical-bg.mp4` | H.264（ultrafast、CRF 28、15 フレームごとにキーフレーム） | AAC 160kbps、48kHz |
| `build/overlay.mov` | ProRes 4444（アルファ付き）、BT.709 | PCM 24bit、48kHz |
| `build/thumbnail/<name>.png`・`build/thumbnail/bg/<name>.png` | PNG（RGB 8bit、圧縮レベル 9） | なし |
