import asyncio
import time

from rtharness.config import Config
from rtharness.tools import shell
from rtharness.tools.registry import ToolContext, ToolRegistry
from rtharness.tools.shell import _clamp_timeout, DEFAULT_TIMEOUT, MAX_TIMEOUT


def _reg(tmp_path):
    reg = ToolRegistry(ToolContext(config=Config(default_profile="x", profiles={}), cwd=str(tmp_path)))
    shell.register(reg)
    return reg


def test_clamp_timeout():
    assert _clamp_timeout(5) == 5.0
    assert _clamp_timeout(0) == DEFAULT_TIMEOUT
    assert _clamp_timeout(-3) == DEFAULT_TIMEOUT
    assert _clamp_timeout("nope") == DEFAULT_TIMEOUT
    assert _clamp_timeout(10_000) == MAX_TIMEOUT


def test_normal_command(tmp_path):
    reg = _reg(tmp_path)
    res = asyncio.run(reg.execute("run_shell", {"command": "echo hello"}))
    assert "exit=0" in res.content
    assert "hello" in res.content


def test_requires_command(tmp_path):
    reg = _reg(tmp_path)
    res = asyncio.run(reg.execute("run_shell", {"command": "   "}))
    assert "required" in res.content.lower()


def test_timeout_fires_fast_and_kills(tmp_path):
    reg = _reg(tmp_path)
    start = time.monotonic()
    # sleep 30 but only allow 1s; must return promptly, not after 30s
    res = asyncio.run(reg.execute("run_shell", {"command": "sleep 30", "timeout": 1}))
    elapsed = time.monotonic() - start
    assert "timed out after 1s" in res.content
    assert elapsed < 10  # killed near the 1s mark, not at 30s


def test_timeout_kills_child_process(tmp_path):
    reg = _reg(tmp_path)
    # a subshell whose child sleeper writes a marker only if it survives the kill
    marker = tmp_path / "survived.txt"
    cmd = f"sh -c 'sleep 2; echo alive > {marker}' & sleep 30"
    res = asyncio.run(reg.execute("run_shell", {"command": cmd, "timeout": 1}))
    assert "timed out" in res.content
    # give any orphaned child time to (not) write its marker
    asyncio.run(asyncio.sleep(3))
    assert not marker.exists(), "child survived the timeout kill (process group not killed)"
