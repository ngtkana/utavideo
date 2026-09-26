# 2026-09-27 libass（fontsdir）が実際に照合するフォント名

`check` が通るフォント名でも、`build`・`preview` では libass が見つけられず別のフォントで描かれることがある不具合（issue #138）の原因調査と、直したときの前提にした実測。

## 環境

- ffmpeg 9.0.2（Homebrew）。libass は 0.17.5（`brew info libass`）
- `otool -L $(brew --prefix libass)/lib/libass.9.dylib` に `fontconfig` は無く、`CoreText.framework`・`ApplicationServices.framework` にリンクされている。ffmpeg 実行時のログにも `Using font provider coretext` と出る
- **この実測は macOS・CoreText バックエンドでのもの。`fonts.py` の元のコメントが前提にしていた WSL・fontconfig 環境では未確認**（下の「fontconfig との違いについて」参照）

## 方法

fontTools で、1つの `.ttf` に次の8つの名前を、指定した nameID・platform の組み合わせだけに割り当てて作った（`unitsPerEm=1000`、文字 `A` が塗りつぶしの正方形になるグリフ）。

| 名前 | nameID | platform |
|---|---|---|
| `UtaMacFamily` | 1（family） | Mac |
| `UtaWinFamily` | 1（family） | Windows |
| `UtaWinFullName` | 4（full name） | Windows |
| `UtaWinPSName` | 6（PostScript name） | Windows |
| `UtaMacPSName` | 6（PostScript name） | Mac |
| `UtaWinTypoFamily` | 16（typographic family） | Windows |
| `UtaMacTypoFamily` | 16（typographic family） | Mac |
| `UtaMacFullNameOnly`（別ファイル） | 4（full name） | Mac |

このフォント1個だけを `fontsdir` に置き、`.ass` のスタイルの `Fontname` に上の名前を1つずつ指定して、`ffmpeg -loglevel verbose -filter_complex "...,subtitles=filename=...:fontsdir=..." ...` を実行した。ログの `fontselect: (指定した名前, weight, italic) -> 解決されたファイル, index, 解決された名前` で、自作フォント自身が選ばれたか（`fontsdir/UtaTest.ttf` が出る）、システムのフォールバック（`/System/Library/Fonts/...`）に化けたかを確かめた。

## 結果

| 名前 | nameID | platform | 結果 |
|---|---|---|---|
| `UtaWinFamily` | 1 | Windows | 自作フォントが選ばれた |
| `UtaWinFullName` | 4 | Windows | 自作フォントが選ばれた |
| `UtaMacFamily` | 1 | Mac | フォールバック（Helvetica） |
| `UtaMacFullNameOnly` | 4 | Mac | フォールバック（Helvetica） |
| `UtaWinPSName` | 6 | Windows | フォールバック（Helvetica） |
| `UtaMacPSName` | 6 | Mac | フォールバック（Helvetica） |
| `UtaWinTypoFamily` | 16 | Windows | フォールバック（Helvetica） |
| `UtaMacTypoFamily` | 16 | Mac | フォールバック（Helvetica） |

libass（この環境の CoreText バックエンド経由）が実際に照合するのは **Windows platform の nameID 1（family）・nameID 4（full name）だけ**。Mac platform の名前は nameID を問わず照合されず、PostScript name（6）・typographic family（16）は Windows platform でも照合されない。

`fonts.py` 冒頭のコメント「libass が照合する名前: family, full name, PostScript name, typographic family」は、この実測とは食い違っていた（PostScript name・typographic family は照合されない）。

## issue #138 の再現

上の結果は issue #138 の症状と一致する。issue の報告にあった name テーブル（nameID 1 の Mac に `Corporate Logo ver2`、nameID 1 の Windows に `Corporate Logo ver2 Bold`、nameID 4 の Windows に `Corporate Logo Bold ver2`、nameID 16 の Windows に `Corporate Logo ver2`）に当てはめると:

- `Corporate Logo ver2` → nameID 1 の Mac、nameID 16 の Windows にしか無い → **どちらも照合されない** → フォールバック（issue の症状と一致）
- `Corporate Logo Bold ver2` → nameID 4 の Windows にある → **照合される**（issue の症状と一致）

## 直し方

`fonts.read_font_names`（`fonts.py`）が索引に入れる名前を、nameID `{1, 4}` かつ platform が Windows（3）のものだけに絞った。これ以外の名前（Mac platform・nameID 6・nameID 16）は、今まで通り「見つからない（missing）」として扱われる。

キャッシュ（`fonts.load_index` が使う JSON）に保存する名前の集合が変わるため、`_CACHE_FORMAT` を上げて古いキャッシュを無効化した。

## fontconfig との違いについて

fontconfig（WSL・Linux で ffmpeg をビルドするときの一般的な構成）の `FcFreeTypeQuery` は、実装を読む限り nameID 16（typographic family）・Mac platform の名前も候補に含める可能性があり、この macOS・CoreText の実測結果とは異なる可能性がある。実際に fontconfig 版の libass で確かめるための Linux 環境（Docker 等）は、この調査では用意しなかった。

今回の直し方は「索引を狭める」方向（Windows platform の family・full name だけを対象にする）なので、**fontconfig で実際にはもっと広い範囲が照合できたとしても、utavideo 側は false negative（本当は見つかるはずのフォントを missing 扱いにする）に倒れるだけ**で、false positive（本来見つからないのに `check` を通してしまい、issue #138 の症状を再発させる）には倒れない。`check` の目的（書き出す前に問題を見つける）から見て、安全側の判断とした。

fontconfig 環境で実際に照合される範囲を確かめられたら、この記録に追記すること。
