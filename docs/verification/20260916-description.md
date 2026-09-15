# 2026-09-16 概要欄の生成の検証記録

## 投稿サイトの上限

YouTube Data API の videos リソースの説明（https://developers.google.com/youtube/v3/docs/videos）で確認した。

- `snippet.title`：最大 100 文字。`<` と `>` は使えない
- `snippet.description`：最大 5000 バイト。`<` と `>` は使えない

`check` の警告はこの値を使う（`description.py` の `TITLE_MAX_CHARS`・`BODY_MAX_BYTES`）。

## 書式の設定で表せる範囲

歌ってみた動画の実際の概要欄 20 本を調べると、次の書き方が混ざっていた。

- 見出しの記号（`■原曲` / `❖ 本家動画様`）、見出し同士の空行の有無、ハッシュタグの前の空行の有無
- 役割の組み合わせを見出しにして1人を書く（`■Vocal, Mix` の下に1人）/ 1つの役割の下に複数人を書く（`❖ 歌唱` の下に2人）
- 名前と URL を同じ行に書く / 別の行に書く
- 原曲の URL が2つ（動画サイトごと）ある

いずれも `heading`・`original_heading`・`section_gap`・`hashtags_gap`・`name_url_separator` の設定と、「`roles` の並びが同じ人を1つの見出しにまとめる」規則で表せる。`tests/test_description.py` の2つの書式のテストで確かめている。
