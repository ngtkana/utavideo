# utavideo

歌詞入りの動画（背景 ＋ 歌詞 ＋ 曲名表示 ＋ 音声）を、設定ファイル `utavideo.toml` と字幕ファイル `.ass` から ffmpeg で書き出すコマンドラインツールです。
「歌ってみた」動画のように、演出はシンプルで本数が多い動画づくりを想定しています。

- **歌詞の見た目を一括で管理できる。** フォント・色・位置は .ass のスタイルで決めるので、1か所直せば全行に反映されます
- **完成図を見ながら歌詞を入れられる。** 歌詞以外を合成したプレビュー動画を [Aegisub](https://aegisub.org/) で開き、同じ描画エンジン（libass）で確認しながら作業できます
- **何度でも同じ動画を作り直せる。** 素材と設定から書き出すので、歌詞の修正や音源の差し替えにすぐ対応できます
- **動画編集ソフトとも組み合わせられる。** 歌詞だけを透過動画（ProRes 4444）で書き出して、DaVinci Resolve などに重ねられます

## 動作環境

- Linux または WSL2（動作確認: WSL2 上の Ubuntu 24.04、ffmpeg 6.1）
  - WSL2 では Windows にインストールしたフォントも自動で探します
  - Windows ネイティブ・macOS は未検証です
- libass 付きの ffmpeg / ffprobe（Ubuntu なら `sudo apt install ffmpeg`）
- 雛形の字幕スタイルが使うフォント [Zen Maru Gothic](https://fonts.google.com/specimen/Zen+Maru+Gothic)（無料）
  - 別のフォントを使う場合は、.ass のスタイルで指定します
- [uv](https://docs.astral.sh/uv/)
- 歌詞を作るのに [Aegisub](https://aegisub.org/) 3.4 以降（推奨）

## インストール

```sh
uv tool install git+https://github.com/ngtkana/utavideo
```

開発する場合は、クローンして編集可能モードで入れます。

```sh
git clone https://github.com/ngtkana/utavideo
uv tool install --editable ./utavideo
```

## 使い方

```sh
utavideo new "曲名" --root ~/videos   # 曲フォルダ（YYYYMMDD 曲名/）を作る
cd ~/videos/20260915\ 曲名
# 音源と背景を置き、utavideo.toml を編集する
utavideo preview-bg   # 歌詞以外を合成したプレビュー動画 → build/preview/bg.mp4
# Aegisub で src/lyrics.ass とプレビュー動画を開いて歌詞を入れる
utavideo check        # 設定・素材・歌詞・フォントを検査
utavideo build        # 書き出し → build/main.mp4
utavideo release      # release/曲名 v1.0.mp4 にコピー
```

| コマンド | 内容 |
|---|---|
| `new` | 雛形から曲フォルダを作る |
| `init` | 既存のフォルダに utavideo のファイルを追加する（既存のファイルは変更しない） |
| `preview-bg` | 歌詞以外（背景・曲名表示・音声）を合成した軽いプレビュー動画を書き出す |
| `check` | 設定・素材・歌詞・フォントを検査する |
| `build` | 動画を書き出す（H.264 / AAC） |
| `overlay` | 歌詞と曲名表示だけを透過 ProRes 4444 で書き出す |
| `release` | 書き出した動画を、バージョン付きの名前で `release/` にコピーする |

どのコマンドも曲フォルダの中で実行します（`-C <曲フォルダ>` でも指定できます）。

## ドキュメント

- [制作の流れ](docs/workflow.md)
- [曲フォルダの構成](docs/project-layout.md)
- [utavideo.toml リファレンス](docs/config-reference.md)
- [ロードマップ](docs/roadmap.md)

## 開発

```sh
uv run pytest          # ffmpeg があれば、実際に書き出す結合テストも実行される
uv run ruff check && uv run ruff format
uv run pyright
```
