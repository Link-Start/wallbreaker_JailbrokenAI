from __future__ import annotations

from pathlib import Path

from .registry import ToolContext, ToolRegistry

MAX_READ = 200000


def _resolve(ctx: ToolContext, path: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = Path(ctx.cwd) / p
    return p


async def _read_file(args: dict, ctx: ToolContext) -> str:
    path = args.get("path", "")
    if not path:
        return "Error: 'path' is required"
    p = _resolve(ctx, path)
    if not p.is_file():
        return f"Error: no such file: {p}"
    data = p.read_text(encoding="utf-8", errors="replace")
    if len(data) > MAX_READ:
        return data[:MAX_READ] + f"\n... (truncated, {len(data)} chars total)"
    return data


async def _write_file(args: dict, ctx: ToolContext) -> str:
    path = args.get("path", "")
    if not path:
        return "Error: 'path' is required"
    content = args.get("content", "")
    p = _resolve(ctx, path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} chars to {p}"


async def _edit_file(args: dict, ctx: ToolContext) -> str:
    path = args.get("path", "")
    old = args.get("old", "")
    new = args.get("new", "")
    if not path or old == "":
        return "Error: 'path' and 'old' are required"
    p = _resolve(ctx, path)
    if not p.is_file():
        return f"Error: no such file: {p}"
    data = p.read_text(encoding="utf-8")
    count = data.count(old)
    if count == 0:
        return "Error: 'old' string not found"
    if count > 1:
        return f"Error: 'old' string is not unique ({count} matches)"
    p.write_text(data.replace(old, new, 1), encoding="utf-8")
    return f"Edited {p}"


def register(registry: ToolRegistry) -> None:
    registry.add(
        name="read_file",
        description="Read a UTF-8 text file and return its contents.",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        handler=_read_file,
    )
    registry.add(
        name="write_file",
        description="Write content to a file, creating parent directories.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        handler=_write_file,
    )
    registry.add(
        name="edit_file",
        description="Replace a unique occurrence of 'old' with 'new' in a file.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old": {"type": "string"},
                "new": {"type": "string"},
            },
            "required": ["path", "old", "new"],
        },
        handler=_edit_file,
    )
