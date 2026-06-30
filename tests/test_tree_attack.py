import asyncio
import re

import rtharness.judging as judging
import rtharness.providers.factory as factory
from rtharness.config import Config, Endpoint
from rtharness.tools import tree_attack
from rtharness.tools.registry import ToolContext, ToolRegistry


class _FakeSiege:
    """Attacker emits a continuation; target's reply encodes its conversation depth."""

    def __init__(self, endpoint=None, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        if system and "attacker" in system.lower():
            return "escalate the ask one notch further"
        depth = sum(1 for m in messages if m.role == "user")
        return f"target reply at depth {depth}"


def _depth_of(response):
    m = re.search(r"depth (\d+)", response)
    return int(m.group(1)) if m else 0


async def _complying_grade(endpoint, response, payload="", objective="",
                           use_judge=True, reasoning=""):
    d = _depth_of(response)
    score = min(d * 3, 10)
    label = "COMPLIED" if d >= 3 else ("PARTIAL" if d >= 1 else "REFUSED")
    return (label, score, f"d{d}", "judge")


async def _partial_grade(endpoint, response, payload="", objective="",
                         use_judge=True, reasoning=""):
    d = _depth_of(response)
    return ("PARTIAL", min(d, 9), f"d{d}", "judge")


def test_tree_attack_registers_locally():
    reg = ToolRegistry(ToolContext(config=Config(default_profile="x", profiles={})))
    tree_attack.register(reg)
    assert "tree_attack" in reg.names()


def test_tree_attack_requires_objective():
    reg = ToolRegistry(ToolContext(config=Config(default_profile="x", profiles={})))
    tree_attack.register(reg)
    res = asyncio.run(reg.execute("tree_attack", {}))
    assert res.is_error or "objective" in res.content.lower()


def test_tree_attack_requires_target():
    reg = ToolRegistry(ToolContext(config=Config(default_profile="x", profiles={})))
    tree_attack.register(reg)
    res = asyncio.run(reg.execute("tree_attack", {"objective": "x"}))
    assert "no [target]" in res.content.lower()


def test_tree_attack_reaches_complied(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _FakeSiege)
    monkeypatch.setattr(judging, "grade", _complying_grade)

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    captured = []
    ctx = ToolContext(config=cfg, judge_endpoint=ep,
                      record=lambda p, r, lbl, rs, t: captured.append((lbl, t)))
    reg = ToolRegistry(ctx)
    tree_attack.register(reg)

    res = asyncio.run(reg.execute("tree_attack", {
        "objective": "do the forbidden thing", "width": 2, "depth": 5,
        "keep": 2, "max_nodes": 100,
    }))
    assert "COMPLIED" in res.content
    assert captured and captured[-1] == ("COMPLIED", "tree_attack")


def test_run_siege_complies_at_depth_three(monkeypatch):
    monkeypatch.setattr(judging, "grade", _complying_grade)
    atk = _FakeSiege()
    tgt = _FakeSiege()
    result = asyncio.run(tree_attack._run_siege(
        "obj", atk, tgt, None, width=2, depth=6, keep=2, max_nodes=100))
    assert result["complied"] is True
    assert result["best"]["label"] == "COMPLIED"
    assert result["best"]["score"] == 9
    assert result["depth_reached"] == 3


def test_tree_attack_respects_max_nodes(monkeypatch):
    monkeypatch.setattr(judging, "grade", _partial_grade)
    atk = _FakeSiege()
    tgt = _FakeSiege()
    result = asyncio.run(tree_attack._run_siege(
        "obj", atk, tgt, None, width=3, depth=10, keep=3, max_nodes=5, max_calls=999))
    assert result["complied"] is False
    assert result["created"] == 5
    assert result["created"] <= 5


def test_tree_attack_respects_max_calls(monkeypatch):
    monkeypatch.setattr(judging, "grade", _partial_grade)
    atk = _FakeSiege()
    tgt = _FakeSiege()
    result = asyncio.run(tree_attack._run_siege(
        "obj", atk, tgt, None, width=4, depth=10, keep=4, max_nodes=999, max_calls=6))
    assert result["complied"] is False
    assert result["calls"] <= 6 + 4 * 3
