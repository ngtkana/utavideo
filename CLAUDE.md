# utavideo

`utavideo.toml` と歌詞 `.ass` から ffmpeg + libass で動画を書き出す CLI（uv / Python 3.12 / typer）。

開発の準備・確認のコマンド・ドキュメントの分担は CONTRIBUTING.md に従う。

@CONTRIBUTING.md

## 構成

- `src/utavideo/cli.py`：コマンド定義。`analyze()` で検査し、`_render()` で書き出す
- `config.py`：toml を pydantic で検証する。未知の項目はエラー
- `project.py`：曲フォルダの規約（パス、バージョン名）、雛形の作成
- `subs.py`：pysubs2 で .ass の検査・フェード挿入・曲名表示の追加
- `description.py`：クレジット・素材から概要欄とタイトルを組み立てる
- `announce.py`：投稿した動画の URL と曲の情報から SNS（X）の告知文を組み立て、URL・ハッシュタグ・長さを検査する
- `fonts.py`：fontTools でフォント名→ファイルの対応表を作る。必要なファイルだけのリンク集を libass の fontsdir に渡す
- `layout.py`：行の幅を概算して、はみ出しそうな行を警告する（libass は空白の無い日本語を自動改行しない）
- `graph.py`：ffmpeg の引数を組み立てる純粋関数。`ffmpeg.py` が実行する
- `templates/`：`new` / `init` が書き出す雛形

## 約束

- 公開リポジトリ。docs・雛形・テストは一般の利用者向けに書き、個人の環境や作品に依存する内容を入れない
- 利用者の元ファイル（`src/lyrics.ass` など）は書き換えない。加工したものは `build/.work/` に書く
- 出力は `.partial` に書いてから名前を変える。`release/` のファイルは上書きしない（例外は `release --description-only`。公開済みの概要欄の `.txt` だけを書き直す）
- OS のユーザー名や、ホームディレクトリの絶対パスを書かない
- commit の前に CONTRIBUTING.md の「確認」を通す
- 挙動や仕様を変えたら、CONTRIBUTING.md の「ドキュメントの分担」に従って、対応するドキュメントも同じ変更で直す
