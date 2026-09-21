# 開発

## 準備

```sh
git clone https://github.com/ngtkana/utavideo
cd utavideo
uv tool install --editable .   # utavideo コマンドが手元のコードで動く
```

## 確認

commit の前に通してください。CI（`.github/workflows/ci.yml`）も同じ確認をします（format は `--check`、pytest は `COLUMNS=40` で実行）。変わったのが `docs/`・`README.md`・`CONTRIBUTING.md`・`CLAUDE.md` だけなら、CI は `tests/test_docs.py` だけを実行します。

```sh
uv run ruff format && uv run ruff check && uv run pyright && uv run pytest
```

- `tests/test_render.py` は ffmpeg で実際に書き出す（ffmpeg が無ければスキップ）
- `tests/test_docs.py` は、コマンドのオプション・設定項目・環境変数がドキュメントに載っているか、文書内のリンクが切れていないかを確かめる
- 出力を確かめるテストが折り返しで落ちないように、`tests/conftest.py` が `cli` のコンソールの幅を固定する。CI が狭い幅で走らせるのは、この固定から漏れたコンソールが増えたときに気づくため

## 変更の送り方

- ブランチで変更して PR を出す（main には直接 push できない）
- PR を出すと、Claude が差分をレビューしてコメントする（`.github/workflows/claude-review.yml`。draft の間とフォークからの PR では動かない）
- 挙動や仕様を変えたら、下の分担に従って、対応するドキュメントも同じ PR で直す
- 利用者向けのメッセージとドキュメントは日本語で書く

## ドキュメントの分担

1つの事実は1か所に書き、他の文書からはリンクします。

| 種類 | ファイル | 内容 |
|---|---|---|
| 初めて来た人向け | `README.md` | 概要・動作環境・インストール・最短の使い方 |
| 仕様 | `docs/workflow.md` | 1本作る手順 |
| 仕様 | `docs/customization.md` | やりたいこと別の設定方法（変えられることをすべて載せる） |
| 仕様 | `docs/config-reference.md` | 設定（`utavideo.toml`・ユーザー設定・環境変数）の全項目 |
| 仕様 | `docs/commands.md` | コマンドのオプション・止まる条件・検査項目・出力の形式 |
| 仕様 | `docs/project-layout.md` | 曲フォルダの構成と名前の規則 |
| 仕様 | `docs/roadmap.md` | 今後の予定 |
| 検証記録 | `docs/verification/YYYYMMDD-*.md` | 設計の前提にした実測や挙動。問題があったときに立ち返るための記録なので、日付ごとのファイルに追記し、既存の記録は書き換えない |
