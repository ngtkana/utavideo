# ロードマップ

## 実装済み

背景（画像・GIF・動画）＋ 歌詞 ＋ 曲名表示 ＋ 音声の動画を書き出す。

- コマンド: `new` / `init` / `preview-bg` / `check` / `build` / `overlay` / `release`
- `check`: 設定・素材・スタイル・フォントの検査、行の重なり・`\pos`・はみ出しの警告

## 予定

### 概要欄の文章

`utavideo.toml` に書いたクレジットと素材から、動画投稿サイトの概要欄とタイトルを作る。

- `utavideo description`：タイトルを `build/title.txt`、概要欄を `build/description.txt` に書き出し、画面にも表示する（投稿画面の欄ごとに、ファイルを丸ごとコピーできるように分ける）
- `release`：`[description]` がある曲では `release/<曲名> <バージョン>.txt`（タイトル、空行、概要欄）も置く。書式を後で変えても、公開したときの文章が残る
- `utavideo.toml`
  - `song.original_urls`：原曲の URL（複数可）
  - `[[credits]]`：`roles`・`name`・`urls`。`roles` の並びが同じ人は1つの見出しにまとめる（例: 見出し「歌唱」の下に2人、見出し「Vocal, Mix」の下に1人）
  - `[[materials]]`：`section`（例: イラスト、Inst、使用素材）・`urls`・`files`（その素材を使ったファイル）。同じ `section` は1つの見出しにまとめる。`urls` が空のもの（自作の素材など）は出力しない
  - `[description]`：`text`（冒頭の手書きの文章）・`hashtags`（その曲のハッシュタグすべて）・`title`（自動で作るタイトルを使わないとき）
- ユーザー設定（`~/.config/utavideo/config.toml`）
  - `[description]`：書式。タイトルの形（`{title}`・`{artist}`・`{singers}`）、`{singers}` に入れる役割と名前の区切り、見出しの形（例: `"■{section}"`）、原曲の見出しの名前、役割の区切り、名前と URL の区切り（`"\n"` なら別の行）、ブロックの順番、見出し同士とハッシュタグの前の空行の数。変えられるのは設定項目の範囲だけにして、テンプレートエンジンは使わない
  - `[defaults]`：`credits` と `hashtags` の既定値。`new` / `init` のときに曲の `utavideo.toml` にコピーする（ユーザー設定を後で変えても、既存の曲は変わらない）
- `check`
  - 使っている素材ファイル（`video.background` など）が、どの `materials.files` にも無ければ警告する
  - `materials.files` のファイルが無い、`{singers}` に入る人がいない、投稿サイトの文字数の上限を超える、のいずれかで警告する。タイトルの形に使えない名前があればエラー
- 後回し
  - 通し番号、前後の動画へのリンク、他サイト版へのリンク（他の曲フォルダの情報や投稿後に決まる URL が要る。手で書くと番号や URL を間違えやすいので、いずれ自動にしたい）
  - よく使う素材をユーザー設定に登録し、名前で参照する

### アバターの合成

ブルーバック・グリーンバックで録画したアバター動画を背景に合成する。

- `[avatar]`
  - `file`：録画した動画
  - `key`：抜く色、`similarity`、`blend`、`despill`（ffmpeg の `colorkey` と `despill` を使う）
  - `scale`・`position`：大きさと、アンカー＋余白での位置
  - `offset`：録画と音源のズレ（秒）
- `sync = "auto"`：録画に入っている音声と音源の相互相関を取り、ズレを自動で求める。`check` で求めた値を表示する
- `[[layers]]`：背景の上に画像・GIF を複数重ねる（位置・大きさ・表示する区間）
- 背景をゆっくり拡大・移動させる（Ken Burns 効果）

### 縦型版・ショート動画

- `[variants.<名前>]`：`size` とスタイルの上書き（例: `styles.Lyrics = { fontsize = 56, alignment = 5 }`）
  - 同じ `lyrics.ass` から、PlayRes を書き換えた .ass を作る
  - `\pos` の座標は解像度の比で変換する
  - `build --variant vertical`、`preview-bg --variant vertical`
- `[[shorts]]`：`name`・`start`・`end`・`variant`。`build --shorts` で `build/shorts-<name>.mp4` を書き出す
- はみ出しの検査を派生版ごとに行う。`\pos` の行も、位置と配置から幅を概算して対象にする

### カラオケ用の音源動画

- 概要欄と同じ `[[credits]]` から、クレジットを並べた画面を自動で作る
- `utavideo inst --keys -1,-2,-3`：ffmpeg の `rubberband` でキーを変えた版を書き出す
- 音量をそろえる（`loudnorm`）

### その他

- `utavideo still --at 1:23`：サムネイル用の静止画（歌詞・曲名表示の有無を選べる）
