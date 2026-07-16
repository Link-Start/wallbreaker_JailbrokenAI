from __future__ import annotations

from rich.table import Table
from rich.text import Text

from textual.widgets import Static

from .theme import PALETTE
from .widgets import verdict_color, verdict_display


def _verdict_text(label) -> Text:
    if not label:
        return Text("-", style=PALETTE["label"])
    word, glyph = verdict_display(label)
    return Text(f"{glyph} {word}", style=f"bold {verdict_color(label)}")


class StatsPanel(Static):
    def on_mount(self) -> None:
        self.stats: dict = {}

    def set_stats(self, **kw) -> None:
        self.stats = {**getattr(self, "stats", {}), **kw}
        self.refresh()

    def render(self) -> Table:
        s = getattr(self, "stats", {})
        g = Table.grid(padding=(0, 1))
        g.add_column(justify="right", style=PALETTE["label"], no_wrap=True)
        g.add_column(overflow="ellipsis")
        rule = Text("▄▀" * 14, style=PALETTE["secondary"])
        g.add_row(Text("☠ W4LLBR34K3R", style=f"bold {PALETTE['brand']}"), "")
        g.add_row(rule, "")
        g.add_row(Text("K1LL-C0UNT", style=f"bold {PALETTE['secondary']}"), "")
        g.add_row("PWNZ", Text(s.get("asr", "0/0"), style=f"bold {PALETTE['assistant']}"))
        g.add_row("L4ST", _verdict_text(s.get("last")))
        g.add_row(rule, "")
        g.add_row(Text("TEH R41D", style=f"bold {PALETTE['secondary']}"), "")
        g.add_row("V1CT1M", Text(s.get("target", "n0n3"), style=f"bold {PALETTE['accent']}"))
        g.add_row("CR3W", Text(s.get("profile", ""), style=PALETTE["user"]))
        g.add_row("W3P0N", Text(s.get("model", "")))
        g.add_row("M0D3", Text(s.get("mode", "")))
        g.add_row("R3F", Text(s.get("judge", "")))
        g.add_row("T0K3NZ", Text(s.get("tokens", ""), style=PALETTE["label"]))
        return g
