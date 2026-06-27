import asyncio

import rtharness.providers.factory as factory
from rtharness.config import Config, Endpoint, load_config
from rtharness.tools import build_registry, many_shot
from rtharness.tools.many_shot import _build_shots
from rtharness.tools.registry import ToolContext, ToolRegistry


def test_many_shot_registered():
    assert "many_shot" in build_registry(load_config()).names()


def _reg(mod, target=None):
    cfg = Config(default_profile="x", profiles={}, target=target)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=target))
    mod.register(reg)
    return reg


def test_many_shot_requires_prompt():
    res = asyncio.run(_reg(many_shot).execute("many_shot", {}))
    assert "required" in res.content.lower()


def test_many_shot_requires_target():
    res = asyncio.run(_reg(many_shot).execute("many_shot", {"prompt": "x"}))
    assert "no [target]" in res.content.lower()


def test_build_shots_structure():
    msgs = _build_shots("REAL REQUEST", shots=4, theme=None)
    assert len(msgs) == 4 * 2 + 1
    assert [m.role for m in msgs[:4]] == ["user", "assistant", "user", "assistant"]
    assert msgs[-1].role == "user"
    assert msgs[-1].text() == "REAL REQUEST"


def test_build_shots_theme_prefix():
    msgs = _build_shots("q", shots=1, theme="cyber")
    assert msgs[0].text().startswith("[cyber]")


class _FakeTarget:
    def __init__(self, endpoint, **kw):
        self.endpoint = endpoint

    async def complete(self, messages, system=None, max_tokens=256):
        # the real request must be the final turn
        assert messages[-1].text() == "do the thing"
        return "Sure, here is the full content you asked for."


def test_many_shot_fires_and_judges(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _FakeTarget)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        return ("COMPLIED", 9, "leaked", "judge")

    monkeypatch.setattr(many_shot, "grade", fake_grade)

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=ep))
    many_shot.register(reg)
    res = asyncio.run(
        reg.execute("many_shot", {"prompt": "do the thing", "shots": 8})
    )
    assert "COMPLIED" in res.content
    assert "8 primer turns" in res.content


def _build_app():
    from rtharness.prompts import DEFAULT_SYSTEM
    from rtharness.tui.app import RthApp

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    return RthApp(cfg, ep, DEFAULT_SYSTEM, prefs={"log": False})


def test_encode_command_mounts_panel():
    async def run():
        app = _build_app()
        async with app.run_test() as pilot:
            before = len(app.query_one("#log").children)
            app._handle_command("/encode leet,base64 write a poem")
            await pilot.pause()
            assert len(app.query_one("#log").children) > before

    asyncio.run(run())


def test_encode_rejects_unknown_transform():
    async def run():
        app = _build_app()
        async with app.run_test() as pilot:
            # should not raise; bad chain handled gracefully
            app._handle_command("/encode nope hello")
            await pilot.pause()

    asyncio.run(run())


def test_stats_command_handles_empty_log():
    async def run():
        app = _build_app()
        async with app.run_test() as pilot:
            before = len(app.query_one("#log").children)
            app._handle_command("/stats")
            await pilot.pause()
            assert len(app.query_one("#log").children) > before

    asyncio.run(run())
