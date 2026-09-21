"""コマンドの出力に使う Rich の Console。

cli.py・analyze.py・render.py のどこからも使えるよう、ここにまとめる
（cli.py に置くと、analyze.py・render.py が cli.py に依存する形になり、
cli.py が analyze.py・render.py に依存する設計と循環してしまうため）。
"""

from rich.console import Console

console = Console(highlight=False)
err_console = Console(stderr=True, highlight=False)
