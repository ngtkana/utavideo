# utavideo

`utavideo.toml` と歌詞 `.ass` から ffmpeg + libass で動画を書き出す CLI（uv / Python 3.12 / typer）。

開発の準備・確認のコマンド・ドキュメントの分担は CONTRIBUTING.md に従う。

@CONTRIBUTING.md

## 構成

- `src/utavideo/cli.py`：コマンド定義。`analyze()` で検査し、`_render()` で書き出す
- `console.py`：コマンドの出力に使う Rich の Console
- `config.py`：toml を pydantic で検証する。未知の項目はエラー。動画の描画に効かない項目には `NOT_RENDERED` の印を付ける（付けないと、変えたときに `release` が止まる）
- `project.py`：曲フォルダの規約（パス、バージョン名）、雛形の作成
- `sample.py`：動作確認用の見本の曲フォルダ（`utavideo sample`）。フォント・音源・背景を合成する
- `subs.py`：pysubs2 で .ass の検査・フェード挿入・曲名表示の追加
- `description.py`：クレジット・素材から概要欄とタイトルを組み立てる
- `announce.py`：投稿した動画の URL と曲の情報から SNS（X）の告知文を組み立て、URL・ハッシュタグ・長さを検査する
- `fonts.py`：fontTools でフォント名→ファイルの対応表を作る。必要なファイルだけのリンク集を libass の fontsdir に渡す
- `timecode.py`：設定に書く時刻（`"M:SS(.fff)"` か秒の数）の読み取り
- `vertical.py`：本編の .ass の座標・大きさを縦の解像度に変換して、縦用 .ass の雛形を作る
- `shorts.py`：縦用 .ass からショートの区間（スタイル `Short` のコメント行）を読み、区間と区間に入る行を検査し、区間に入る歌詞を本編の歌詞と突き合わせる。区間をフレームに丸める
- `layout.py`：行の幅を概算して、はみ出しそうな行を警告する（libass は空白の無い日本語を自動改行しない）
- `inputs.py`：`build` の入力（素材の中身・印の無い設定・フォントの stat）を記録し、`release` で比べる
- `graph.py`：ffmpeg の引数（動画と、サムネイルの1枚の PNG）を組み立てる純粋関数。`ffmpeg.py` が実行する
- `templates/`：`new` / `init` が書き出す雛形と、`sample` が書き出す見本（`sample*`）

## 約束

- 公開リポジトリ。docs・雛形・テストは一般の利用者向けに書き、個人の環境や作品に依存する内容を入れない
- 利用者の元ファイル（`src/lyrics.ass` など）は書き換えない。加工したものは `build/.work/` に書く
- 出力は `.partial` に書いてから名前を変える。`release/` のファイルは上書きしない
- OS のユーザー名や、ホームディレクトリの絶対パスを書かない
- commit の前に CONTRIBUTING.md の「確認」を通す
- 挙動や仕様を変えたら、CONTRIBUTING.md の「ドキュメントの分担」に従って、対応するドキュメントも同じ変更で直す
