# 2026-09-26 楽譜描画パイプラインでの Bravura Text 同梱の検証記録

`utavideo score`（issue #140、.mscz → MusicXML → Verovio → PNG の描画パイプライン）で見つかった、
Verovio が出力するSVGの文字化けと、その対処のために SMuFL フォント Bravura Text を同梱した記録。

## 環境

- macOS、Python 3.12、`verovio` 6.3.0、`resvg-py` 0.5.0
- 動作確認に使った楽譜: ユーザー提供の実際の .mscz（121小節、コード記号172個、MuseScore 4.7.5 で保存）

## 見つかった不具合

Verovio がSVGに書き出す音符・音部記号などの標準的な記譜要素は `<path>` として直接埋め込まれる
（フォント不要）。しかし、コード記号中の♯♭やテンポのメトロノーム記号のように、MEIの一般テキスト
（`<dir>`・`<tempo>` 相当）に埋め込まれた SMuFL 私用領域の文字（U+E000–U+F8FF）は `<path>` 化されず、
`<tspan>` のテキストとして書き出される。このとき

- `font-family="Leipzig"` のように、**実在しないフォント名**が付くことがある（`Leipzig` は
  Verovio 内蔵のグリフ座標データの名前で、配布可能なフォントファイルとしては存在しない）
- `font-family` 属性自体が**無いまま**私用領域の文字だけが出てくることもある

どちらの場合も、SVGラスタライザ（`resvg-py`）はシステムにインストールされている別のフォントへの
フォールバックを試み、たまたま同じコードポイントにグリフを持つ無関係な文字（日本語の機種依存文字
など）を描いてしまう。実データでは、テンポ記号「♩ = 175」が「拍 = 175」に、コード記号「A♭」が
「A食」に化けた。

## 対処：コードポイントで検出してフォントを強制する

`font-family` の値では判別できないため、`<tspan>` のテキスト内容に SMuFL 私用領域の文字
（U+E000–U+F8FF）が含まれるかどうかで検出し、含まれる場合だけ `font-family` を同梱フォントに
強制で書き換える（`src/utavideo/score.py` の `_substitute_missing_font`）。歌詞・コード記号本体
などの通常テキストは対象外なので、日本語フォントへの依存は変わらない。

## 同梱するフォントの選定

MuseScore 同梱の `Leland`/`LelandText` では、実データに含まれる一部のコードポイント
（U+EA64・U+EA66、コード記号の♯♭に使われる）のグリフが無く、文字化けが直らなかった。
`BravuraText`（SMuFLの参照実装。MuseScoreにも同梱される）はこれらを含め、実データで出てきた
全コードポイント（U+EA64, U+EA66, U+ECA5, U+ECB7）を持っていることを確認した。

## 配布元・ライセンス

MuseScoreのインストールに依存させず、公式配布元から取得してリポジトリに同梱する。

- フォント: `https://raw.githubusercontent.com/steinbergmedia/bravura/master/redist/otf/BravuraText.otf`
  （3,056,000 バイト）
- ライセンス: `https://raw.githubusercontent.com/steinbergmedia/bravura/master/redist/OFL.txt`
  （SIL Open Font License 1.1、GitHub API の `license` エンドポイントでも `ofl-1.1` と確認）

`Bravura`（`BravuraText` ではなく本体の記譜用フォント）は MuseScore には同梱されているが、
公式配布元のリポジトリでは `redist/otf/` に `BravuraText.otf` のみが提供されている
（今回はテキスト中の文字の描画にしか使わないため、`BravuraText` で足りる）。

## 動作確認

実データ（121小節）を `to_musicxml` → `render_horizontal_svg` → `svg_to_png` の順に通し、
テンポ記号・コード記号（♯・♭・aug等）が正しいグリフで描かれることを目視確認した。
