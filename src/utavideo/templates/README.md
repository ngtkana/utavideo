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
- [ ] 投稿したら `utavideo.toml` の `[[uploads]]` に動画の URL を書く → `utavideo announce` → `build/announce.txt` で SNS に告知する

## メモ
