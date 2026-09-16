# 制作の流れ

1本の動画を作る手順です。やりたいこと別の設定方法は [customization.md](customization.md)、設定とコマンドの詳細は [config-reference.md](config-reference.md)・[commands.md](commands.md)、フォルダの構成は [project-layout.md](project-layout.md) を参照してください。

## 0. 準備（最初に一度だけ）

Aegisub の字幕の描画エンジンを **libass** にします。utavideo も libass で描画するので、Aegisub で見た位置・折り返し・縁取りがそのまま書き出し結果になります。

- 設定（Preferences）→ 詳細（Advanced）→ ビデオ（Video）→ 字幕プロバイダ（Subtitles provider）を `libass` にする

雛形の字幕スタイルは [Zen Maru Gothic](https://fonts.google.com/specimen/Zen+Maru+Gothic) を使います。Aegisub を動かす環境（WSL2 なら Windows 側）にインストールしてください。入っていないと Aegisub では別のフォントで表示され、`utavideo check` はエラーになります。

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

同じ内容の動画を既に公開しているときや、`build/main.mp4` より新しい入力があるとき（書き出し忘れ）は止まります（[commands.md](commands.md#release)）。

## 動画編集ソフトと組み合わせる

utavideo で合成できない演出（アバターのクロマキー合成など）が必要な場合は、歌詞だけを透過動画にして動画編集ソフトで重ねます。

1. 動画編集ソフトで、歌詞以外を合成した動画を書き出し、`build/preview/bg.mp4` として保存する（Aegisub のプレビューに使う）
2. Aegisub で歌詞を入れる
3. `utavideo overlay` で `build/overlay.mov`（歌詞と曲名表示だけの透過動画、音声付き）を書き出す
4. 動画編集ソフトのタイムラインで、音声の頭をそろえて `overlay.mov` を一番上のトラックに置く

`overlay` は背景を使わないので、`video.background` のファイルが無くても書き出せます。
