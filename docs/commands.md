# コマンドリファレンス

各コマンドのオプション、読み書きするファイル、検査項目、出力の形式です。手順は [workflow.md](workflow.md) を参照してください。

## 共通

- `check`・`preview-bg`・`build`・`overlay`・`description`・`release` は曲フォルダで実行します。`-C <曲フォルダ>`（`--project`）で指定でき、省略するとカレントディレクトリから親へ向かって `utavideo.toml` を探します
- `sample`・`check`・`preview-bg`・`build`・`overlay` には ffmpeg と ffprobe が必要です。無ければ、何を入れればよいかを表示して始めに止まります
- 歌詞の描画には libass 付きの ffmpeg が必要です（[動作環境](../README.md#動作環境)）。無いと `preview-bg`・`build`・`overlay` は書き出す前に止まり、`check` は[エラー](#検査項目)として他の検査結果と一緒に出します。素材を合成するだけの `sample` には要りません
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

## sample

```sh
utavideo sample <パス> [--font <フォント名>] [--small]
```

動作確認用の見本の曲フォルダを作ります。素材をその場で合成するので、自分の曲を用意する前に一通りのコマンドを試せます。`new` が空の雛形（素材は自分で置く）なのに対して、`sample` は素材入りで、作った直後から書き出せます。

| オプション | 既定値 | 内容 |
|---|---|---|
| `<パス>` | 必須 | 作る見本の曲フォルダのパス。既にあるとエラー（作り直すときはフォルダごと消す） |
| `--font` | 合成フォント | 歌詞に使う実在のフォント名 |
| `--small` | 無効 | 小さく速く作る（640x360・10fps・ultrafast）。テストと CI 用 |

作るものは 1920x1080・30fps・36 秒で、合計 2MB 程度です。途中で失敗したときは、作りかけのフォルダを消してから終わるので、同じパスでやり直せます。

| ファイル | 内容 |
|---|---|
| `utavideo.toml` | 架空の曲名・クレジット・素材。背景の変え方はコメントに書いてある |
| `src/lyrics.ass` | 歌詞。警告の出る行がわざと入っている（下記） |
| `src/mix/sample-v1.0.flac` | 4 秒ごとに 220Hz ずつ高くなる合成音（220Hz から 9 段）。同じ高さが出てこないので、どこを切り出したか、どこでフェードしたかが耳で分かる |
| `src/bg/loop.mp4` | カラーバー ＋ 5 秒で画面を横断する白い箱。背景の繰り返しが目で分かる |
| `src/bg/still.png` | 4:3 のカラーバー（静止画）。`video.fit` を `"cover"`（上下が切り取られる）と `"contain"`（左右に余白が出る）で見比べられる |
| `src/bg/loop.gif` | `loop.mp4` と同じ絵の GIF（480x270・2 秒）。GIF の背景と、拡大の効き方を試す用 |
| `src/fonts/UtavideoSample.ttf` | 合成フォント（`--font` を渡したときは作らない） |
| `README.md` | 試すコマンドの一覧 |

- 合成フォントを使うときは、見本の曲フォルダで `UTAVIDEO_FONT_DIRS=src/fonts utavideo check` のように、コマンドごとに場所を渡します（`UTAVIDEO_FONT_DIRS` は探す場所を置き換えるので、`export` すると同じシェルで自分の曲に戻ったときに自分のフォントが見つかりません）
- 合成フォントはどの文字も四角で描くので、書体や仕上がりは確かめられません。見栄えを見るときは `--font` に手元のフォント名を渡します
- 見本は `check` で**警告が 2 件**出ます。警告の出方も見せるためで、`\pos` / `\move` を使っている行が 2 行と、空白も `\N` も無い長い行が 1 行入っています。はみ出しの警告は行の幅の概算から出すので、`--font` に細いフォントを渡すと出なくなることがあります
- 要らなくなったらフォルダごと消します

## check

```sh
utavideo check [-C <曲フォルダ>]
```

[検査項目](#検査項目)を調べ、曲名・音源の長さ・歌詞の行数・使うフォントのファイル・`release` で次に付く名前を表示します。

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
| 概要欄（`[description]` がある曲の `check`） | ユーザー設定の `description.title`・`description.heading` の書式が不正 |
| 実行環境 | ffmpeg で `subtitles` フィルタ（libass）が使えない（ffmpeg・ffprobe が無いときは検査を始める前に止まります） |

### 警告

| 対象 | 内容 |
|---|---|
| 歌詞の行 | `\pos`・`\move` を使っている、表示時間が 0 以下、音声が終わった後に始まる、音声の終わりで途中で切られる、同じスタイル・同じレイヤーで重なる、画面からはみ出しそう |
| `check` だけ | 音源のファイル名にバージョン（`vX.Y`）が無い、`song.artist` が空 |
| 概要欄（`[description]` がある曲の `check`） | `video.background` がどの `materials.files` にも無い、`materials.files` のファイルが無い、タイトルの `{singers}` に入る人がいない、タイトルが 100 文字・概要欄が 5000 バイトを超える、`<` か `>` を含む（YouTube の上限） |

はみ出しの概算で反映するタグは [customization.md](customization.md#utavideo-が読むタグ) を参照してください。

## 出力の形式（変更不可）

| 出力 | 映像 | 音声 |
|---|---|---|
| `build/main.mp4` | H.264（`video.crf`・`video.preset`）、yuv420p、BT.709 | AAC 320kbps、48kHz |
| `build/preview/bg.mp4` | H.264（ultrafast、CRF 28、15 フレームごとにキーフレーム） | AAC 160kbps、48kHz |
| `build/overlay.mov` | ProRes 4444（アルファ付き）、BT.709 | PCM 24bit、48kHz |
