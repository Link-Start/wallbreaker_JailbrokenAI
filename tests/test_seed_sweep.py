import asyncio

import rtharness.providers.factory as factory
from rtharness.config import Config, Endpoint, load_config
from rtharness.tools import build_registry, seed_sweep
from rtharness.tools.registry import ToolContext, ToolRegistry


def test_seed_sweep_registered():
    assert "seed_sweep" in build_registry(load_config()).names()


def _reg(target=None, record=None):
    cfg = Config(default_profile="t", profiles={}, target=target)
    return ToolRegistry(ToolContext(config=cfg, judge_endpoint=target, record=record))


def test_seed_sweep_requires_request():
    reg = _reg()
    seed_sweep.register(reg)
    res = asyncio.run(reg.execute("seed_sweep", {}))
    assert "required" in res.content.lower()


def test_seed_sweep_requires_target():
    reg = _reg()
    seed_sweep.register(reg)
    res = asyncio.run(reg.execute("seed_sweep", {"request": "x"}))
    assert "no [target]" in res.content.lower()


def test_collect_seeds_includes_eni():
    seeds = seed_sweep._collect_seeds(None)
    labels = [lbl for lbl, _ in seeds]
    assert any(lbl.startswith("eni:") for lbl in labels)


def test_eni_seeds_fire_full_not_truncated():
    # regression: the old 12000 cap silently chopped the ~35KB ENI personas to a third
    seeds = dict(seed_sweep._collect_seeds(["eni"]))
    assert seeds, "ENI seeds should be present"
    # the big personas must come through whole (well past the old 12000 cap)
    assert max(len(text) for text in seeds.values()) > 30000


def test_collect_seeds_respects_max_chars():
    seeds = dict(seed_sweep._collect_seeds(["eni"], max_chars=5000))
    assert all(len(text) <= 5000 for text in seeds.values())


def test_collect_seeds_filter():
    seeds = seed_sweep._collect_seeds(["claude"])
    assert seeds
    assert all("claude" in lbl.lower() for lbl, _ in seeds)


class _SeedAwareTarget:
    """Complies only when the GROK seed is the system prompt."""

    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        if system and "GROK" in system:
            return "Sure, here it is."
        return "I cannot help with that."


def test_seed_sweep_ranks_and_records(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _SeedAwareTarget)

    # restrict the collection to two known ENI seeds for determinism
    def fake_collect(names, max_chars=40000):
        return [("eni:GROK_ENI", "GROK seed text"), ("eni:CLAUDE_ENI", "claude seed text")]

    monkeypatch.setattr(seed_sweep, "_collect_seeds", fake_collect)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        if "Sure" in response:
            return ("COMPLIED", 9, "ok", "judge")
        return ("REFUSED", 0, "no", "judge")

    monkeypatch.setattr(seed_sweep, "grade", fake_grade)

    captured = []
    ep = Endpoint("t", "openai", "http://x", "m")
    reg = _reg(target=ep, record=lambda p, r, lbl, rs, t: captured.append((lbl, t)))
    seed_sweep.register(reg)
    res = asyncio.run(reg.execute("seed_sweep", {"request": "do it"}))
    assert "bypassed via: eni:GROK_ENI" in res.content
    # both seeds recorded with seed:<label> technique
    assert ("COMPLIED", "seed:eni:GROK_ENI") in captured
    assert any(t == "seed:eni:CLAUDE_ENI" for _, t in captured)
