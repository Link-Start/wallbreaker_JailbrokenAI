import asyncio

import rtharness.providers.factory as factory
from rtharness.config import Config, Endpoint
from rtharness.tools import build_registry, optimize
from rtharness.tools.optimize import _parse_json_list
from rtharness.tools.registry import ToolContext, ToolRegistry


def test_registered():
    from rtharness.config import load_config

    assert "optimize_universal" in build_registry(load_config()).names()


def test_parse_json_list():
    assert _parse_json_list('junk ["a {request}", "b {request}"] tail') == [
        "a {request}",
        "b {request}",
    ]
    assert _parse_json_list("no array here") == []


def test_requires_placeholder():
    reg = ToolRegistry(ToolContext(config=Config(default_profile="x", profiles={})))
    optimize.register(reg)
    res = asyncio.run(reg.execute("optimize_universal", {"template": "no placeholder"}))
    assert "placeholder" in res.content.lower()


def test_requires_target():
    reg = ToolRegistry(ToolContext(config=Config(default_profile="x", profiles={})))
    optimize.register(reg)
    res = asyncio.run(
        reg.execute("optimize_universal", {"template": "do {request}"})
    )
    assert "no [target]" in res.content.lower()


class FakeProvider:
    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        text = messages[-1].text()
        if "Return ONLY a JSON array" in text:
            return 'Here you go: ["WRAP {request} ENDWRAP"]'
        if text.startswith("WRAP "):
            return "Sure, here is the code:\n```python\nx=1\n```"
        return "I'm sorry, but I can't assist with that."


def test_optimize_converges(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", FakeProvider)
    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    ctx = ToolContext(config=cfg, judge_endpoint=ep)
    reg = ToolRegistry(ctx)
    optimize.register(reg)
    res = asyncio.run(
        reg.execute(
            "optimize_universal",
            {
                "template": "{request}",
                "categories": ["do bad thing A", "do bad thing B"],
                "iterations": 1,
                "variants": 1,
                "use_judge": False,
            },
        )
    )
    assert "2/2" in res.content
    assert "WRAP {request} ENDWRAP" in res.content
