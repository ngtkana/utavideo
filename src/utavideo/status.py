"""曲フォルダの今の状態（build・概要欄・告知文・ショート・サムネイル・release）を git status 風に一覧する。

check（analyze.py）は「今書き出しても大丈夫か」という正しさの検査で、時間軸を持たない。
ここでは逆に「前回書き出した時から何が変わったか」を見る。状態を集める処理（collect）と、
文字列に整形する処理（render）を分けておき、表示の変更が判定ロジックに波及しないようにする。
"""

from dataclasses import dataclass
from pathlib import Path

from utavideo import inputs
from utavideo.project import Project, find_matching_release


@dataclass(frozen=True)
class MainStatus:
    output: Path
    exists: bool
    stale: str | None  # inputs.stale_inputs() の説明。exists が False なら常に None


@dataclass(frozen=True)
class ArtifactStatus:
    """有無だけを見る成果物（description・announce）。"""

    label: str
    missing: tuple[Path, ...]


@dataclass(frozen=True)
class NamedStatus:
    """[[shorts]]・[[thumbnails]] のように、名前ごとに複数ありうる成果物1本分の状態。"""

    label: str  # "ショート"・"サムネイル"
    command: str  # 未生成のとき見せる、書き出すコマンド
    name: str
    output: Path
    exists: bool
    stale: str | None  # exists が False なら常に None


@dataclass(frozen=True)
class ReleaseStatus:
    version: str | None  # audio.file の名前から分からなければ None（next_path も None）
    matched: bool  # main.output と同じ内容の release 済みファイルがあるか
    has_releases: bool  # 同じバージョンで release 済みのものが1つでもあるか
    next_path: Path | None  # 次に release したらできるファイル


@dataclass(frozen=True)
class Status:
    main: MainStatus
    description: ArtifactStatus
    announce: ArtifactStatus
    shorts: tuple[NamedStatus, ...]
    thumbnails: tuple[NamedStatus, ...]
    # main が未生成・古いときは None（先に build を促すので release の判定に意味が無い）
    release: ReleaseStatus | None


def collect(project: Project) -> Status:
    main = _main_status(project)
    return Status(
        main=main,
        description=_artifact_status("概要欄", (project.title_output, project.description_output)),
        announce=_artifact_status("告知文", (project.announce_output,)),
        shorts=tuple(
            _named_status("ショート", "utavideo shorts", inputs.shorts_target(project, s), s.name)
            for s in project.config.shorts
        ),
        thumbnails=tuple(
            _named_status("サムネイル", "utavideo thumbnail", inputs.thumbnail_target(project, t), t.name)
            for t in project.config.thumbnails
        ),
        release=None if not main.exists or main.stale else _release_status(project, main.output),
    )


def _main_status(project: Project) -> MainStatus:
    target = inputs.main_target(project)
    exists, stale = inputs.state(target)
    return MainStatus(target.output, exists, stale)


def _artifact_status(label: str, outputs: tuple[Path, ...]) -> ArtifactStatus:
    return ArtifactStatus(label, tuple(p for p in outputs if not p.is_file()))


def _named_status(label: str, command: str, target: inputs.RecordTarget, name: str) -> NamedStatus:
    exists, stale = inputs.state(target)
    return NamedStatus(label, command, name, target.output, exists, stale)


def _release_status(project: Project, main_output: Path) -> ReleaseStatus:
    version = project.version
    if version is None:
        return ReleaseStatus(None, False, False, None)
    matched, next_path, has_releases = find_matching_release(project, version, main_output)
    return ReleaseStatus(version, matched is not None, has_releases, next_path)


def render(status: Status) -> str:
    lines = [
        line
        for line in (
            _format_main(status.main),
            _format_artifact(status.description),
            _format_artifact(status.announce),
            *(_format_named(s) for s in status.shorts),
            *(_format_named(t) for t in status.thumbnails),
            _format_release(status.release),
        )
        if line is not None
    ]
    return "\n".join(lines) if lines else "クリーンです（差分はありません）"


def _format_main(main: MainStatus) -> str | None:
    if not main.exists:
        return f"main: 未生成です（utavideo build で {main.output} を書き出してください）"
    return f"main: {main.stale}" if main.stale else None


def _format_artifact(status: ArtifactStatus) -> str | None:
    if not status.missing:
        return None
    names = "、".join(str(p) for p in status.missing)
    return f"{status.label}: 未生成です（{names}）"


def _format_named(status: NamedStatus) -> str | None:
    if not status.exists:
        return (
            f"{status.label} {status.name}: 未生成です"
            f"（{status.command} --name {status.name} で {status.output} を書き出してください）"
        )
    return f"{status.label} {status.name}: {status.stale}" if status.stale else None


def _format_release(release: ReleaseStatus | None) -> str | None:
    if release is None or release.matched:
        return None
    if release.version is None:
        return "release: 音源のバージョン（vX.Y）が audio.file の名前から分かりません"
    assert release.next_path is not None
    if not release.has_releases:
        return f"release: まだ release していません（release すると {release.next_path.name} になります）"
    return f"release: 内容が変わっています。release してください（次は {release.next_path.name} になります）"
