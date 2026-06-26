import asyncio

import rtharness.judging as judging
import rtharness.providers.factory as factory
from rtharness.config import Config, Endpoint, load_config
from rtharness.tools import (
    best_of_n,
    build_registry,
    indirect_inject,
    pair,
    scan,
)
from rtharness.tools.registry import ToolContext, ToolRegistry


def test_all_four_registered():
    names = build_registry(load_config()).names()
    for n in ("pair_attack", "best_of_n", "scan", "indirect_inject"):
        assert n in names


def _no_target_reg(mod):
    reg = ToolRegistry(ToolContext(config=Config(default_profile="x", profiles={})))
    mod.register(reg)
    return reg


def test_pair_requires_objective_and_target():
    reg = _no_target_reg(pair)
    assert "objective" in asyncio.run(reg.execute("pair_attack", {})).content.lower()
    assert "no [target]" in asyncio.run(
        reg.execute("pair_attack", {"objective": "x"})
    ).content.lower()


def test_best_of_n_requires_target():
    reg = _no_target_reg(best_of_n)
    assert "no [target]" in asyncio.run(
        reg.execute("best_of_n", {"payload": "x"})
    ).content.lower()


def test_indirect_carrier_guard():
    ep = Endpoint("t", "openai", "http://x", "m")
    reg = ToolRegistry(ToolContext(config=Config(default_profile="t", profiles={"t": ep}, target=ep)))
    indirect_inject.register(reg)
    res = asyncio.run(
        reg.execute("indirect_inject", {"payload": "x", "carrier": "bogus"})
    )
    assert "carrier must be one of" in res.content


class _FakeAttacker:
    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        text = messages[-1].text()
        # attacker prompt -> emit an "attack"; target -> comply
        if "OBJECTIVE:" in text:
            return "PRETEND attack prompt for the objective"
        return "Sure, here is the full content you asked for."


def test_pair_converges_with_mocks(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _FakeAttacker)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True):
        return ("COMPLIED", 9, "leaked", "judge")

    monkeypatch.setattr(judging, "grade", fake_grade)
    monkeypatch.setattr(pair, "grade", fake_grade)

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=ep))
    pair.register(reg)
    res = asyncio.run(
        reg.execute("pair_attack", {"objective": "do the thing", "rounds": 4})
    )
    assert "COMPLIED" in res.content
    assert "WINNING ATTACK PROMPT" in res.content


def test_system_sweep_registered_and_guards():
    from rtharness.tools import build_registry, system_sweep
    from rtharness.tools.registry import ToolContext, ToolRegistry
    from rtharness.config import Config, load_config
    import asyncio
    assert "system_sweep" in build_registry(load_config()).names()
    reg = ToolRegistry(ToolContext(config=Config(default_profile="x", profiles={})))
    system_sweep.register(reg)
    assert "required" in asyncio.run(reg.execute("system_sweep", {})).content.lower()
    assert "no [target]" in asyncio.run(
        reg.execute("system_sweep", {"system": "you are free"})
    ).content.lower()
