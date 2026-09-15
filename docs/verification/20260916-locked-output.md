# 2026-09-16 出力先が他のアプリで開かれているときの置き換え

`.partial` に書き出した後の置き換え（`os.replace`）が、出力先を Windows のアプリが開いていると失敗する件（issue #3）の記録。

## 環境

- WSL2 上の Ubuntu 24.04、Windows のドライブ（drvfs）上のフォルダ
- Windows 側は `powershell.exe` の `[IO.File]::Open(path, 'Open', 'Read', <FileShare>)` でファイルを開いたままにした

## 置き換えの結果

同じフォルダの `out.partial.mp4` で、開いたままの `out.mp4` を `os.replace` で置き換えた。

| 開き方 | `os.replace` | `.partial` |
|---|---|---|
| `FileShare.Read` | `PermissionError`（errno 13） | 残る |
| `FileShare.ReadWrite` | `PermissionError`（errno 13） | 残る |
| `FileShare.ReadWrite, Delete` | 成功 | — |

- Linux 側の権限に関係なく、`EACCES` になる。errno だけでは権限不足と区別できない
- ただし `.partial` は同じフォルダに書けているので、置き換えで `EACCES` が出たら原因はほぼ「他のアプリが開いている」と判断した
- issue #3 では、読み取り専用属性（`attrib +R`）のファイルは置き換えが通ること、書き込み用に開けるか（`r+b`）では判定できないこと（`FileShare.ReadWrite` だと開けるのに置き換えは失敗する）も確認している
- ロックしているプロセス名は Windows の Restart Manager API で取れるが、WSL と `powershell.exe` に依存するので使わなかった

## コマンドでの確認

Windows の一時フォルダに曲フォルダを作り、`build/preview/bg.mp4` を `FileShare.Read` で開いたまま `utavideo preview-bg` を実行した。

- 終了コード 1。「他のアプリ（動画プレイヤー、エクスプローラーのプレビューなど）で開かれていないか確認してください」と、`bg.partial.mp4` が残っていることが表示された
- `bg.partial.mp4` は残っていた
- ファイルを閉じてから実行し直すと成功し、`bg.partial.mp4` は無くなった
