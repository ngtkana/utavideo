# utavideo

`utavideo.toml` と歌詞 `.ass` から ffmpeg + libass で動画を書き出す CLI（uv / Python 3.12 / typer）。

## コマンド

- テスト: `uv run pytest`（`tests/test_render.py` は実際に ffmpeg を動かす）
- lint / 整形: `uv run ruff check && uv run ruff format`
- 型: `uv run pyright`

## 構成

- `src/utavideo/cli.py`：コマンド定義。`analyze()` で検査し、`_render()` で書き出す
- `config.py`：toml を pydantic で検証する。未知の項目はエラー
- `project.py`：曲フォルダの規約（パス、バージョン名）、雛形の作成
- `subs.py`：pysubs2 で .ass の検査・フェード挿入・曲名表示の追加
- `fonts.py`：fontTools でフォント名→ファイルの対応表を作る。必要なファイルだけのリンク集を libass の fontsdir に渡す
- `layout.py`：行の幅を概算して、はみ出しそうな行を警告する（libass は空白の無い日本語を自動改行しない）
- `graph.py`：ffmpeg の引数を組み立てる純粋関数。`ffmpeg.py` が実行する
- `templates/`：`new` / `init` が書き出す雛形

## 約束

- 公開リポジトリ。docs・雛形・テストは一般の利用者向けに書き、個人の環境や作品に依存する内容を入れない
- 利用者向けのメッセージとドキュメントは日本語
- 利用者の元ファイル（`src/lyrics.ass` など）は書き換えない。加工したものは `build/.work/` に書く
- 出力は `.partial` に書いてから名前を変える。`release/` のファイルは上書きしない
- OS のユーザー名や、ホームディレクトリの絶対パスを書かない
- commit の前に、CI（`.github/workflows/ci.yml`）と同じ QA（上のコマンド）を通す

## ドキュメント

挙動や仕様を変えたら、対応するドキュメントも同じ変更で直す。

- `README.md`：初めて使う人向け（概要・インストール・コマンド一覧）
- `CONTRIBUTING.md`：開発する人向け（準備・QA・変更の送り方・ドキュメントの分担）
- 仕様。コードと食い違わないようにする。1つの事実は1か所に書き、他の文書からはリンクする
  - `docs/workflow.md`：制作の流れ（手順だけ）
  - `docs/customization.md`：やりたいこと別の設定方法（変えられることを網羅する）
  - `docs/config-reference.md`：設定（utavideo.toml・ユーザー設定・環境変数）の全項目
  - `docs/commands.md`：コマンドのオプション・検査項目・出力の形式
  - `docs/project-layout.md`：曲フォルダの構成と名前の規則
- `docs/roadmap.md`：今後の予定
- `docs/verification/YYYYMMDD-*.md`：検証記録。設計の前提にした実測や挙動を、日付ごとのファイルに追記していく（既存の記録は書き換えない）
