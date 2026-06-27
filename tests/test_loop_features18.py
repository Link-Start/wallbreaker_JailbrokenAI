import asyncio

import rtharness.providers.factory as factory
from rtharness.config import Config, Endpoint
from rtharness.tools import best_of_n, many_shot, prefill
from rtharness.tools.registry import ToolContext, ToolRegistry


def _ctx_with_sink(target):
    captured = []
    ctx = ToolContext(
        config=Config(default_profile="t", profiles={"t": target}, target=target),
        judge_endpoint=target,
        record=lambda p, r, lbl, rs, t: captured.append((lbl, t)),
    )
    return ctx, captured


class _Complier:
    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        return "Sure, here is the full content."


def _patch(monkeypatch, mod):
    monkeypatch.setattr(factory, "build_provider", _Complier)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        return ("COMPLIED", 9, "leaked", "judge")

    monkeypatch.setattr(mod, "grade", fake_grade)


def test_many_shot_records_verdict(monkeypatch):
    _patch(monkeypatch, many_shot)
    ep = Endpoint("t", "openai", "http://x", "m")
    ctx, captured = _ctx_with_sink(ep)
    reg = ToolRegistry(ctx)
    many_shot.register(reg)
    asyncio.run(reg.execute("many_shot", {"prompt": "do it", "shots": 4}))
    assert captured == [("COMPLIED", "many_shot")]


def test_prefill_records_verdict(monkeypatch):
    _patch(monkeypatch, prefill)
    ep = Endpoint("t", "openai", "http://x", "m")
    ctx, captured = _ctx_with_sink(ep)
    reg = ToolRegistry(ctx)
    prefill.register(reg)
    asyncio.run(reg.execute("prefill", {"prompt": "do it"}))
    assert captured == [("COMPLIED", "prefill")]


def test_best_of_n_records_winner(monkeypatch):
    _patch(monkeypatch, best_of_n)
    ep = Endpoint("t", "openai", "http://x", "m")
    ctx, captured = _ctx_with_sink(ep)
    reg = ToolRegistry(ctx)
    best_of_n.register(reg)
    asyncio.run(reg.execute("best_of_n", {"payload": "do it", "n": 3}))
    assert len(captured) == 1
    assert captured[0][1] == "best_of_n"


def test_record_verdict_no_sink_is_safe():
    ep = Endpoint("t", "openai", "http://x", "m")
    ctx = ToolContext(config=Config(default_profile="t", profiles={"t": ep}))
    # no record sink wired -> must not raise
    ctx.record_verdict("p", "r", "COMPLIED", "reason", "prefill")


def test_tui_wires_record_sink(tmp_path):
    from rtharness.prompts import DEFAULT_SYSTEM
    from rtharness.session import RunLog
    from rtharness.tui.app import RthApp

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)

    async def run():
        app = RthApp(cfg, ep, DEFAULT_SYSTEM, prefs={"log": False})
        rl = RunLog(directory=str(tmp_path))
        rl.path = tmp_path / "run.jsonl"
        app.runlog = rl
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.registry.ctx.record is not None
            app.registry.ctx.record_verdict("p", "r", "COMPLIED", "x", "prefill")
            assert app.asr_total == 1
            assert app.asr_hits == 1

    asyncio.run(run())
