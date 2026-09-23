# 2026-09-23 inst の loudnorm・atempo フォールバックの検証記録

`utavideo inst` に音量正規化（`loudnorm`）と rubberband 非対応環境向けフォールバック（`asetrate`+`atempo`）を追加するにあたっての実測。

## 環境

- macOS、ffmpeg 8.0（rubberband 対応ビルド）

## loudnorm の JSON 出力は stderr に出る

`loudnorm=...:print_format=json` を `-f null -` で実行すると、JSON ブロックは **stderr** に出る（stdout は空）。

```
ffmpeg -hide_banner -nostdin -i test-tone.wav \
  -af "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json" -f null -
```

```
[Parsed_loudnorm_0 @ ...]
{
	"input_i" : "-21.05",
	"input_tp" : "-18.06",
	"input_lra" : "0.00",
	"input_thresh" : "-31.05",
	"output_i" : "-16.05",
	...
	"target_offset" : "0.05"
}
```

libass・rubberband の検出（`subtitles_filter_error`・`rubberband_filter_error`）と同じ理由で、ビルドによって stdout に出る可能性もゼロではないため、`measure_loudness`（`ffmpeg.py`）は stdout・stderr の両方を対象に正規表現でJSONブロックを探す実装にした。

## atempo チェーンの分解結果

`_atempo_chain`（`graph.py`）の実装を、代表的なキー変更で手計算・実行の両方で確認した。

| キー（半音） | ratio（周波数比） | tempo（1/ratio） | atempo チェーン |
|---|---|---|---|
| 0 | 1.0 | 1.0 | なし |
| +2 | 1.122462 | 0.890899 | `atempo=0.890899` |
| -12（1オクターブ下） | 0.5 | 2.0 | `atempo=2` |
| +24（2オクターブ上） | 4.0 | 0.25 | `atempo=0.5,atempo=0.5` |
| -24（2オクターブ下） | 0.25 | 4.0 | `atempo=2,atempo=2` |

`tests/test_graph.py` の `test_atempo_chain_splits_extreme_ratios` 等でユニットテスト化済み。

## loudnorm 適用後の実測

`utavideo inst`（既定キー0、rubberband 使用）で書き出した `key0.mp4` に対して `measure_loudness` を再実行し、統合ラウドネスが目標値（-16 LUFS）の近傍に収まることを確認した（`tests/test_render.py::test_inst_normalizes_loudness_to_the_target`、許容誤差 ±1.0 LUFS）。

## rubberband フォールバックの動作確認

手元の ffmpeg は rubberband 対応ビルドのため、`cli.rubberband_filter_error` を monkeypatch で強制的に無効化して atempo 経路を通した（`tests/test_render.py::test_inst_falls_back_to_atempo_when_rubberband_is_unavailable`）。出力ファイルが書き出され、複数キー間で動画の長さが一致することを確認した（asetrate/atempo は音声のみのフィルタで、映像のフレーム数には影響しないため）。
