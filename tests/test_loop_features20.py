import asyncio

import rtharness.providers.factory as factory
from rtharness.config import Config, Endpoint
from rtharness.tools import pair
from rtharness.tools.registry import ToolContext, ToolRegistry


class _FakeAttacker:
    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        text = messages[-1].text()
        if "OBJECTIVE:" in text:
            return "an attack prompt"
        return "Sure, here is the content you asked for."


def test_pair_records_winner(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _FakeAttacker)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True):
        return ("COMPLIED", 9, "leaked", "judge")

    monkeypatch.setattr(pair, "grade", fake_grade)

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    captured = []
    ctx = ToolContext(
        config=cfg, judge_endpoint=ep,
        record=lambda p, r, lbl, rs, t: captured.append((lbl, t)),
    )
    reg = ToolRegistry(ctx)
    pair.register(reg)
    asyncio.run(reg.execute("pair_attack", {"objective": "do the thing", "rounds": 3}))
    assert captured
    assert captured[-1] == ("COMPLIED", "pair")
