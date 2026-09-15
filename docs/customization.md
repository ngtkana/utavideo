# カスタマイズ一覧

やりたいこと別の設定方法です。項目の型と既定値は [config-reference.md](config-reference.md) を参照してください。

## 歌詞の見た目（.ass）

見た目は .ass のスタイルで決めます（Aegisub のスタイルマネージャ）。

| やりたいこと | 書き方 |
|---|---|
| フォント・大きさ・色 | `Fontname`・`Fontsize`・`PrimaryColour` など（色は `&HAABBGGRR`。`AA` が `00` で不透明） |
| 縁取り・影 / 文字の後ろに帯 | `Outline`・`Shadow` / `BorderStyle` を `3`（帯の色は `OutlineColour`） |
| 位置 | `Alignment`（テンキーの配置）と `MarginL`・`MarginR`・`MarginV`。位置が複数あるならスタイルを分ける |
| 同時に複数行（ハモリなど） | レイヤーを分ける（同じスタイル・同じレイヤーで重なると `check` が警告する） |
| 書き出さないメモ | Aegisub で行を「コメント」にする |
| 長い行 | `\N` で改行する（空白の無い日本語は自動で折り返されない） |
| フェード | `lyrics.fade_ms` で全行に付く。`\fad` を書いた行には付かない |

libass のタグはすべて使えます。utavideo が特別に扱うのは次のタグです。

- `\pos`・`\move`：`check` が警告し、重なりとはみ出しの検査から外す
- `\fn`・`\r<スタイル名>`：そのフォントとスタイルも検査の対象になる
- `\fs`・`\fscx`・`\fsp`・`\q`：はみ出しの概算に反映する（`\bord` と縦書きは反映しない）

## 曲名表示

レイヤー 100 に、動画の最初から最後まで入ります（自動のフェードは付きません）。見た目は `Title` スタイル、文字は `overlay_text.text` で変えます。

- タグは `{` `}` を二重にして書く。例: `text = "{{\\an7}}{title}\\N{artist}"`（左上に2行）
- `overlay_text.enabled = false` にすると、`Title` スタイルのフォントも不要になる

## 解像度・縦長の動画

`video.size` と .ass の `PlayResX`・`PlayResY` を同じ偶数にします。歌詞を入れた後なら、Aegisub の「解像度の変換（Resample Resolution）」でスタイルも一緒に拡大縮小できます。

## 音源のバージョン

ファイル名の `v1.2` などがバージョンになります（大文字の `V` も可。複数あれば最後のもの。`v1.2a` は対象外）。`release --version` では小文字の `v` で書きます。

## フォント

- 曲フォルダに置いたフォントを使う：`UTAVIDEO_FONT_DIRS=./fonts utavideo build`（相対パスは実行した場所から）
- フォント名は、ファミリー名・フルネーム・PostScript 名などと、大文字小文字を区別せずに照合する
- Aegisub で同じ見た目にするには、Aegisub 側にもインストールする

設定ファイルとキャッシュの場所は、`XDG_CONFIG_HOME`・`XDG_CACHE_HOME` に従います。

## 雛形を自分用にする

雛形は設定では変えられません。定番のスタイルは、Aegisub のスタイルマネージャのストレージに保存して使い回すか、自分用の `src/lyrics.ass` を置いたフォルダで `utavideo init` します（既にあるファイルは残ります）。

## 描画した内容を確かめる

`build/.work/*.ass` が、実際に描画した .ass です（自動のフェードと曲名表示が入っています）。Aegisub で開けます。

## 今は変えられないもの

出力の形式、曲名表示の区間・レイヤー・数、背景の重ね合わせ、1曲で複数の .ass。予定は [roadmap.md](roadmap.md) を参照してください。
