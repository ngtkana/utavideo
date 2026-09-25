"""build/main.mp4・shorts・thumbnail・inst を書き出したときの入力の記録と、release・status のときの比較。

release が止まるのは、確かめた動画と描画に効く入力が違うときだけにしたい。
更新時刻では、概要欄を書き足しただけ・保存し直しただけでも止まってしまうので、中身で比べる。

音声・背景ファイルは数十〜数百MBになりうるので、毎回 SHA256 で全体を読み直すと status のように
頻繁に呼ぶ用途では重い。size・mtime_ns が記録と一致すれば読まずに済ませ、違うときだけ実際に読んで
確かめる（racy git の要領。issue #78）。

shorts・thumbnail・inst はフォント依存を見ない。歌詞を合成しないと使うフォントが決まらないため、正確に
見るには合成をやり直す必要があるが、それでは status のように頻繁に呼ぶ用途に重すぎる。歌詞・config
ファイル自体の変化だけを見る簡略版にする（issue #79・#80）。
"""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from utavideo import avatar, inst, shorts, thumbnail, vertical
from utavideo.config import PROJECT_CONFIG_NAME, Avatar, Layer, Short, Thumbnail, rendered_values
from utavideo.ffmpeg import write_text
from utavideo.layers import file_path as layer_file_path
from utavideo.project import Project

_FORMAT = 2
FONTS = "フォント"


def _layer_files(root: Path, layers: tuple[Layer, ...]) -> tuple[tuple[str, Path], ...]:
    """[[layers]] の各ファイルを、files タプルに足す分の (名前, パス) にする。"""
    return tuple((f"layers.{layer.name}", layer_file_path(root, layer)) for layer in layers)


def _avatar_files(root: Path, config_avatar: Avatar | None) -> tuple[tuple[str, Path], ...]:
    """[avatar] の生の録画を、files タプルに足す分の (名前, パス) にする（無ければ空）。

    キー抜き・頭出し済みの中間動画（build/.work/）はここでは追わない。生の録画・
    utavideo.toml の値（config ハッシュに含まれる）が変わらない限り作り直さないため。
    """
    if config_avatar is None:
        return ()
    return (("avatar.file", avatar.file_path(root, config_avatar)),)


@dataclass(frozen=True)
class RecordTarget:
    """記録・比較する成果物1本分の宛先。main の他、shorts:<name>・thumbnail:<name> にも使う。"""

    output: Path
    record_path: Path
    files: tuple[tuple[str, Path], ...]
    config: object  # rendered_values() 済みの、この成果物に効く設定値
    label: str  # stale_inputs のメッセージに使う、この成果物の呼び名
    track_fonts: bool = True  # False なら使ったフォントの変化を追わない（shorts・thumbnail の簡略化）


@dataclass(frozen=True)
class Record:
    """write_video・_write_thumbnail が書き出し前後に使う、記録の宛先と中身。"""

    target: RecordTarget
    values: dict[str, Any]


def main_target(project: Project) -> RecordTarget:
    return RecordTarget(
        project.main_output,
        project.inputs_record,
        (
            (PROJECT_CONFIG_NAME, project.config_path),
            ("audio.file", project.audio_path),
            ("video.background", project.background_path),
            ("lyrics.file", project.lyrics_path),
            *_layer_files(project.root, project.config.layers),
            *_avatar_files(project.root, project.config.avatar),
        ),
        rendered_values(project.config),
        "build/main.mp4",
    )


def shorts_target(project: Project, short: Short) -> RecordTarget:
    config = project.config
    output = shorts.output_path(project.build_dir, short)
    return RecordTarget(
        output,
        project.shorts_inputs_record(short.name),
        (
            (PROJECT_CONFIG_NAME, project.config_path),
            ("vertical.lyrics", vertical.lyrics_path(project.root, config.vertical)),
            ("lyrics.file", project.lyrics_path),
            ("audio.file", project.audio_path),
            ("video.background", project.background_path),
            *_layer_files(project.root, config.layers),
            *_avatar_files(project.root, config.avatar),
        ),
        {
            "video": rendered_values(config.video),
            "vertical": rendered_values(config.vertical),
            "overlay_text": rendered_values(config.overlay_text),
            "song": rendered_values(config.song),
            "short": rendered_values(short),
            "layers": rendered_values(config.layers),
            "avatar": rendered_values(config.avatar),
        },
        str(output),
        track_fonts=False,
    )


def thumbnail_target(project: Project, thumb: Thumbnail) -> RecordTarget:
    config = project.config
    output = thumbnail.output_path(project.build_dir, thumb)
    return RecordTarget(
        output,
        project.thumbnail_inputs_record(thumb.name),
        (
            (PROJECT_CONFIG_NAME, project.config_path),
            ("video.background", project.background_path),
            ("thumbnail.file", thumbnail.file_path(project.root, thumb)),
            *_layer_files(project.root, config.layers),
            *_avatar_files(project.root, config.avatar),
        ),
        {
            "video": rendered_values(config.video),
            "thumbnail": rendered_values(thumb),
            "layers": rendered_values(config.layers),
            "avatar": rendered_values(config.avatar),
        },
        str(output),
        track_fonts=False,
    )


def inst_target(project: Project, key: int) -> RecordTarget:
    """inst は --keys で任意のキーを指定でき、事前宣言された個数を持たないので、キーごとに作る。

    inst.audio が未設定のとき（analyze_inst がエラーにして書き出しまで進まない）は、追う音源が無いので
    files に含めない。
    """
    config = project.config
    output = inst.output_path(project.build_dir, project.slug, key)
    audio_file = (("inst.audio", project.inst_audio_path),) if config.inst.audio is not None else ()
    return RecordTarget(
        output,
        project.inst_inputs_record(inst.key_label(key)),
        (
            (PROJECT_CONFIG_NAME, project.config_path),
            *audio_file,
            ("video.background", project.background_path),
            ("lyrics.file", project.lyrics_path),
        ),
        {
            "video": rendered_values(config.video),
            "lyrics": rendered_values(config.lyrics),
            "overlay_text": rendered_values(config.overlay_text),
            "song": rendered_values(config.song),
            "inst": rendered_values(config.inst),
        },
        str(output),
        track_fonts=False,
    )


def snapshot(target: RecordTarget) -> dict[str, Any]:
    """描画に効く入力のうち、フォント以外の要約。値は JSON にできる形で、記録を読み戻したものと比べられる。

    書き出しでは、utavideo や ffmpeg が素材を読むより前に呼ぶ。読むまでの間に変わっても、記録が古い側に
    なって release が止まる。
    """
    values: dict[str, Any] = {PROJECT_CONFIG_NAME: _config_hash(target.config)}
    values |= {name: _file_record(path) for name, path in target.files if name != PROJECT_CONFIG_NAME}
    return values


def _config_hash(config: object) -> str:
    # utavideo.toml は書き方ではなく、読み込んだ値のうち描画に効くもので比べる
    text = json.dumps(config, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()


def _file_record(path: Path) -> dict[str, Any]:
    """ファイルの要約。size・mtime_ns（読まずに済む）と sha256（中身で確かめる）を持つ。"""
    size, mtime_ns = _stamp(path)
    return {"size": size, "mtime_ns": mtime_ns, "sha256": _file_digest(path)}


def _font_values(font_files: Iterable[Path]) -> list[list[Any]]:
    unique = sorted({path.absolute() for path in font_files})
    return [[str(path), *_stamp(path)] for path in unique]


def with_fonts(values: dict[str, Any], font_files: Iterable[Path]) -> dict[str, Any]:
    """snapshot に、使うフォントの要約を足したもの。使うフォントは歌詞を読んだ後にしか分からない。"""
    # 中身を読むと重いので、パス・大きさ・更新時刻で代える（issue #26）
    return {**values, FONTS: _font_values(font_files)}


def record_text(target: RecordTarget, values: dict[str, Any]) -> str:
    """書き出し終えた成果物と、その入力の記録。"""
    data = {"format": _FORMAT, "video": _stamp(target.output), "inputs": values}
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def unlink_stale_record(record: Record | None) -> None:
    """書き出す前に呼ぶ。書き出しが途中で終わったとき、前の記録が新しい成果物のものに見えないよう先に消す。"""
    if record is not None:
        record.target.record_path.unlink(missing_ok=True)


def save_record(record: Record | None, font_files: tuple[Path, ...] = ()) -> None:
    """書き出し終えた後に呼ぶ。target.track_fonts が真なら font_files の要約を足して保存する。"""
    if record is None:
        return
    values = with_fonts(record.values, font_files) if record.target.track_fonts else record.values
    write_text(record.target.record_path, record_text(record.target, values))


def state(target: RecordTarget) -> tuple[bool, str | None]:
    """(出力があるか, stale_inputs の説明) の組。出力が無ければ stale は常に None。"""
    if not target.output.is_file():
        return False, None
    return True, stale_inputs(target)


def stale_inputs(target: RecordTarget) -> str | None:
    """書き出した後に変わった入力の説明。変わっていなければ None。"""
    recorded = _read_record(target)
    if recorded is None:
        # 記録の無い書き出し（記録を始める前のものなど）は、更新時刻で比べる
        if not target.output.is_file():
            return None
        built_at = target.output.stat().st_mtime
        newer = [name for name, path in target.files if path.is_file() and path.stat().st_mtime > built_at]
        return f"{target.label} より新しい入力があります（{', '.join(newer)}）" if newer else None
    changed = _changed_inputs(target, recorded)
    return (
        f"{target.label} を書き出した後に変わった入力があります（{', '.join(changed)}）" if changed else None
    )


def _changed_inputs(target: RecordTarget, recorded: dict[str, Any]) -> list[str]:
    """記録と比べて変わった入力の名前。ファイルは size・mtime_ns が一致すれば読まずに済ませる。"""
    changed = (
        [] if recorded.get(PROJECT_CONFIG_NAME) == _config_hash(target.config) else [PROJECT_CONFIG_NAME]
    )
    changed += [
        name
        for name, path in target.files
        if name != PROJECT_CONFIG_NAME and not _file_matches(path, recorded.get(name))
    ]
    if target.track_fonts:
        fonts = [Path(entry[0]) for entry in recorded.get(FONTS, [])]
        if _font_values(fonts) != recorded.get(FONTS):
            changed.append(FONTS)
    return changed


def _file_matches(path: Path, record: Any) -> bool:
    """記録と実際のファイルを比べる。size・mtime_ns が一致すれば読まずに済ませ、違えば中身で確かめる。"""
    if not isinstance(record, dict):
        return False
    if _stamp(path) == [record.get("size"), record.get("mtime_ns")]:
        return True
    return record.get("sha256") == _file_digest(path)


def _read_record(target: RecordTarget) -> dict[str, Any] | None:
    """使える記録の inputs。無い・読めない・別の成果物のものなら None。"""
    try:
        data = json.loads(target.record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("format") != _FORMAT:
        return None
    # 成果物を別の手段で差し替えていたら、記録はそのものではない
    if data.get("video") != _stamp(target.output):
        return None
    inputs = data.get("inputs")
    return inputs if isinstance(inputs, dict) else None


_digest_cache: dict[Path, tuple[list[int | None], str | None]] = {}


def _file_digest(path: Path) -> str | None:
    """path の sha256。status は main・shorts・thumbnail で同じ音声・背景ファイルを何度も見るので、
    stamp（size・mtime_ns）が変わっていない間はプロセス内で使い回し、読み直さない。"""
    stamp = _stamp(path)
    cached = _digest_cache.get(path)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    digest = _read_file_digest(path)
    _digest_cache[path] = (stamp, digest)
    return digest


def _read_file_digest(path: Path) -> str | None:
    try:
        with path.open("rb") as f:
            return hashlib.file_digest(f, "sha256").hexdigest()
    except OSError:
        return None


def _stamp(path: Path) -> list[int | None]:
    """大きさと更新時刻。ファイルが無ければ None の組。"""
    try:
        stat = path.stat()
    except OSError:
        return [None, None]
    return [stat.st_size, stat.st_mtime_ns]
