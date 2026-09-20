# utavideo の見本

`utavideo sample` が作った、動作確認用の曲フォルダです。音源・背景・歌詞・フォントはすべて合成したもので、曲名・人・URL は架空です。
書き出したものが要らなくなったら、このフォルダごと消してください。

$font_note

## 試すこと

```sh
utavideo check        # 検査（わざと警告の出る行が入っています）
utavideo preview-bg   # build/preview/bg.mp4（Aegisub で開く用）
utavideo build        # build/main.mp4
utavideo description  # build/title.txt・build/description.txt
utavideo release      # release/sample-v1.0.0.mp4
utavideo overlay      # build/overlay.mov（透過。大きいので必要なときだけ）
```

- 見本の中身とコマンドの説明: https://github.com/ngtkana/utavideo/blob/main/docs/commands.md
- 背景の形式を変えて試すときは `utavideo.toml` の `video.background` を書き換えます
