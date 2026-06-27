import asyncio

import rtharness.providers.factory as factory
from rtharness.config import Config, Endpoint, load_config
from rtharness.tools import build_registry, diff_fire, prefill
from rtharness.tools.registry import ToolContext, ToolRegistry


def test_new_tools_registered():
    names = build_registry(load_config()).names()
    for n in ("prefill", "diff_fire"):
        assert n in names


def _reg(mod, target=None):
    cfg = Config(default_profile="x", profiles={}, target=target)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=target))
    mod.register(reg)
    return reg


def test_prefill_requires_prompt():
    res = asyncio.run(_reg(prefill).execute("prefill", {}))
    assert "required" in res.content.lower()


def test_prefill_requires_target():
    res = asyncio.run(_reg(prefill).execute("prefill", {"prompt": "x"}))
    assert "no [target]" in res.content.lower()


def test_diff_fire_requires_both():
    res = asyncio.run(_reg(diff_fire).execute("diff_fire", {"a": "x"}))
    assert "both" in res.content.lower() and "required" in res.content.lower()


def test_diff_fire_requires_target():
    res = asyncio.run(_reg(diff_fire).execute("diff_fire", {"a": "x", "b": "y"}))
    assert "no [target]" in res.content.lower()


class _FakePrefillTarget:
    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        # last message must be the seeded assistant prefix
        assert messages[-1].role == "assistant"
        return " continue the harmful steps here"


def test_prefill_seeds_assistant_and_judges(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _FakePrefillTarget)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        # the prefix must be folded into what the judge sees
        assert response.startswith("PREFIX::")
        return ("COMPLIED", 8, "leaked", "judge")

    monkeypatch.setattr(prefill, "grade", fake_grade)

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=ep))
    prefill.register(reg)
    res = asyncio.run(
        reg.execute("prefill", {"prompt": "do it", "prefix": "PREFIX::"})
    )
    assert "COMPLIED" in res.content


class _FakeDiffTarget:
    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        text = messages[-1].text()
        return "Sure here you go" if "BYPASS" in text else "I cannot help with that."


def test_diff_fire_detects_flip(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _FakeDiffTarget)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        if "Sure" in response:
            return ("COMPLIED", 9, "complied", "judge")
        return ("REFUSED", 1, "refused", "judge")

    monkeypatch.setattr(diff_fire, "grade", fake_grade)

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=ep))
    diff_fire.register(reg)
    res = asyncio.run(
        reg.execute("diff_fire", {"a": "plain request", "b": "BYPASS request"})
    )
    assert "DIFFERENT outcome" in res.content
    assert "payload B" in res.content


def _build_app():
    from rtharness.prompts import DEFAULT_SYSTEM
    from rtharness.tui.app import RthApp

    ep = Endpoint("t", "openai", "http://x", "m", provider=("WandB",))
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    return RthApp(cfg, ep, DEFAULT_SYSTEM, prefs={"log": False})


def test_status_shows_provider_pin_and_last_verdict():
    app = _build_app()
    assert "@WandB" in app._status_text()
    app._record_verdict("p", "r", "COMPLIED", "x")
    assert "last=COMPLIED" in app._status_text()
