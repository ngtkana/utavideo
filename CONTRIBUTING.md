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
- `tests/test_sample.py` は `utavideo sample` で見本の曲フォルダを作り、小さい寸法（`--small`）で各コマンドを動かす（同じくスキップあり）
- `tests/test_docs.py` は、コマンドのオプション・設定項目・環境変数がドキュメントに載っているか、文書内のリンクが切れていないかを確かめる
- 出力を確かめるテストが折り返しで落ちないように、`tests/conftest.py` が `cli` のコンソールの幅を固定する。CI が狭い幅で走らせるのは、この固定から漏れたコンソールが増えたときに気づくため

## 変更の送り方

- ブランチで変更して PR を出す（main には直接 push できない）
- PR を出すと、Claude が差分をレビューしてコメントする（`.github/workflows/claude-review.yml`。draft の間とフォークからの PR では動かない）
- 挙動や仕様を変えたら、下の分担に従って、対応するドキュメントも同じ PR で直す
- 利用者向けのメッセージとドキュメントは日本語で書く
- PR の本文に「動作確認の手順」を書く（下のテンプレート）
- 設定項目・コマンドを足したら、見本（`utavideo sample`）にも同じ PR で足す。見本の `utavideo.toml` は未知の項目がエラーになるので、そのブランチのコードでしか読めない

### 動作確認の手順（PR 本文に書く）

見た目・音・Aegisub での見え方は、人が動かさないと確かめられません。見本の曲フォルダ（`utavideo sample`。[commands.md](docs/commands.md#sample)）を作って確かめられるようにし、その手順を PR の本文に書きます。
ホームディレクトリの絶対パスは書かず、`<見本のフォルダ>` と、曲フォルダからの相対パスを使います。

~~~markdown
## 動作確認の手順

1. 見本を作る（`<見本のフォルダ>` はリポジトリの外の、まだ無いパス）

   ```sh
   utavideo sample <見本のフォルダ>
   cd <見本のフォルダ>
   ```

   見栄えを見る項目があるときは `--font "<手元にあるフォント名>"` を付ける（合成フォントはどの文字も四角なので、書体は確かめられない）。

2. 実行する（`--font` を付けたときは `UTAVIDEO_FONT_DIRS=src/fonts ` は要らない）

   ```sh
   UTAVIDEO_FONT_DIRS=src/fonts utavideo check
   UTAVIDEO_FONT_DIRS=src/fonts utavideo build
   ```

3. 何を見れば正しいと分かるか

   - `build/main.mp4` の 0:12 の行が、画面の左右からはみ出している（`check` のはみ出しの警告と同じ行）
   - 背景の白い箱が 5 秒で画面を横断し、0:05 と 0:10 では同じ位置に戻っている
~~~

- 3 は「どこを見るか」と「どうなっていれば正しいと分かるか」を必ず対にして書く。「確認する」だけでは、読んだ人が同じ判断をできない
- コマンドが通る・数値が合うなど、機械が判定できることはテストで確かめ、PR 本文の「確認したこと」に書く。手順には混ぜない
- 判定は件数ではなく中身で書く。警告の数やファイルのサイズは、読む人のユーザー設定や渡したフォントで変わる
- `UTAVIDEO_FONT_DIRS` は `export` しない。探す場所を置き換えるので、同じシェルで自分の曲に戻ったときに自分のフォントが見つからなくなる

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
| 見本 | `src/utavideo/sample.py`・`src/utavideo/templates/sample*` | `utavideo sample` が作る見本の中身（説明は `docs/commands.md`） |
| 検証記録 | `docs/verification/YYYYMMDD-*.md` | 設計の前提にした実測や挙動。問題があったときに立ち返るための記録なので、日付ごとのファイルに追記し、既存の記録は書き換えない |
