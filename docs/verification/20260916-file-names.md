# 2026-09-16 フォルダ名・ファイル名に使える文字

`song.slug`（[project-layout.md](../project-layout.md#名前の付け方)）の検査を決めるために調べた。

## 実測（WSL2 から Windows のドライブ上に作成）

| 試したこと | 結果 |
|---|---|
| 曲名 `Mr.` からフォルダ名を作る | `20260915 Mr.`（末尾が点） |
| 末尾が点の名前を WSL から作る | 作れるが、Windows からは「存在しない」と言われて開けない |
| `CON` という名前を WSL から作る | 同じく開けない |
| `:` や `?` を含む名前を WSL から作る | Windows 側では私用領域の文字（U+F03A など）に化ける |

WSL から作れてしまうので、utavideo 側で止めないと、後から Windows で開けない曲フォルダができる。

## 調べたこと

- 名前に使う識別子を表示名と分けるのは定石。VS Code 拡張機能は `name` と `displayName`、Hugo は `title` と `slug`、VFX の制作では作品名を略した showID をフォルダ名に使う
- 安全な文字は英数字・`.`・`_`・`-`（POSIX の Portable Filename Character Set）。先頭の `-` は避ける
- Windows で使えない名前は `\ / : * ? " < > |` と制御文字、末尾の空白と点、`CON` `PRN` `AUX` `NUL` `COM1`〜`COM9` `LPT1`〜`LPT9`（拡張子を付けても同じ）
- 日本語からローマ字の slug を自動で作るのは頼れない。Unidecode などは漢字を中国語の読みにする（「東京タワー」→ `Dong Jing tawa`）ので、自動変換はしない

出典：[Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file)、[POSIX](https://pubs.opengroup.org/onlinepubs/9799919799/basedefs/V1_chap03.html)、[VS Code](https://code.visualstudio.com/api/references/extension-manifest)、[Hugo](https://gohugo.io/content-management/urls/)

## 決めたこと

- 利用者が `--slug` や `utavideo.toml` で指定した名前は書き換えず、上の使えない名前ならエラーにする（黙って直すと、指定した名前と違うファイルができる）
- 長さの上限は 200 文字。`-v1.2.mp4` のような接尾辞を足しても、ファイル名の上限（255）に収まる
- ASCII 以外は使えるので、`check` の警告だけにする
