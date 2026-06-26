from __future__ import annotations

import asyncio

from .registry import ToolContext, ToolRegistry

MAX_OUTPUT = 30000


async def _run_shell(args: dict, ctx: ToolContext) -> str:
    command = args.get("command", "").strip()
    if not command:
        return "Error: 'command' is required"
    timeout = float(args.get("timeout", 120))
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=ctx.cwd,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return f"Error: command timed out after {timeout}s"
    out = stdout.decode("utf-8", "replace")
    if len(out) > MAX_OUTPUT:
        out = out[:MAX_OUTPUT] + f"\n... (truncated, {len(out)} bytes total)"
    return f"exit={proc.returncode}\n{out}" if out else f"exit={proc.returncode}"


def register(registry: ToolRegistry) -> None:
    registry.add(
        name="run_shell",
        description=(
            "Execute a shell command and return its combined stdout/stderr and exit "
            "code. Runs in the harness working directory."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"},
                "timeout": {
                    "type": "number",
                    "description": "Timeout in seconds (default 120)",
                },
            },
            "required": ["command"],
        },
        handler=_run_shell,
    )
