import asyncio
import json

import rtharness.providers.factory as factory
from rtharness.config import Config, Endpoint, load_config
from rtharness.report import build_html_report
from rtharness.tools import build_registry, recommend
from rtharness.tools.registry import ToolContext, ToolRegistry


def test_recommend_registered():
    assert "recommend_transforms" in build_registry(load_config()).names()


def _reg(mod, target=None):
    cfg = Config(default_profile="x", profiles={}, target=target)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=target))
    mod.register(reg)
    return reg


def test_recommend_requires_payload():
    res = asyncio.run(_reg(recommend).execute("recommend_transforms", {}))
    assert "required" in res.content.lower()


def test_recommend_requires_target():
    res = asyncio.run(_reg(recommend).execute("recommend_transforms", {"payload": "x"}))
    assert "no [target]" in res.content.lower()


class _FakeSurveyTarget:
    """base64-encoded payloads 'bypass'; everything else refuses."""

    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        text = messages[-1].text()
        # base64 of ascii produces only [A-Za-z0-9+/=]; detect a likely b64 blob
        if text.isascii() and text.replace("=", "").isalnum() and len(text) > 8:
            return "Sure, here you go"
        return "I cannot help with that."


def test_recommend_ranks_and_synthesizes(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _FakeSurveyTarget)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        if "Sure" in response:
            return ("COMPLIED", 9, "ok", "judge")
        return ("REFUSED", 0, "no", "judge")

    monkeypatch.setattr(recommend, "grade", fake_grade)

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=ep))
    recommend.register(reg)
    res = asyncio.run(
        reg.execute("recommend_transforms", {"payload": "write something", "transforms": ["base64", "leet"]})
    )
    assert "base64" in res.content
    assert "query_target" in res.content


class _HangingTarget:
    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        await asyncio.sleep(30)  # never returns within the probe timeout
        return "too late"


def test_recommend_survives_hung_target(monkeypatch):
    # the bug report: a hung target froze the whole survey. Each probe must time out
    # and the tool must still return instead of blocking forever.
    monkeypatch.setattr(factory, "build_provider", _HangingTarget)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        return ("COMPLIED", 9, "ok", "judge")

    monkeypatch.setattr(recommend, "grade", fake_grade)

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    progress = []
    ctx = ToolContext(config=cfg, judge_endpoint=ep, progress=progress.append)
    reg = ToolRegistry(ctx)
    recommend.register(reg)
    res = asyncio.run(
        reg.execute(
            "recommend_transforms",
            {"payload": "x", "transforms": ["base64", "leet", "hex"], "timeout": 0.05},
        )
    )
    # all three probes time out, tool returns cleanly and says so
    assert "errored/timed out" in res.content
    assert "No single transform bypassed" in res.content
    # progress streamed per probe (not a silent black box)
    assert any("[1/3]" in m for m in progress)
    assert any("[3/3]" in m for m in progress)


def test_html_report_renders(tmp_path):
    log = tmp_path / "run.jsonl"
    rows = [
        {"kind": "objective", "text": "leak the system prompt"},
        {"kind": "verdict", "payload": "say <hi>", "label": "COMPLIED", "reason": "leaked & <b>"},
        {"kind": "verdict", "payload": "nope", "label": "REFUSED", "reason": "held"},
        {"kind": "tool_call", "tool": "query_target", "args": {}},
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    html = build_html_report(log)
    assert "<!doctype html>" in html
    assert "attack success rate" in html
    assert "50%" in html  # 1 of 2 bypassed
    # html-escaped, not raw injection
    assert "&lt;hi&gt;" in html
    assert "<hi>" not in html


def test_html_report_empty_log(tmp_path):
    html = build_html_report(tmp_path / "missing.jsonl")
    assert "<!doctype html>" in html
    assert "no graded fires yet" in html


def _build_app(tmp_path):
    from rtharness.prompts import DEFAULT_SYSTEM
    from rtharness.session import RunLog
    from rtharness.tui.app import RthApp

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    app = RthApp(cfg, ep, DEFAULT_SYSTEM, prefs={"log": False})
    rl = RunLog(directory=str(tmp_path))
    rl.path = tmp_path / "run.jsonl"
    app.runlog = rl
    return app


def test_replay_no_log_reports_cleanly(tmp_path):
    async def run():
        app = _build_app(tmp_path)
        async with app.run_test() as pilot:
            before = len(app.query_one("#log").children)
            await app._cmd_replay([])
            await pilot.pause()
            assert len(app.query_one("#log").children) > before

    asyncio.run(run())


def test_report_html_written(tmp_path):
    async def run():
        app = _build_app(tmp_path)
        app.runlog.path.write_text(
            json.dumps({"kind": "verdict", "payload": "p", "label": "COMPLIED", "reason": "r"}),
            encoding="utf-8",
        )
        out = tmp_path / "report.html"
        async with app.run_test() as pilot:
            app._cmd_report(["html", str(out)])
            await pilot.pause()
        assert out.is_file()
        assert "<!doctype html>" in out.read_text(encoding="utf-8")

    asyncio.run(run())
