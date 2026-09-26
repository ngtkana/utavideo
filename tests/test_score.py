"""score.py: .mscz→MusicXML→Verovio→PNG の描画パイプライン。"""

import hashlib
import subprocess
from pathlib import Path

import pytest

from utavideo import score

# 拍子/調号変更・臨時記号・3連符・タイ・歌詞・コード記号・リハーサルマークを含む最小の楽譜。
# テンポのメトロノーム記号はSMuFLの私用領域の文字(U+ECA5)で埋め込まれることが多く、MuseScoreは
# "Leland Text"のようなフォント名で書き出すが、Verovioは実在しない"Leipzig"というフォント名に
# 書き換えて出力する(issue #140で発見)。ここではその文字を直接埋め込んで再現する。
_MUSICXML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>Vocal</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>6</divisions><key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <direction placement="above"><direction-type><rehearsal>A</rehearsal></direction-type></direction>
      <direction placement="above">
        <direction-type>
          <words font-family="Leland Text" font-size="12">&#xECA5; = 120</words>
        </direction-type>
      </direction>
      <harmony><root><root-step>C</root-step></root><kind>major-seventh</kind></harmony>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>6</duration><voice>1</voice><type>quarter</type>
        <lyric number="1"><syllabic>begin</syllabic><text>ね</text></lyric></note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>6</duration><voice>1</voice><type>quarter</type>
        <lyric number="1"><syllabic>end</syllabic><text>こ</text></lyric></note>
      <note><pitch><step>F</step><alter>1</alter><octave>4</octave></pitch><duration>3</duration><voice>1</voice><type>eighth</type>
        <accidental>sharp</accidental>
        <time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes></time-modification>
        <notations><tuplet type="start" bracket="yes"/></notations>
        <lyric number="1"><text>ろ</text></lyric></note>
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>3</duration><voice>1</voice><type>eighth</type>
        <time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes></time-modification>
        <lyric number="1"><text>ば</text></lyric></note>
      <note><pitch><step>A</step><octave>4</octave></pitch><duration>3</duration><voice>1</voice><type>eighth</type>
        <time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes></time-modification>
        <notations><tuplet type="stop"/></notations>
        <lyric number="1"><text>え</text></lyric></note>
      <note><pitch><step>C</step><octave>5</octave></pitch><duration>6</duration><voice>1</voice><type>quarter</type>
        <tie type="start"/><notations><tied type="start"/></notations>
        <lyric number="1"><text>し</text></lyric></note>
    </measure>
    <measure number="2">
      <attributes><key><fifths>1</fifths></key><time><beats>3</beats><beat-type>4</beat-type></time></attributes>
      <direction placement="above"><direction-type><rehearsal>B</rehearsal></direction-type></direction>
      <harmony><root><root-step>G</root-step></root><kind>major</kind></harmony>
      <note><pitch><step>C</step><octave>5</octave></pitch><duration>6</duration><voice>1</voice><type>quarter</type>
        <tie type="stop"/><notations><tied type="stop"/></notations>
        <lyric number="1"><text>て</text></lyric></note>
      <note><pitch><step>C</step><alter>1</alter><octave>5</octave></pitch><duration>6</duration><voice>1</voice><type>quarter</type>
        <accidental>sharp</accidental>
        <lyric number="1"><text>な</text></lyric></note>
      <note><rest/><duration>6</duration><voice>1</voice><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>
"""


# テンポ変化(120→60)・和音・休符を含む、note_events()の検証専用の楽譜。
_TEMPO_CHANGE_MUSICXML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>Vocal</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>6</divisions><key><fifths>0</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
        <clef><sign>G</sign><line>2</line></clef>
      </attributes>
      <direction><sound tempo="120"/></direction>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>6</duration><voice>1</voice><type>quarter</type></note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>6</duration><voice>1</voice><type>quarter</type></note>
      <note><rest/><duration>6</duration><voice>1</voice><type>quarter</type></note>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>6</duration><voice>1</voice><type>quarter</type></note>
    </measure>
    <measure number="2">
      <direction><sound tempo="60"/></direction>
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>6</duration><voice>1</voice><type>quarter</type></note>
      <note><chord/><pitch><step>C</step><octave>5</octave></pitch><duration>6</duration><voice>1</voice><type>quarter</type></note>
      <note><pitch><step>A</step><octave>4</octave></pitch><duration>12</duration><voice>1</voice><type>half</type></note>
    </measure>
  </part>
</score-partwise>
"""


def test_render_horizontal_svg_returns_svg() -> None:
    svg = score.render_horizontal_svg(_MUSICXML)
    assert svg.startswith("<?xml") or "<svg" in svg[:200]


def test_note_events_are_sorted_by_time_and_increasing_in_x() -> None:
    events = score.note_events(_TEMPO_CHANGE_MUSICXML)
    times = [e.time_s for e in events]
    xs = [e.x for e in events]
    assert times == sorted(times)
    assert xs == sorted(xs)


def test_note_events_reflects_tempo_change() -> None:
    """120bpmの四分音符は0.5秒、60bpmの四分音符は1.0秒(ちょうど2倍)になる。"""
    events = score.note_events(_TEMPO_CHANGE_MUSICXML)
    # 1小節目: C(120bpm, 0秒) D(0.5秒) 休符 E(1.5秒、休符ぶん1秒分空く)
    assert events[0].time_s == pytest.approx(0.0)
    assert events[1].time_s == pytest.approx(0.5)
    assert events[2].time_s == pytest.approx(1.5)
    # 2小節目: G+C5の和音(60bpmで2秒)、A(3秒)
    assert events[3].time_s == pytest.approx(2.0)
    assert events[4].time_s == pytest.approx(3.0)


def test_note_events_merges_chord_into_one_point() -> None:
    """和音（同時に鳴る音符）は1つの点にまとめる。"""
    events = score.note_events(_TEMPO_CHANGE_MUSICXML)
    assert len(events) == 5  # C, D, E, [G+C5], A の5点（休符は含まない）


def test_substitute_missing_font_with_wrong_font_name() -> None:
    """Verovioは実在しない"Leipzig"フォント名でSMuFL文字を書き出すことがある(issue #140)。"""
    svg = f'<tspan font-family="Leipzig" font-size="720px">{chr(0xECA5)}</tspan>'
    substituted = score._substitute_missing_font(svg)
    assert "Leipzig" not in substituted
    assert 'font-family="Bravura Text"' in substituted
    assert chr(0xECA5) in substituted


def test_substitute_missing_font_without_font_attribute() -> None:
    """font-family属性自体が無いままSMuFL文字が出てくることもある(実データで確認済み)。"""
    svg = f'<tspan font-size="405px">{chr(0xECA5)} = 120</tspan>'
    substituted = score._substitute_missing_font(svg)
    assert 'font-family="Bravura Text"' in substituted


def test_substitute_missing_font_leaves_normal_text_alone() -> None:
    """SMuFL文字を含まない歌詞・コード文字はフォントを変えない(日本語フォントが必要なため)。"""
    svg = '<tspan font-size="405px">こんにちは</tspan>'
    assert score._substitute_missing_font(svg) == svg


def test_svg_to_png_produces_valid_png() -> None:
    svg = score.render_horizontal_svg(_MUSICXML)
    png = score.svg_to_png(svg)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(png) > 1000


def test_find_musescore_prefers_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UTAVIDEO_MUSESCORE", "/path/to/mscore")
    assert score.find_musescore() == "/path/to/mscore"


def test_require_musescore_raises_when_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(score, "find_musescore", lambda: None)
    with pytest.raises(score.ScoreError):
        score.require_musescore()


def test_to_musicxml_raises_when_musescore_missing(tmp_path: Path) -> None:
    with pytest.raises(score.ScoreError):
        score.to_musicxml(tmp_path / "no-such-file.mscz", "/no/such/musescore")


@pytest.mark.skipif(score.find_musescore() is None, reason="MuseScore 4 が必要")
def test_to_musicxml_round_trips_without_modifying_input(tmp_path: Path) -> None:
    """MuseScore CLIでMusicXML→.msczと作ってから読み直し、内容が読めて元ファイルも壊れないことを確かめる。"""
    musescore = score.require_musescore()
    source_path = tmp_path / "source.musicxml"
    source_path.write_text(_MUSICXML, encoding="utf-8")
    mscz_path = tmp_path / "score.mscz"
    subprocess.run([musescore, "-o", str(mscz_path), str(source_path)], check=True, capture_output=True)
    digest_before = hashlib.sha256(mscz_path.read_bytes()).digest()

    xml = score.to_musicxml(mscz_path, musescore)

    assert "major-seventh" in xml
    assert hashlib.sha256(mscz_path.read_bytes()).digest() == digest_before
