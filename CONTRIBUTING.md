# 開発

## 準備

```sh
git clone https://github.com/ngtkana/utavideo
cd utavideo
uv sync
uv tool install --editable .   # utavideo コマンドを手元のコードで動かす
```

## 確認

CI（`.github/workflows/ci.yml`）と同じ確認です。PR を出す前に通してください。

```sh
uv run ruff format --check
uv run ruff check
uv run pyright
uv run pytest   # ffmpeg があれば、実際に書き出す結合テストも実行される
```

## 変更の送り方

- ブランチで変更して PR を出してください（main には直接 push できません）
- 挙動や仕様を変えたら、対応するドキュメントも同じ PR で直してください
- 利用者向けのメッセージとドキュメントは日本語で書きます

## ドキュメントの分担

1つの事実は1か所に書き、他の文書からはリンクします。

| ファイル | 内容 |
|---|---|
| `README.md` | 初めて使う人向け。概要・動作環境・インストール・最短の使い方 |
| `docs/workflow.md` | 1本作る手順 |
| `docs/customization.md` | やりたいこと別の設定方法（変えられることをすべて載せる） |
| `docs/config-reference.md` | 設定（`utavideo.toml`・ユーザー設定・環境変数）の全項目 |
| `docs/commands.md` | コマンドのオプション・検査項目・出力の形式 |
| `docs/project-layout.md` | 曲フォルダの構成と名前の規則 |
| `docs/roadmap.md` | 今後の予定 |
| `docs/verification/` | 設計の前提にした実測や挙動の記録。日付ごとのファイルに追記し、既存の記録は書き換えない |
