"""縦用 .ass の雛形への変換。"""

import pysubs2
import pytest

from utavideo import subs, vertical

STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
    "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
    "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
)
SOURCE = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
LayoutResX: 1920
LayoutResY: 1080

[Aegisub Project Garbage]
Audio File: ../build/preview/bg.mp4
Video File: ../build/preview/bg.mp4
Video AR Mode: 4
Video AR Value: 1.777778
Video Zoom Percent: 0.5
Active Line: 1

[V4+ Styles]
{STYLE_FORMAT}
Style: Title,Title Font,36,&H00FFFFFF,&H000000FF,&H00403030,&H80000000,-1,0,0,0,100,100,0,0,1,3,0,9,40,40,30,1
Style: Lyrics,Lyrics Font,100,&H00FFFFFF,&H000000FF,&H0,&H0,-1,0,0,0,100,100,2,0,1,4,1,2,120,120,90,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.00,Lyrics,,0,0,0,,歌詞
Comment: 0,0:00:03.00,0:00:04.00,Lyrics,,40,0,20,,{{\\pos(960,540)}}コメント行も変換する
"""
VIDEO = "../build/preview/vertical-bg.mp4"


def _convert(
    text: str = SOURCE,
    *,
    source_dir: str = ".",
    band_video_size: tuple[int, int] = (1920, 1080),
) -> pysubs2.SSAFile:
    source = pysubs2.SSAFile.from_string(text, format_="ass")
    return vertical.convert(
        source,
        size=(1080, 1920),
        video_file=VIDEO,
        source_dir=source_dir,
        band_video_size=band_video_size,
    )


def test_script_info_and_project_point_at_the_vertical_size_and_underlay() -> None:
    script = _convert()
    assert subs.play_res(script) == (1080, 1920)
    # 本編の LayoutRes が残ると、libass が文字を横に潰して描く
    assert subs.layout_res(script) == (1080, 1920)
    assert script.aegisub_project == {"Audio File": VIDEO, "Video File": VIDEO, "Active Line": "1"}


def test_layout_res_is_not_added_when_the_source_has_none() -> None:
    source = SOURCE.replace("LayoutResX: 1920\nLayoutResY: 1080\n", "")
    assert "LayoutResX" not in _convert(source).info


def test_layout_res_keeps_its_scale_against_play_res() -> None:
    # 縦横比が同じで大きさの違う LayoutRes（4K の下敷き）は、\blur の効き方が変わらないよう同じ比で変える
    source = SOURCE.replace("LayoutResX: 1920\nLayoutResY: 1080", "LayoutResX: 3840\nLayoutResY: 2160")
    assert subs.layout_res(_convert(source)) == (2160, 3840)


def test_audio_file_other_than_the_underlay_is_kept() -> None:
    source = SOURCE.replace("Audio File: ../build/preview/bg.mp4", "Audio File: ../src/mix/song.wav")
    assert _convert(source).aegisub_project["Audio File"] == "../src/mix/song.wav"


def test_project_paths_are_rebased_to_the_vertical_ass_folder() -> None:
    source = SOURCE.replace(
        "Audio File: ../build/preview/bg.mp4",
        "Audio File: ../mix/song.wav\nKeyframes File: keys.txt\nTimecodes File: C:\\tc.txt",
    )
    project = _convert(source, source_dir="..").aegisub_project
    assert (project["Audio File"], project["Keyframes File"]) == ("../../mix/song.wav", "../keys.txt")
    assert project["Timecodes File"] == "C:\\tc.txt"  # 絶対パスはそのまま


@pytest.mark.parametrize(
    "audio", ["?video", "dummy-audio:silence?sr=44100&bd=16&ch=1&ln=396900", "/abs/a.wav"]
)
def test_project_values_that_are_not_relative_paths_are_kept(audio: str) -> None:
    source = SOURCE.replace("Audio File: ../build/preview/bg.mp4", f"Audio File: {audio}")
    assert _convert(source, source_dir="..").aegisub_project["Audio File"] == audio


def test_styles_shrink_by_the_width_ratio() -> None:
    lyrics = _convert().styles["Lyrics"]
    assert (lyrics.fontsize, lyrics.spacing, lyrics.outline, lyrics.shadow) == (56.25, 1.12, 2.25, 0.56)
    assert (lyrics.marginl, lyrics.marginr, lyrics.marginv) == (68, 68, 51)


def test_short_and_band_styles_are_added_with_the_lyrics_font() -> None:
    styles = _convert().styles
    assert styles["Short"].fontname == "Lyrics Font"
    assert styles["VerticalBand"].fontname == "Lyrics Font"
    assert styles["VerticalBand"].alignment == pysubs2.Alignment.TOP_CENTER


def test_existing_short_style_is_kept() -> None:
    source = SOURCE.replace(
        "[Events]", "Style: Short,Other,20,&H0,&H0,&H0,&H0,0,0,0,0,100,100,0,0,1,0,0,2,0,0,0,1\n\n[Events]"
    )
    assert _convert(source).styles["Short"].fontname == "Other"


def test_band_style_margin_v_fits_the_band_when_a_video_size_is_given() -> None:
    band = _convert(band_video_size=(1920, 1080)).styles["VerticalBand"]
    # 本編（1920x1080）を幅 1080 に縮めた高さは 608。本編は中央に置くので、上帯の高さは (1920 - 608) / 2 = 656
    # フォントサイズは Lyrics と同じ比で縮んだ 56.25（test_styles_shrink_by_the_width_ratio と同じ値）
    assert band.marginv == round((656 - 56.25) / 2) == 300


def test_band_style_margin_v_is_zero_when_the_band_is_thinner_than_the_font() -> None:
    # 本編と同じ縦横比（1080x1920）なら幅いっぱいに縮めても縦を埋め、帯の高さは 0 になる
    band = _convert(band_video_size=(1080, 1920)).styles["VerticalBand"]
    assert band.marginv == 0


def test_events_are_not_copied() -> None:
    # 歌詞は本編の映像に入るので、縦用 .ass にはスタイルだけを写し、行は写さない
    script = _convert()
    assert script.events == []


def test_source_without_play_res_is_rejected() -> None:
    source = SOURCE.replace("PlayResX: 1920\nPlayResY: 1080\n", "")
    with pytest.raises(subs.SubtitleError, match="PlayResX"):
        _convert(source)
