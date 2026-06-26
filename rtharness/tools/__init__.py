from __future__ import annotations

from ..config import Config
from .registry import Tool, ToolContext, ToolRegistry


def build_registry(config: Config, cwd: str | None = None) -> ToolRegistry:
    ctx = ToolContext(config=config, cwd=cwd or ".")
    registry = ToolRegistry(ctx)

    from . import files, shell

    shell.register(registry)
    files.register(registry)

    for module_name in ("parseltongue", "l1b3rt4s", "target", "http_tool"):
        try:
            module = __import__(f"{__name__}.{module_name}", fromlist=["register"])
        except ImportError:
            continue
        module.register(registry)
    return registry


__all__ = ["Tool", "ToolContext", "ToolRegistry", "build_registry"]
