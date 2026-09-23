"""曲フォルダで今作れるものをまとめて作る（build・description・announce・thumbnail）。

status.py と同じく、状態を集める処理（collect）と文字列に整形する処理（render）を分ける。
判定ロジックは analyze.py の検査関数を再利用する。実際に書き出す処理（apply）は、ffmpeg を
呼ぶ処理が集まっている cli.py 側に任せ、ここでは持たない。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from utavideo import announce, description, inputs
from utavideo.analyze import FontSearch, analyze, analyze_thumbnails, background_issues
from utavideo.config import load_user_config
from utavideo.project import Project
from utavideo.subs import Issue

State = Literal["run", "skip", "issues"]


@dataclass(frozen=True)
class TargetStatus:
    name: str  # "build" / "description" / "announce" / "thumbnail:<name>"
    state: State
    issues: tuple[str, ...] = ()  # state == "issues" のときのエラーメッセージ
    outputs: tuple[Path, ...] = ()  # state == "run" / "skip" のときの出力先


@dataclass(frozen=True)
class Plan:
    # 対象外（[[thumbnails]] が空など、この曲では使わない機能）は含まない
    targets: tuple[TargetStatus, ...]


def collect(project: Project, search: FontSearch) -> Plan:
    targets = [_build_status(project, search), _description_status(project), _announce_status(project)]
    targets += _thumbnail_statuses(project, search)
    return Plan(tuple(targets))


def _errors(issues: list[Issue]) -> tuple[str, ...]:
    return tuple(issue.message for issue in issues if issue.level == "error")


def _build_status(project: Project, search: FontSearch) -> TargetStatus:
    errors = _errors(analyze(project, "final", search).issues)
    output = project.main_output
    if errors:
        return TargetStatus("build", "issues", errors)
    exists, stale = inputs.state(inputs.main_target(project))
    if exists and stale is None:
        return TargetStatus("build", "skip", outputs=(output,))
    return TargetStatus("build", "run", outputs=(output,))


def _description_status(project: Project) -> TargetStatus:
    # 生成コストが低く ffmpeg も使わないので、済み判定はせず、要対応でなければ常に実行し直す
    fmt = load_user_config().description
    issues = description.lint(project, fmt) if project.config.description is not None else []
    if errors := _errors(issues):
        return TargetStatus("description", "issues", errors)
    return TargetStatus("description", "run", outputs=(project.title_output, project.description_output))


def _announce_status(project: Project) -> TargetStatus:
    # description と同じ理由で済み判定はしない。[[uploads]] が無いことは、既存の announce
    # コマンドと同じく警告どまりとし、下書きとして書き出す（要対応にはしない）
    user_config = load_user_config()
    issues = announce.lint(
        project.config, user_config.announce, user_config.description, warn_no_uploads=False
    )
    if errors := _errors(issues):
        return TargetStatus("announce", "issues", errors)
    return TargetStatus("announce", "run", outputs=(project.announce_output,))


def _thumbnail_statuses(project: Project, search: FontSearch) -> list[TargetStatus]:
    thumbnails = project.config.thumbnails
    if not thumbnails:  # 対象外。何も返さない
        return []
    # 背景のファイル自体の問題は、どのサムネイルにも共通してのしかかる
    background_errors = _errors(background_issues(project))
    statuses = []
    for thumb in thumbnails:
        name = f"thumbnail:{thumb.name}"
        own_errors = _errors(analyze_thumbnails(project, (thumb,), bg_only=False, search=search).issues)
        errors = background_errors + own_errors
        thumb_target = inputs.thumbnail_target(project, thumb)
        output = thumb_target.output
        if errors:
            statuses.append(TargetStatus(name, "issues", errors))
        else:
            exists, stale = inputs.state(thumb_target)
            target_state = "skip" if exists and stale is None else "run"
            statuses.append(TargetStatus(name, target_state, outputs=(output,)))
    return statuses


def render(plan: Plan) -> str:
    sections = [
        _section("実行しました", [t for t in plan.targets if t.state == "run"]),
        _section("スキップ（済み）", [t for t in plan.targets if t.state == "skip"]),
        _section("要対応", [t for t in plan.targets if t.state == "issues"], show_issues=True),
    ]
    blocks = [block for block in sections if block is not None]
    return "\n\n".join(blocks) if blocks else "クリーンです（作るものはありません）"


def _section(heading: str, targets: list[TargetStatus], *, show_issues: bool = False) -> str | None:
    if not targets:
        return None
    lines = [f"{heading}:"]
    for target in targets:
        if show_issues:
            lines += [f"  {target.name}: {message}" for message in target.issues]
        else:
            paths = ", ".join(str(path) for path in target.outputs)
            lines.append(f"  {target.name}: {paths}")
    return "\n".join(lines)
