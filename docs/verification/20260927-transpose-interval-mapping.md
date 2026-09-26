# 2026-09-27 MuseScore CLIの--transposeの挙動（issue #144）の検証記録

`inst` の楽譜表示（issue #139・#143）を `--keys` の移調に連動させるにあたり、MuseScore CLIの
`--transpose` オプションの挙動を実測した記録。

## 環境

- macOS、MuseScore 4.7.5（`/Applications/MuseScore 4.app/Contents/MacOS/mscore`）
- 動作確認に使った楽譜: ユーザー提供の実際の .mscz（438音符）

## `--score-transpose` ではなく `--transpose` を使う

`mscore --help` で確認したところ、移調に使えるオプションは `--transpose <JSON>` であり、
似た名前の `--score-transpose` は別の（JSONエクスポート専用の）オプションだった。WebSearchでは
`--transpose` 自体もMuseScore 4.5.2で壊れているという報告があったが、鵜呑みにせず実際に手元の
4.7.5で動くことを確認した上で採用した。

JSONの形式: `{"mode": "by_interval", "direction": "up"|"down", "transposeInterval": N,
"transposeKeySignatures": bool, "transposeChordNames": bool}`。`-o out.musicxml` と組み合わせて
`--transpose '{...}' -o out.musicxml in.mscz` とすると、移調してMusicXMLへの変換まで1回のCLI
呼び出しで済む（`.mscz`への書き出しを経由しなくてよい）ことも確認した。

## `transposeInterval` は半音に線形対応しない

`transposeInterval` を0〜25まで総当たりし、実際の楽曲（438音符）の移調前後のMIDI相当の音高を
比較したところ、次のように半音数に対応した（各値は438音符すべてで一律だった）。

```
transposeInterval -> 半音数:
0:0, 1:1, 2:0, 3:1, 4:2, 5:3, 6:2, 7:3, 8:4, 9:5, 10:4, 11:5, 12:6, 13:6,
14:7, 15:8, 16:7, 17:8, 18:9, 19:10, 20:9, 21:10, 22:11, 23:12, 24:11, 25:12
```

同じ半音数に複数の `transposeInterval` が対応する（異名同音の音程の違い。例:
半音2は`transposeInterval`2か4のどちらでも実現できるが、前者は減三度、後者は長二度）。
実装では、なるべく増減音程を避けた標準的な音程名になる値を選んだ
（`src/utavideo/score.py`の`_SEMITONE_TO_INTERVAL`）。

`transposeInterval` が25を超える値・負の値は、**エラーメッセージも無いまま出力ファイルが
作られずに失敗する**（黙って失敗する）ことも確認した。1回の`--transpose`で動かせるのは
1オクターブ分（半音±12相当）までなので、それを超える移調は`--transpose`を繰り返し適用する
（`to_musicxml`が`divmod(semitones, 12)`でオクターブ分と残りの半音分に分け、オクターブ分は
`transposeInterval=25`を繰り返し適用してから、最後に残りの半音分を1回適用する）。

2オクターブ上（+24半音）・1オクターブ+2半音下（-14半音）でこの繰り返し適用を検証し、
どちらも期待通りの音高になることを確認した（`tests/test_score.py`に回帰テストとして追加）。
