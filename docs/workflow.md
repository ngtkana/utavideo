# 制作の流れ

1本の動画を作る手順です。素材を用意する前に動かしてみたいときは、`utavideo sample <パス>` で見本の曲フォルダを作れます（[commands.md](commands.md#sample)）。やりたいこと別の設定方法は [customization.md](customization.md)、設定とコマンドの詳細は [config-reference.md](config-reference.md)・[commands.md](commands.md)、フォルダの構成は [project-layout.md](project-layout.md) を参照してください。

素材を一通り置いた後は、下の 6・7・9・サムネイルの書き出しは `utavideo build-all` でまとめて実行できます。既にできているものはスキップし、Aegisub での作業が要るもの（区間の指定など）は「要対応」として教えてくれます（[commands.md](commands.md#build-all)）。

## 0. 準備（最初に一度だけ）

Aegisub の字幕の描画エンジンを **libass** にします。utavideo も libass で描画するので、Aegisub で見た位置・折り返し・縁取りがそのまま書き出し結果になります。

- 設定（Preferences）→ 詳細（Advanced）→ ビデオ（Video）→ 字幕プロバイダ（Subtitles provider）を `libass` にする

雛形の字幕スタイルは [Noto Sans JP](https://fonts.google.com/noto/specimen/Noto+Sans+JP) を使います。Aegisub を動かす環境（WSL2 なら Windows 側）にインストールしてください。入っていないと Aegisub では別のフォントで表示され、`utavideo check` はエラーになります。

## 1. 曲フォルダを用意する

```sh
utavideo new ~/videos/20260915-song --title "曲名" --artist "アーティスト"  # 新しく作る
utavideo init ~/videos/制作中の曲 --artist "アーティスト"                    # 既存のフォルダで使い始める
```

`init` は足りないファイルとフォルダを追加するだけで、既存のファイルは移動も上書きもしません。
`src/` に音源や背景がちょうど1つずつあれば、`utavideo.toml` に自動で設定されます。

## 2. 素材を置いて utavideo.toml を編集する

- 音源（ミックス済みの wav など）を `src/mix/song-v1.0.wav` のように置き、`audio.file` を合わせる
- 背景（画像 / GIF / 動画）を `src/bg/` に置き、`video.background` を合わせる
- `song.title`・`song.artist`・`song.label` を埋める

音源を差し替えるときは、新しいバージョン名のファイル（`song-v1.1.wav`）を置いて `audio.file` を書き換えます。ファイル名の `vX.Y` が、`release` で付く名前に使われます（規則は [project-layout.md](project-layout.md#名前の付け方)）。

## 3. プレビュー動画を作る

```sh
utavideo preview-bg
```

`build/preview/bg.mp4` に、歌詞以外（背景・曲名表示・音声）を合成した動画ができます。
WSL2 では、Aegisub で開くための Windows のパスも表示されます。

## 4. Aegisub で歌詞を入れる

1. `src/lyrics.ass` を開く
2. ビデオ → ビデオを開く で `build/preview/bg.mp4` を開く
3. オーディオ → ビデオからオーディオを開く で、同じ動画の音声を読み込む
4. 波形を見ながら、歌詞の行とタイミングを入れる。スタイルは `Lyrics`（歌詞）と `Comment`（コメント）を使い分ける
5. .ass 形式のまま保存する

解像度を合わせるか聞かれたら、変更しない方を選んでください（プレビュー動画は .ass の PlayRes と同じ解像度で作られています）。

### 見た目の決め方

- **位置・大きさ・色はスタイルで決めます。** スタイルマネージャで数値を変えると映像にすぐ反映されるので、完成図を見ながら調整できます
- 位置が何種類かあるときは、`LyricsLeft` / `LyricsRight` のように**スタイルを分けます**
- 行ごとのタグ（`\pos`、`\fs`、`\c` など）は、演出上どうしても必要な行だけに使います
- **長い行は `\N` で改行します。** libass は空白の位置でしか自動改行しないため、空白の無い日本語の長い行は画面の外へはみ出します
- フェードと曲名表示は .ass に書きません。`utavideo.toml` の `lyrics.fade_ms` と `[overlay_text]` から自動で入ります

タグ・レイヤー・フェード・曲名表示などの書き方は [customization.md](customization.md) を参照してください。

### プレビューを作り直すとき

`utavideo.toml`（背景・曲名表示など）を変えたら、`utavideo preview-bg` を実行し直し、Aegisub で動画を開き直します。背景を決めてから歌詞を入れると、作り直しはほとんど要りません。
フェードも含めた最終的な見え方は、`utavideo build` の結果で確認してください。

WSL2 で曲フォルダが Windows のドライブにあるときは、出力先の動画を他のアプリで開いたまま書き出すと止まります（[commands.md](commands.md#共通)）。

## 5. 検査する

```sh
utavideo check
```

エラーがあると書き出せません（警告だけなら書き出せます）。検査項目は [commands.md](commands.md#検査項目) を参照してください。

初回はフォントの一覧を作るので時間がかかります（2回目以降はキャッシュを使います）。

## 6. 書き出して確認する

```sh
utavideo build
```

`build/main.mp4` ができます。`build/` の中身は utavideo がいつでも作り直せるので、消してもかまいません。

## 7. 概要欄とタイトルを作る

`utavideo.toml` の `song.original_urls`・`[[credits]]`・`[[materials]]`・`[description]` を埋めてから実行します。

```sh
utavideo description
```

`build/title.txt` と `build/description.txt` を、投稿画面のタイトルと説明の欄に貼ります。見出しの形などは [customization.md](customization.md#概要欄とタイトル) を参照してください。

## 8. 公開用にコピーする

```sh
utavideo release                # release/song-vX.Y.N.mp4（vX.Y は音源のファイル名から、N はその音源で何本目か）
utavideo release --version v1.0 # 音源のバージョンを指定する
```

同じ内容の動画を既に公開しているときや、`build` の後に動画に効く入力（歌詞・素材・曲名など）を変えたとき（書き出し忘れ）は止まります。7 の概要欄の項目だけを変えたときは止まりません（比べ方は [commands.md](commands.md#release)）。

## 9. 投稿して告知文を作る

`release` した動画を投稿サイトに投稿（または公開を予約）してから、URL を `utavideo.toml` に書きます。

```toml
[[uploads]]
url = "https://youtu.be/xxxxxxxxxxx"

[[uploads]]
url = "https://www.nicovideo.jp/watch/sm00000000"
```

```sh
utavideo announce
```

`build/announce.txt` を SNS に貼ります。URL の形が誤っているときは書き出さずに止まり、X で「さらに表示」に折りたたまれる長さのときは警告します（[commands.md](commands.md#announce)）。書式は [customization.md](customization.md#sns-の告知文) を参照してください。

`[[uploads]]` を書くと `utavideo.toml` が `build/main.mp4` より新しくなり、`release` が止まります。`release` を先に済ませてから URL を書いてください。

## 9. サムネイルを作る

動画と同じ背景・フォントで、サムネイル用に文字を組み直します。`new` / `init` で `utavideo.toml` を作った曲には、`src/thumbnail.ass` と `[[thumbnails]]`（`name = "main"`）が入っています。既存の `utavideo.toml` がある曲では、`init` が表示する書き足し方に従って足してください。

```sh
utavideo thumbnail --bg-only    # build/thumbnail/bg/main.png（文字を組むときの下敷き）
```

1. 背景が GIF・動画なら、使うフレームの時刻を `[[thumbnails]]` の `at` に書いてから実行する
2. Aegisub で `src/thumbnail.ass` を開き、ビデオ → ビデオを開く で `build/thumbnail/bg/main.png` を開く（雛形の .ass には下敷きのパスが書いてあり、開くと読み込まれることがあります）
3. 文字の位置・大きさ・色を決める。行は `0:00:00.00` から始める（描かれる状態は [commands.md](commands.md#thumbnail)。雛形の行は `9:59:59.99` まで）
4. 保存して書き出す

```sh
utavideo thumbnail              # build/thumbnail/main.png
```

- `build` の後に `[[thumbnails]]` を書き足したり変えたりしてから `release` するときは、`--allow-stale` が要ります（[commands.md](commands.md#release)）
- 曲名・アーティストを直すときは [customization.md](customization.md#サムネイル)
- 正方形などのサイズ違いは、`[[thumbnails]]` を足します（[customization.md](customization.md#サムネイル)）
- 投稿先には容量の上限があります。書き出したときに表示されるバイト数で確かめてください

## 10. ショートの縦用 .ass を作り、区間を置く

縦型のショート（YouTube Shorts など）に使う、縦に組み直した歌詞と、切り抜く区間を用意します。本編の歌詞を入れ終えてから作ります。

```sh
utavideo vertical-ass           # src/vertical.ass（本編の src/lyrics.ass は変わらない）
utavideo preview-bg --vertical  # build/preview/vertical-bg.mp4（縦の下敷き）
```

1. `utavideo.toml` に `[vertical]` を書いてから、上のコマンドを実行する。画面の作り方（`layout`）は `"blur"`（既定。本編の映像を上下のぼかした帯に置く）と `"reframe"`（背景を縦に切り取り、縦用 .ass の歌詞を重ねる）から選び（[commands.md](commands.md#shorts)）、背景の残す位置を縦で変えるなら `focus`、`blur` で本編を置く高さを変えるなら `frame_y` も書く
2. Aegisub で `src/vertical.ass` を開く。下敷きの `build/preview/vertical-bg.mp4` は、縦用 .ass に書いてあるので開くと読み込まれることがあります。読み込まれなければ、[4.](#4-aegisub-で歌詞を入れる) と同じ手順で動画と音声を開く
3. 波形を見ながら、切り抜く区間の行を置く（書き方は下の[区間の書き方（文法）](#区間の書き方文法)）
4. `utavideo.toml` に、同じ名前の `[[shorts]]` を書く

```toml
[[shorts]]
name = "chorus"
```

5. `reframe` では、文字は本編と同じ割合で小さくなっているので、まずスタイル `Lyrics` の大きさを上げる
6. `reframe` では、区間に入る行のうち、画面からはみ出す行を `\N` で改行する。位置や大きさを直すのは、縦用 .ass だけです。区間の外の行は使わないので、直さなくてかまいません。`blur` では歌詞が本編の映像に入り、曲名表示も自動で帯に入るので、組むのは区間の指定だけです。帯に文字を足したいときだけ、スタイル `VerticalBand` で書きます
7. .ass 形式のまま保存し、`utavideo check` で検査する（[commands.md](commands.md#ショートの検査)）
8. 書き出す

```sh
utavideo shorts                 # build/shorts/<name>.mp4（wide なら build/shorts/wide/<name>.mp4 も）
utavideo shorts --name chorus   # 1本だけ書き出す
```

- `vertical-ass` は、縦用 .ass が既にあると止まります。直した縦用 .ass を上書きしないためです。`layout` は `vertical-ass` を実行する前に決めてください（使う `layout` が `blur` だけなら歌詞の行を写しません）
- 変換される大きさと座標、変換されない図形は [commands.md](commands.md#vertical-ass) を参照してください
- 縦用 .ass の曲名表示のスタイル（`reframe` は `Title`、`blur` は `VerticalBand`）を変えたら、`preview-bg --vertical` を実行し直します
- 後から本編の歌詞を直したら、縦用 .ass も同じように直します。直し忘れは `check` が警告します（[本編との突き合わせ](commands.md#本編との突き合わせ)）。縦での改行の変え方（1行を2行に分ける、2行を1行にまとめる）では警告しません。`blur` では縦に歌詞を置かないので、この警告は出ません
- 区間の端の音声はフェードします（長さは [`vertical.audio_fade_ms`](config-reference.md#vertical)）。フェードインの間は音が小さいので、区間の頭は歌い出しの少し前に置きます
- 16:9 版（SNS の告知に添える用）が要るときは、`[[shorts]]` に `wide = true` を書きます
- 区間の長さが投稿先の上限を超えると警告します（[ショートの検査](commands.md#ショートの検査)）

### 区間の書き方（文法）

- 1区間 = スタイル `Short` のコメント行1本（本文を `chorus` にすると `[[shorts]] name = "chorus"` と対応します）
- 区間の開始・終了 = その行の開始・終了時刻。Aegisub 上での行の長さが、そのまま区間の長さになります
- 本文 = `[[shorts]]` の `name` と一致させる（前後の空白を除き、大文字小文字も含めて比べます）
- エラーになる条件（区間の行が無い・2つ以上ある、Dialogue になっている、終了が始まり以前・音源の長さを超える、など）は[ショートの検査](commands.md#ショートの検査)を参照してください

## 動画編集ソフトと組み合わせる

utavideo で合成できない演出（アバターのクロマキー合成など）が必要な場合は、歌詞だけを透過動画にして動画編集ソフトで重ねます。

1. 動画編集ソフトで、歌詞以外を合成した動画を書き出し、`build/preview/bg.mp4` として保存する（Aegisub のプレビューに使う）
2. Aegisub で歌詞を入れる
3. `utavideo overlay` で `build/overlay.mov`（歌詞と曲名表示だけの透過動画、音声付き）を書き出す
4. 動画編集ソフトのタイムラインで、音声の頭をそろえて `overlay.mov` を一番上のトラックに置く

`overlay` は背景を使わないので、`video.background` のファイルが無くても書き出せます。
