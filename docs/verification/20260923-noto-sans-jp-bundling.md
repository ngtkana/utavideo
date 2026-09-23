# 2026-09-23 見本フォント Noto Sans JP 同梱の検証記録

見本（`utavideo sample`）のフォントを、その場で合成する四角フォントから Noto Sans JP に変える
にあたっての実測。

## 環境

- macOS、fontTools（`uv run` で utavideo の venv 経由）
- ffmpeg 8.0（libass 0.17.5、CoreText フォントプロバイダ）

## 配布元

Google Fonts の配布は可変フォント（`wght` 軸）のみで、静的な Regular ファイルは配布されていない。

- 可変フォント: `https://github.com/google/fonts/raw/main/ofl/notosansjp/NotoSansJP%5Bwght%5D.ttf`（9,589,900 バイト）
- ライセンス: `https://raw.githubusercontent.com/google/fonts/main/ofl/notosansjp/OFL.txt`
- `ofl/notosansjp/static/` ディレクトリは存在しない（GitHub API で確認済み、404 になる）

## 可変フォントをそのまま同梱しない理由

`fvar` の `defaultValue` が Thin（100）になっている。`.ass` の `Fontname` 指定だけでは
ウェイトを選べないため、そのまま使うと歌詞が意図せず細く描かれる。

## 静的インスタンス化

```sh
fonttools varLib.instancer NotoSansJP-Variable.ttf wght=400 --update-name-table \
  -o NotoSansJP-Regular.ttf
```

`--update-name-table` を付けないと name table が "Noto Sans JP Thin" のまま残る
（instancer は既定では name table を更新しない）。付けた結果、以下の通り正しく更新された。

| 項目 | 値 |
|---|---|
| ファイルサイズ | 5,766,828 バイト（9,589,900 → 約 60%） |
| `fvar` テーブル | 無し（静的フォントになっている） |
| name ID 1（Family） | `Noto Sans JP` |
| name ID 4（Full name） | `Noto Sans JP Regular` |
| name ID 6（PostScript name） | `NotoSansJP-Regular` |
| `OS/2.usWeightClass` | 400 |

副次的にファイルサイズも縮む（可変フォントの軸情報・`gvar`・`avar` 等が削れるため）。

## libass での実描画確認

`fontsdir` に静的インスタンスだけを置き、`.ass` の `Style` に `Fontname: Noto Sans JP` を指定して
日本語テキスト「見本のうた / 架空アーティスト」を1フレーム描画した。

- `fontselect: (Noto Sans JP, 400, 0) -> NotoSansJP-Regular, 0, NotoSansJP-Regular` のログで、
  family 名（name ID 1）でのマッチを確認
- 出力画像で文字化けが無く、Regular 相当の太さで描画されることを目視確認

## サブセット化・動的ダウンロードを採用しなかった理由

- サブセット化: 歌詞テンプレートを変えるたびに手動でサブセットを作り直す必要があり、更新忘れ
  のリスクがある。フルセットならグリフ抜けが原理的に起きない
- 動的ダウンロード: `sample` 実行のたびに外部ネットワークに依存すると、配布元 URL の変化・
  フォントの意図しない更新・CI の不安定化のリスクがある

フルセット（静的インスタンス化後 5.5MB）をそのままリポジトリにコミットする方針とした。
