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
RX, RY = 1080 / 1920, 1920 / 1080


def _convert(text: str = SOURCE, *, source_dir: str = ".") -> vertical.Conversion:
    source = pysubs2.SSAFile.from_string(text, format_="ass")
    return vertical.convert(source, size=(1080, 1920), video_file=VIDEO, source_dir=source_dir)


def test_script_info_and_project_point_at_the_vertical_size_and_underlay() -> None:
    script = _convert().script
    assert subs.play_res(script) == (1080, 1920)
    # 本編の LayoutRes が残ると、libass が文字を横に潰して描く
    assert subs.layout_res(script) == (1080, 1920)
    assert script.aegisub_project == {"Audio File": VIDEO, "Video File": VIDEO, "Active Line": "1"}


def test_layout_res_is_not_added_when_the_source_has_none() -> None:
    source = SOURCE.replace("LayoutResX: 1920\nLayoutResY: 1080\n", "")
    assert "LayoutResX" not in _convert(source).script.info


def test_layout_res_keeps_its_scale_against_play_res() -> None:
    # 縦横比が同じで大きさの違う LayoutRes（4K の下敷き）は、\blur の効き方が変わらないよう同じ比で変える
    source = SOURCE.replace("LayoutResX: 1920\nLayoutResY: 1080", "LayoutResX: 3840\nLayoutResY: 2160")
    assert subs.layout_res(_convert(source).script) == (2160, 3840)


def test_audio_file_other_than_the_underlay_is_kept() -> None:
    source = SOURCE.replace("Audio File: ../build/preview/bg.mp4", "Audio File: ../src/mix/song.wav")
    assert _convert(source).script.aegisub_project["Audio File"] == "../src/mix/song.wav"


def test_project_paths_are_rebased_to_the_vertical_ass_folder() -> None:
    source = SOURCE.replace(
        "Audio File: ../build/preview/bg.mp4",
        "Audio File: ../mix/song.wav\nKeyframes File: keys.txt\nTimecodes File: C:\\tc.txt",
    )
    script = _convert(source, source_dir="..").script
    project = script.aegisub_project
    assert (project["Audio File"], project["Keyframes File"]) == ("../../mix/song.wav", "../keys.txt")
    assert project["Timecodes File"] == "C:\\tc.txt"  # 絶対パスはそのまま


@pytest.mark.parametrize(
    "audio", ["?video", "dummy-audio:silence?sr=44100&bd=16&ch=1&ln=396900", "/abs/a.wav"]
)
def test_project_values_that_are_not_relative_paths_are_kept(audio: str) -> None:
    source = SOURCE.replace("Audio File: ../build/preview/bg.mp4", f"Audio File: {audio}")
    script = _convert(source, source_dir="..").script
    assert script.aegisub_project["Audio File"] == audio


def test_styles_shrink_by_the_width_ratio() -> None:
    lyrics = _convert().script.styles["Lyrics"]
    assert (lyrics.fontsize, lyrics.spacing, lyrics.outline, lyrics.shadow) == (56.25, 1.12, 2.25, 0.56)
    assert (lyrics.marginl, lyrics.marginr, lyrics.marginv) == (68, 68, 51)


def test_short_and_band_styles_are_added_with_the_lyrics_font() -> None:
    styles = _convert().script.styles
    assert styles["Short"].fontname == "Lyrics Font"
    assert styles["VerticalBand"].fontname == "Lyrics Font"
    assert styles["VerticalBand"].alignment == pysubs2.Alignment.TOP_CENTER


def test_existing_short_style_is_kept() -> None:
    source = SOURCE.replace(
        "[Events]", "Style: Short,Other,20,&H0,&H0,&H0,&H0,0,0,0,0,100,100,0,0,1,0,0,2,0,0,0,1\n\n[Events]"
    )
    assert _convert(source).script.styles["Short"].fontname == "Other"


def test_band_style_margin_v_is_unchanged_without_a_video_size() -> None:
    # band_video_size を渡さなければ、Lyrics スタイルを継承した MarginV のまま
    styles = _convert().script.styles
    assert styles["VerticalBand"].marginv == styles["Lyrics"].marginv


def test_band_style_margin_v_fits_the_band_when_a_video_size_is_given() -> None:
    source = pysubs2.SSAFile.from_string(SOURCE, format_="ass")
    conversion = vertical.convert(
        source, size=(1080, 1920), video_file=VIDEO, band_video_size=(1920, 1080), band_frame_y=0.5
    )
    band = conversion.script.styles["VerticalBand"]
    # 本編（1920x1080）を幅 1080 に縮めた高さは 608。上帯の高さは (1920 - 608) * 0.5 = 656
    # フォントサイズは Lyrics と同じ比で縮んだ 56.25（test_styles_shrink_by_the_width_ratio と同じ値）
    assert band.marginv == round((656 - 56.25) / 2) == 300


def test_band_style_margin_v_is_zero_when_the_band_is_thinner_than_the_font() -> None:
    source = pysubs2.SSAFile.from_string(SOURCE, format_="ass")
    conversion = vertical.convert(
        source, size=(1080, 1920), video_file=VIDEO, band_video_size=(1920, 1080), band_frame_y=0.02
    )
    assert conversion.script.styles["VerticalBand"].marginv == 0


def test_events_are_copied_with_margins_and_tags_converted() -> None:
    source = pysubs2.SSAFile.from_string(SOURCE, format_="ass")
    conversion = vertical.convert(source, size=(1080, 1920), video_file=VIDEO)

    comment = conversion.script.events[1]
    assert comment.type == "Comment"
    assert (comment.marginl, comment.marginv) == (22, 11)
    assert comment.text == r"{\pos(540,960)}コメント行も変換する"
    assert conversion.unconverted == []
    # 元の .ass は変えない
    assert source.events[1].text == r"{\pos(960,540)}コメント行も変換する"
    assert subs.play_res(source) == (1920, 1080)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (r"{\pos(960,540)\org(0, 1080)}あ", r"{\pos(540,960)\org(0,1920)}あ"),
        (r"{\move(0,108,1920,54,100,500)}あ", r"{\move(0,192,1080,96,100,500)}あ"),
        (
            r"{\clip(0,0,960,540)\iclip(10,10,20,20)}あ",
            r"{\clip(0,0,540,960)\iclip(5.62,17.78,11.25,35.56)}あ",
        ),
        (r"{\fs80\fsp4\bord8\xbord4\yshad-2}あ", r"{\fs45\fsp2.25\bord4.5\xbord2.25\yshad-1.12}あ"),
        (r"{\blur6\t(\blur2)}あ", r"{\blur3.38\t(\blur1.12)}あ"),
        # \be は回数。幅の比の2乗倍にして四捨五入し、1回以上は1回以上に保つ
        (r"{\be5}あ{\be10}い{\be1}う{\be2.5}え{\be0}お", r"{\be2}あ{\be3}い{\be1}う{\be1}え{\be0}お"),
        # 変えないもの: 倍率・相対指定・時刻・行の文字
        (
            r"{\fscx120\fscy80\fs+2\t(0,500,\fs40)}\pos(1,2)",
            r"{\fscx120\fscy80\fs+2\t(0,500,\fs22.5)}\pos(1,2)",
        ),
        (r"{\pos(1,2,3)}引数の数が違う", r"{\pos(1,2,3)}引数の数が違う"),
    ],
)
def test_convert_tags(text: str, expected: str) -> None:
    assert vertical.convert_tags(text, RX, RY) == (expected, [])


def test_drawings_and_vector_clips_are_reported_and_left_as_is() -> None:
    text = r"{\clip(m 0 0 l 100 0 100 100)\p1}m 0 0 l 1920 0 1920 1080"
    assert vertical.convert_tags(text, RX, RY) == (text, ["図形（\\p）", "ベクターの \\clip"])

    source = SOURCE + "Dialogue: 0,0:00:05.00,0:00:06.00,Lyrics,,0,0,0,,{\\p1}m 0 0 l 10 0 10 10\n"
    unconverted = _convert(source).unconverted
    assert len(unconverted) == 1 and "0:00:05" in unconverted[0]


def test_source_without_play_res_is_rejected() -> None:
    source = SOURCE.replace("PlayResX: 1920\nPlayResY: 1080\n", "")
    with pytest.raises(subs.SubtitleError, match="PlayResX"):
        _convert(source)
