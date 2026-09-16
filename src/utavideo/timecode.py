"""設定に書く時刻（"M:SS(.fff)" の文字列、または秒の数）。"""

import math
import re

# \d は全角数字にも一致するので、[0-9] で ASCII の数字だけにする
_PATTERN = re.compile(r"([0-9]+):([0-5][0-9])(?:\.([0-9]{1,3}))?")
FORMAT_HINT = '"M:SS" か "M:SS.fff"（例: "1:23.5"）、または秒の数（例: 83.5）で書いてください'


def parse_time(value: object) -> float:
    """時刻の文字列（例: "1:23.5"）か秒の数（例: 83.5）を秒にする。

    書式が違う、または負の値なら ValueError。
    """
    # TOML の true / false は int の仲間として通ってしまう
    if isinstance(value, bool):
        raise ValueError(FORMAT_HINT)
    if isinstance(value, int | float):
        # TOML は inf と nan を書ける
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"0 以上の有限の秒数にしてください: {value}")
        return float(value)
    if isinstance(value, str) and (m := _PATTERN.fullmatch(value)):
        minutes, seconds, fraction = m.groups()
        ms = (int(minutes) * 60 + int(seconds)) * 1000 + int((fraction or "0").ljust(3, "0"))
        return ms / 1000
    raise ValueError(FORMAT_HINT)


def format_time(seconds: float) -> str:
    """メッセージに出す形。例: 83.5 → "1:23.500"。"""
    ms = round(seconds * 1000)
    return f"{ms // 60_000}:{ms % 60_000 // 1000:02d}.{ms % 1000:03d}"
