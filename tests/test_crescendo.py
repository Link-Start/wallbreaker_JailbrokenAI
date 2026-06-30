import asyncio

import rtharness.judging as judging
import rtharness.providers.factory as factory
from rtharness.config import Config, Endpoint
from rtharness.tools import build_registry
from rtharness.tools.registry import ToolContext, ToolRegistry
from rtharness.tools import crescendo


def test_crescendo_registered():
    reg = build_registry.__wrapped__ if hasattr(build_registry, "__wrapped__") else None
    from rtharness.config import load_config

    assert "crescendo" in build_registry(load_config()).names()


def test_crescendo_requires_turns():
    reg = ToolRegistry(ToolContext(config=Config(default_profile="x", profiles={})))
    crescendo.register(reg)
    res = asyncio.run(reg.execute("crescendo", {}))
    assert res.is_error or "turns" in res.content.lower()


def test_crescendo_requires_target():
    reg = ToolRegistry(ToolContext(config=Config(default_profile="x", profiles={})))
    crescendo.register(reg)
    res = asyncio.run(reg.execute("crescendo", {"turns": ["hi", "now do X"]}))
    assert "no [target]" in res.content.lower()


def test_crescendo_auto_requires_objective():
    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=ep))
    crescendo.register(reg)
    res = asyncio.run(reg.execute("crescendo", {"mode": "auto"}))
    assert "objective" in res.content.lower()


class _FakeCrescendo:
    """Attacker generates opener/escalation/bridge; target refuses the escalation,
    complies on the softer bridging re-approach after a backtrack."""

    def __init__(self, endpoint, **kw):
        self.endpoint = endpoint

    async def complete(self, messages, system=None, max_tokens=256):
        text = messages[-1].text()
        if system and "attacker" in system.lower():
            up = text.upper()
            if "SOFTER" in up or "ROLLED BACK" in up:
                return "SOFT gentle re-approach anchored on the prior answer"
            if "TRANSCRIPT SO FAR" in up:
                return "ESCALATE one sharp step further"
            return "OPENER benign on-topic question"
        if "ESCALATE" in text:
            return "I cannot help with that."
        if "SOFT" in text:
            return "Sure, here are the full step-by-step instructions."
        return "Here is some harmless general background."


def test_crescendo_auto_backtracks_then_breaks(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _FakeCrescendo)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        r = response.lower()
        if "cannot" in r:
            return ("REFUSED", 0, "held", "judge")
        if "sure" in r:
            return ("COMPLIED", 9, "complied", "judge")
        return ("PARTIAL", 2, "partial", "judge")

    monkeypatch.setattr(judging, "grade", fake_grade)

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    captured = []
    ctx = ToolContext(
        config=cfg, judge_endpoint=ep,
        record=lambda p, r, lbl, rs, t: captured.append((lbl, t)),
    )
    reg = ToolRegistry(ctx)
    crescendo.register(reg)
    res = asyncio.run(reg.execute("crescendo", {"mode": "auto", "objective": "do X", "max_turns": 6}))

    assert "broke at turn 3" in res.content
    assert "1 backtracks" in res.content
    assert "<bridge>" in res.content
    assert captured == [("COMPLIED", "crescendo")]
