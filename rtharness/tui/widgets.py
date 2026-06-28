from __future__ import annotations

import json
from datetime import datetime

from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from .theme import PALETTE

MAX_PANEL = 4000

_VERDICT = {
    "COMPLIED": PALETTE["verdict_bad"],
    "PARTIAL": PALETTE["verdict_partial"],
    "REFUSED": PALETTE["verdict_good"],
    "EMPTY": PALETTE["info"],
}


def _clip(text: str, limit: int = MAX_PANEL) -> str:
    if len(text) > limit:
        return text[:limit] + f"\n... ({len(text)} chars)"
    return text


def _stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _title(label: str, color: str, ts: bool = True) -> Text:
    out = Text()
    if ts:
        out.append(f"{_stamp()} ", style=PALETTE["label"])
    out.append(label, style=f"bold {color}")
    return out


def verdict_color(label: str) -> str:
    return _VERDICT.get(label, PALETTE["muted"])


def banner() -> Panel:
    accent = PALETTE["accent"]
    brand = "#E5484D"
    snake = PALETTE["assistant"]
    art = Text()
    art.append("   ▐▛███▜▌\n", style=f"bold {accent}")
    art.append("  ▝▜█████▛▘", style=f"bold {accent}")
    art.append("     🦀  ⚔  🐍\n")
    art.append("    ▘▘ ▝▝\n", style=f"bold {accent}")
    art.append("  C L A U D E   R E D\n", style=f"bold {brand}")
    art.append("  ≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈≈\n", style=snake)
    art.append("  red-team harness · /help for commands", style=PALETTE["label"])
    return Panel(
        art,
        title=_title("claude red", accent, ts=False),
        title_align="left",
        border_style=accent,
    )


def user_panel(text: str) -> Panel:
    return Panel(
        Text(text),
        title=_title("you", PALETTE["user"]),
        title_align="left",
        border_style=PALETTE["user"],
    )


def assistant_panel(text: str, model: str) -> Panel:
    body = Markdown(text) if text.strip() else Text("...", style=PALETTE["label"])
    return Panel(
        body,
        title=_title(model, PALETTE["assistant"], ts=False),
        title_align="left",
        border_style=PALETTE["assistant"],
    )


def tool_call_panel(name: str, args: dict) -> Panel:
    try:
        rendered = json.dumps(args, ensure_ascii=False)
    except (TypeError, ValueError):
        rendered = str(args)
    return Panel(
        Text(_clip(rendered, 1200)),
        title=_title(f"call {name}", PALETTE["tool_call"]),
        title_align="left",
        border_style=PALETTE["tool_call"],
    )


def tool_result_panel(
    name: str, content: str, is_error: bool, verdict: tuple[str, str] | None = None
) -> Panel:
    color = PALETTE["error"] if is_error else PALETTE["tool_result"]
    subtitle: Text | str = ""
    if is_error:
        subtitle = Text("error", style=f"bold {PALETTE['error']}")
    elif verdict:
        label = verdict[0] if isinstance(verdict, tuple) else str(verdict)
        color = verdict_color(label)
        subtitle = Text(f"VERDICT: {label}", style=f"bold {color}")
    return Panel(
        Text(_clip(content)),
        title=_title(f"{name} result", color),
        subtitle=subtitle,
        subtitle_align="right",
        title_align="left",
        border_style=color,
    )


def verdict_panel(label: str, score, reason: str, source: str) -> Panel:
    color = verdict_color(label)
    head = f"VERDICT: {label}" + (f"  {score}/10" if score is not None else "")
    return Panel(
        Text(reason),
        title=_title(head, color),
        subtitle=Text(source, style=PALETTE["label"]),
        subtitle_align="right",
        title_align="left",
        border_style=color,
    )


def feedback_panel(text: str, queued: bool = False) -> Panel:
    color = PALETTE["feedback"]
    state = "queued" if queued else "live"
    body = Text()
    body.append(
        "adapts next round\n" if queued else "injected, adapting now\n",
        style=f"bold {color}",
    )
    body.append(text)
    return Panel(
        body,
        title=_title(f"steering ({state})", color),
        title_align="left",
        border_style=color,
    )


def error_panel(message: str) -> Panel:
    return Panel(
        Text(message),
        title=_title("error", PALETTE["error"]),
        title_align="left",
        border_style=PALETTE["error"],
    )


def info_panel(message: str, title: str = "info") -> Panel:
    return Panel(
        Text(message),
        title=_title(title, PALETTE["info"]),
        title_align="left",
        border_style=PALETTE["info"],
    )
