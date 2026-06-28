from __future__ import annotations

import asyncio
import os
import signal

from .registry import ToolContext, ToolRegistry

MAX_OUTPUT = 30000
DEFAULT_TIMEOUT = 30.0
MAX_TIMEOUT = 600.0


def _clamp_timeout(value) -> float:
    try:
        t = float(value)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT
    if t <= 0:
        return DEFAULT_TIMEOUT
    return min(t, MAX_TIMEOUT)


def _kill_tree(proc) -> None:
    """Kill the whole process group so children (find, pipe stages) die with the shell.

    asyncio.create_subprocess_shell runs '/bin/sh -c ...'; proc.kill() only signals that
    shell, leaving a runaway child (e.g. 'find /') orphaned. With start_new_session=True
    the shell leads its own process group, so killpg takes the whole tree down.
    """
    if proc.returncode is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError, AttributeError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass


async def _run_shell(args: dict, ctx: ToolContext) -> str:
    command = args.get("command", "").strip()
    if not command:
        return "Error: 'command' is required"
    timeout = _clamp_timeout(args.get("timeout", DEFAULT_TIMEOUT))
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=ctx.cwd,
        start_new_session=True,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        _kill_tree(proc)
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass
        return (
            f"Error: command timed out after {timeout:g}s and was killed. "
            "Narrow it (scope `find` to a directory, not /) or pass a larger 'timeout'."
        )
    out = stdout.decode("utf-8", "replace")
    if len(out) > MAX_OUTPUT:
        out = out[:MAX_OUTPUT] + f"\n... (truncated, {len(out)} bytes total)"
    return f"exit={proc.returncode}\n{out}" if out else f"exit={proc.returncode}"


def register(registry: ToolRegistry) -> None:
    registry.add(
        name="run_shell",
        description=(
            "Execute a shell command and return its combined stdout/stderr and exit "
            "code. Runs in the harness working directory. Times out after 30s by default "
            "(max 600) and kills the whole process tree on timeout - scope filesystem "
            "searches (don't run `find /`); pass 'timeout' for a known-slow command."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"},
                "timeout": {
                    "type": "number",
                    "description": "Timeout in seconds (default 30, max 600); the process tree is killed when it elapses",
                },
            },
            "required": ["command"],
        },
        handler=_run_shell,
    )
