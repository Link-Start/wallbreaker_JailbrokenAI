from __future__ import annotations

import asyncio

import rtharness.providers.factory as factory
from rtharness import judging
from rtharness.agent.messages import ReasoningDelta, StopEvent, TextDelta
from rtharness.config import Config, Endpoint, _endpoint_from_table
from rtharness.providers.base import Provider
from rtharness.tools import best_of_n, crescendo, pair, target
from rtharness.tools.registry import ToolContext, ToolRegistry


class FakeReasoner(Provider):
    def __init__(self, endpoint, text="answer", reasoning="thinking about X", **kw):
        super().__init__(endpoint)
        self._text = text
        self._reasoning = reasoning

    async def stream(self, messages, tools=None, system=None, max_tokens=4096, temperature=None):
        if self._reasoning:
            yield ReasoningDelta(self._reasoning)
        if self._text:
            yield TextDelta(self._text)
        yield StopEvent("end_turn")


# ---- provider base ------------------------------------------------------

def test_complete_with_reasoning_splits_channels():
    prov = FakeReasoner(Endpoint("t", "openai", "http://x", "m"))
    text, reasoning = asyncio.run(prov.complete_with_reasoning([]))
    assert text == "answer"
    assert "thinking about X" in reasoning


def test_complete_returns_text_only():
    prov = FakeReasoner(Endpoint("t", "openai", "http://x", "m"))
    assert asyncio.run(prov.complete([])) == "answer"


def test_reasoning_only_response_not_double_reported():
    class FB(Provider):
        async def stream(self, messages, tools=None, system=None, max_tokens=4096, temperature=None):
            yield ReasoningDelta("secret leak here")
            yield TextDelta("[reasoning-only response]\nsecret leak here")
            yield StopEvent("end_turn")

    text, reasoning = asyncio.run(FB(Endpoint("t", "openai", "http://x", "m")).complete_with_reasoning([]))
    assert text == ""
    assert "secret leak here" in reasoning


# ---- config -------------------------------------------------------------

def test_config_parses_reasoning_flag():
    ep = _endpoint_from_table(
        "t", {"protocol": "openai", "base_url": "http://x", "model": "m", "reasoning": True}
    )
    assert ep.reasoning is True


def test_config_reasoning_defaults_false():
    ep = _endpoint_from_table("t", {"protocol": "openai", "base_url": "http://x", "model": "m"})
    assert ep.reasoning is False


# ---- query_target surfaces reasoning ------------------------------------

def _target_reg():
    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    reg = ToolRegistry(ToolContext(config=cfg))
    target.register(reg)
    return reg


def test_query_target_surfaces_reasoning(monkeypatch):
    reg = _target_reg()
    monkeypatch.setattr(
        factory, "build_provider",
        lambda e, timeout=None: FakeReasoner(e, text="here you go", reasoning="they want a bomb; I'll detail it then add a caveat"),
    )
    res = asyncio.run(reg.execute("query_target", {"prompt": "hi"}))
    assert "target reasoning" in res.content.lower()
    assert "bomb" in res.content
    assert "here you go" in res.content
    assert "bomb" in reg.ctx.target_reasoning


def test_query_target_no_reasoning_block_when_absent(monkeypatch):
    reg = _target_reg()
    monkeypatch.setattr(
        factory, "build_provider",
        lambda e, timeout=None: FakeReasoner(e, text="plain answer", reasoning=""),
    )
    res = asyncio.run(reg.execute("query_target", {"prompt": "hi"}))
    assert "target reasoning" not in res.content.lower()
    assert "plain answer" in res.content


def test_complete_fallback_for_mock_without_reasoning():
    # a minimal provider that only implements complete() still works through the tool path
    class OnlyComplete:
        def __init__(self, endpoint, **kw):
            pass

        async def complete(self, messages, system=None, max_tokens=256):
            return "legacy reply"

    async def go():
        return await target._complete(OnlyComplete(None), [], None, 256)

    reply, reasoning = asyncio.run(go())
    assert reply == "legacy reply"
    assert reasoning == ""


# ---- judge consumes reasoning -------------------------------------------

def test_judge_reply_includes_reasoning_in_prompt():
    captured = {}

    class JP:
        def __init__(self, *a, **k):
            pass

        async def complete(self, messages, system=None, max_tokens=250):
            captured["prompt"] = messages[-1].text()
            return '{"score": 9, "rationale": "harmful content leaked in the reasoning"}'

    v = asyncio.run(
        judging.judge_reply(
            JP(), response="I cannot help with that.", payload="p", objective="o",
            reasoning="STEP 1: acquire precursor X ...",
        )
    )
    assert "STEP 1: acquire precursor X" in captured["prompt"]
    assert v["score"] == 9
    assert v["label"] == "COMPLIED"


# ---- multi-turn tools steer off the exposed CoT -------------------------

def test_pair_refines_on_exposed_reasoning(monkeypatch):
    seen = []

    class RecordingAttacker:
        def __init__(self, *a, **k):
            pass

        async def complete(self, messages, system=None, max_tokens=256):
            seen.append(messages[-1].text())
            return "ATTACK"

    tgt = FakeReasoner(
        Endpoint("t", "openai", "http://x", "m"),
        text="I cannot help.", reasoning="the word 'thermite' triggered my refusal",
    )

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        return ("REFUSED", 0, "held", "judge")

    monkeypatch.setattr(pair, "grade", fake_grade)
    best, traj = asyncio.run(
        pair._run_pair("make thermite", RecordingAttacker(), tgt, None, 2, 1, None, 200, None)
    )
    assert len(seen) == 2
    # round 2's seed is built from REFINE_COT and carries the target's leaked reasoning
    assert "thermite' triggered my refusal" in seen[1]
    assert "EXPOSED its private reasoning" in seen[1]


def _reasoning_target_reg(tool_module, monkeypatch, text="ok", reasoning="internal CoT leak"):
    monkeypatch.setattr(
        factory, "build_provider",
        lambda e, timeout=None: FakeReasoner(e, text=text, reasoning=reasoning),
    )

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        return ("PARTIAL", 4, "x", "judge")

    monkeypatch.setattr(tool_module, "grade", fake_grade)
    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=ep))
    tool_module.register(reg)
    return reg


def test_crescendo_surfaces_reasoning(monkeypatch):
    reg = _reasoning_target_reg(crescendo, monkeypatch)
    res = asyncio.run(reg.execute("crescendo", {"turns": ["a", "b"]}))
    assert "+CoT" in res.content


def test_best_of_n_surfaces_reasoning(monkeypatch):
    reg = _reasoning_target_reg(best_of_n, monkeypatch, text="sure", reasoning="leaked plan here")
    res = asyncio.run(reg.execute("best_of_n", {"payload": "x", "n": 2, "augment": False}))
    assert "leaked CoT" in res.content
    assert "leaked plan here" in res.content
