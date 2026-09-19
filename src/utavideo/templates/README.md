# 曲フォルダ

utavideo の曲フォルダ。制作の流れ: https://github.com/ngtkana/utavideo/blob/main/docs/workflow.md

## チェックリスト

- [ ] 音源を `src/mix/`（ファイル名に `vX.Y`）、背景を `src/bg/` に置き、`utavideo.toml` を合わせる
- [ ] `utavideo.toml` の `song` を埋める
- [ ] `utavideo preview-bg` → Aegisub で `src/lyrics.ass` と `build/preview/bg.mp4` を開いて歌詞を入れる
- [ ] `utavideo check`
- [ ] `utavideo build` → `build/main.mp4` を確認
- [ ] `utavideo release`
- [ ] `utavideo thumbnail --bg-only` → Aegisub で `src/thumbnail.ass` を開いて文字を組む → `utavideo thumbnail`
- [ ] `utavideo description` → `build/title.txt`・`build/description.txt` を投稿画面に貼る
- [ ] 縦型のショートを作るなら、`utavideo.toml` に `[vertical]`（画面の作り方 `layout`）を書く → `utavideo vertical-ass` → `utavideo preview-bg --vertical` → Aegisub で `src/vertical.ass` を組み、区間を置く → `utavideo.toml` に `[[shorts]]` → `utavideo shorts`

## メモ
