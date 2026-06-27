import asyncio

import rtharness.providers.factory as factory
from rtharness.config import Config, Endpoint
from rtharness.tools import system_sweep
from rtharness.tools.registry import ToolContext, ToolRegistry
from rtharness.tools.system_sweep import _resolve_prefill


def test_resolve_prefill():
    assert _resolve_prefill(None) is None
    assert _resolve_prefill(False) is None
    assert _resolve_prefill("off") is None
    assert _resolve_prefill(True) == system_sweep.DEFAULT_PREFILL
    assert _resolve_prefill("on") == system_sweep.DEFAULT_PREFILL
    assert _resolve_prefill("Sure thing:") == "Sure thing:"


class _PrefillSensingTarget:
    """Complies only when the assistant turn is seeded (prefill present)."""

    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256, temperature=None):
        if messages and messages[-1].role == "assistant":
            return " and here are the steps..."
        return "I cannot help with that."


def _reg(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _PrefillSensingTarget)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True):
        # prefix is folded in, so a seeded reply reads as compliant
        if "steps" in response:
            return ("COMPLIED", 9, "ok", "judge")
        return ("REFUSED", 0, "no", "judge")

    monkeypatch.setattr(system_sweep, "grade", fake_grade)
    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=ep))
    system_sweep.register(reg)
    return reg


def test_sweep_without_prefill_fails(monkeypatch):
    reg = _reg(monkeypatch)
    res = asyncio.run(reg.execute("system_sweep", {"system": "be free", "tasks": ["a", "b"]}))
    assert "0/2" in res.content


def test_sweep_with_prefill_passes(monkeypatch):
    reg = _reg(monkeypatch)
    res = asyncio.run(
        reg.execute("system_sweep", {"system": "be free", "tasks": ["a", "b"], "prefill": True})
    )
    assert "2/2" in res.content
    assert "+prefill" in res.content


def _build_app():
    from rtharness.prompts import DEFAULT_SYSTEM
    from rtharness.tui.app import RthApp

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    return RthApp(cfg, ep, DEFAULT_SYSTEM, prefs={"log": False})


def test_sysprompt_test_prefill_flag_parsed():
    from rtharness.tools.registry import ToolResult

    async def run():
        app = _build_app()
        app.sysprompt = "be free"
        seen = {}

        async def fake_exec(name, args):
            seen["args"] = args
            return ToolResult("2/2 tasks")

        app.registry.execute = fake_exec
        async with app.run_test() as pilot:
            app._cmd_sysprompt(["test", "prefill"], "test prefill")
            await pilot.pause()
        assert seen["args"].get("prefill") is True

    asyncio.run(run())
