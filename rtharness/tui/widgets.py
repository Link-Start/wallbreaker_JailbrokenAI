from __future__ import annotations

import json

from rich.panel import Panel
from rich.text import Text

MAX_PANEL = 4000


def _clip(text: str, limit: int = MAX_PANEL) -> str:
    if len(text) > limit:
        return text[:limit] + f"\n... ({len(text)} chars)"
    return text


def user_panel(text: str) -> Panel:
    return Panel(Text(text), title="you", title_align="left", border_style="cyan")


def assistant_panel(text: str, model: str) -> Panel:
    return Panel(
        Text(text or "..."),
        title=model,
        title_align="left",
        border_style="green",
    )


def tool_call_panel(name: str, args: dict) -> Panel:
    try:
        rendered = json.dumps(args, ensure_ascii=False)
    except (TypeError, ValueError):
        rendered = str(args)
    return Panel(
        Text(_clip(rendered, 1200)),
        title=f"call {name}",
        title_align="left",
        border_style="yellow",
    )


def tool_result_panel(name: str, content: str, is_error: bool) -> Panel:
    return Panel(
        Text(_clip(content)),
        title=f"{name} result",
        subtitle="error" if is_error else "",
        title_align="left",
        border_style="red" if is_error else "magenta",
    )


def error_panel(message: str) -> Panel:
    return Panel(Text(message), title="error", border_style="red")


def info_panel(message: str, title: str = "info") -> Panel:
    return Panel(Text(message), title=title, title_align="left", border_style="blue")
