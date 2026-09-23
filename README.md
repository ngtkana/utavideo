# utavideo

歌詞入りの動画（背景 ＋ 歌詞 ＋ 曲名表示 ＋ 音声）を、設定ファイル `utavideo.toml` と字幕ファイル `.ass` から ffmpeg で書き出すコマンドラインツールです。
「歌ってみた」動画のように、演出はシンプルで本数が多い動画づくりを想定しています。

- **歌詞の見た目を一括で管理できる。** フォント・色・位置は .ass のスタイルで決めるので、1か所直せば全行に反映されます
- **完成図を見ながら歌詞を入れられる。** 歌詞以外を合成したプレビュー動画を [Aegisub](https://aegisub.org/) で開き、同じ描画エンジン（libass）で確認しながら作業できます
- **何度でも同じ動画を作り直せる。** 素材と設定から書き出すので、歌詞の修正や音源の差し替えにすぐ対応できます
- **動画編集ソフトとも組み合わせられる。** 歌詞だけを透過動画（ProRes 4444）で書き出して、DaVinci Resolve などに重ねられます

## 動作環境

- Linux または WSL2（動作確認: WSL2 上の Ubuntu 24.04、ffmpeg 6.1）
  - インストール済みのフォントは自動で探します（WSL2 では Windows 側のものも）
  - Windows ネイティブ・macOS は、フォントの場所は探しますが未検証です
- libass 付きの ffmpeg / ffprobe（Ubuntu なら `sudo apt install ffmpeg`）
  - libass 無しの ffmpeg では歌詞を描画できません。`preview-bg`・`build`・`overlay` は始めに調べて、書き出す前に止まります（`check` はエラーとして他の検査結果と一緒に出します）
  - macOS は未検証ですが、Homebrew の `ffmpeg` は libass 無しなので、使うなら `brew install ffmpeg-full` が要ります
- 雛形の字幕スタイルが使うフォント [Zen Maru Gothic](https://fonts.google.com/specimen/Zen+Maru+Gothic)（無料）
  - 別のフォントを使う場合は、.ass のスタイルで指定します
- 見本（`utavideo sample`）に同梱しているフォント [Noto Sans JP](https://fonts.google.com/noto/specimen/Noto+Sans+JP)（SIL Open Font License 1.1）
  - ライセンス全文は見本の `src/fonts/OFL.txt` に同梱しています
- 見本（`utavideo sample`）に同梱している背景の静止画（`src/bg/still.jpg`）と音源（`src/mix/sample-v1.0.flac`）は、リポジトリ作者本人（Kana Nagata）が用意したものです（背景: VRoid Studio で制作・VRM Posing Desktop で撮影、音源: 作曲）
- [uv](https://docs.astral.sh/uv/)
- 歌詞を作るのに [Aegisub](https://aegisub.org/) 3.4 以降（推奨）

## インストール

```sh
uv tool install git+https://github.com/ngtkana/utavideo
```

## 使い方

```sh
utavideo new ~/videos/20260915-song --title "曲名" --artist "アーティスト"  # 曲フォルダを作る
cd ~/videos/20260915-song
# 音源と背景を置き、utavideo.toml を編集する
utavideo preview-bg   # 歌詞以外を合成したプレビュー動画 → build/preview/bg.mp4
# Aegisub で src/lyrics.ass とプレビュー動画を開いて歌詞を入れる
utavideo check        # 設定・素材・歌詞・フォントを検査
utavideo build        # 書き出し → build/main.mp4
utavideo description  # タイトルと概要欄 → build/title.txt・build/description.txt
utavideo release      # release/song-v1.0.0.mp4 にコピー
# 動画を投稿し、utavideo.toml の [[uploads]] に URL を書く
utavideo announce     # SNS の告知文 → build/announce.txt
```

| コマンド | 内容 |
|---|---|
| `new` | 雛形から曲フォルダを作る |
| `init` | 既存のフォルダに utavideo のファイルを追加する（既存のファイルは変更しない） |
| `sample` | 動作確認用の見本の曲フォルダを作る（素材も合成するので、そのまま書き出せる） |
| `fonts` | `.ass` に書けるフォント名を探す |
| `preview-bg` | 歌詞以外（背景・曲名表示・音声）を合成した軽いプレビュー動画を書き出す |
| `check` | 設定・素材・歌詞・フォントを検査する |
| `build` | 動画を書き出す（H.264 / AAC） |
| `overlay` | 歌詞と曲名表示だけを透過 ProRes 4444 で書き出す |
| `vertical-ass` | 本編の歌詞 .ass から、縦型のショート用の .ass を作る |
| `shorts` | 縦用 .ass の区間を切り抜いて、縦型のショート（と 16:9 版）を書き出す |
| `description` | クレジット・素材から、タイトルと概要欄を書き出す |
| `release` | 書き出した動画を、バージョン付きの名前で `release/` にコピーする |
| `announce` | 投稿した動画の URL と曲の情報から、SNS の告知文を書き出す |
| `status` | build・概要欄・告知文・release の状態を一覧する（git status 風） |

`new`・`init`・`sample`・`fonts` 以外は曲フォルダの中で実行します（`-C <曲フォルダ>` でも指定できます）。

自分の曲を用意する前に動かしてみたいときは、`utavideo sample <パス>` で合成した素材入りの見本を作れます（[commands.md](docs/commands.md#sample)）。

## ドキュメント

- [制作の流れ](docs/workflow.md)
- [カスタマイズ一覧](docs/customization.md)（やりたいこと別の設定方法）
- [設定リファレンス](docs/config-reference.md)
- [コマンドリファレンス](docs/commands.md)
- [曲フォルダの構成](docs/project-layout.md)
- [ロードマップ](docs/roadmap.md)

## 開発

[CONTRIBUTING.md](CONTRIBUTING.md) を参照してください。
