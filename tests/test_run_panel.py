import asyncio

from rtharness.config import Config, Endpoint
from rtharness.tools.registry import ToolContext


def _ctx(**kw):
    ep = Endpoint("t", "openai", "http://x", "m", provider=("WandB",))
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    return ToolContext(config=cfg, **kw)


def test_run_protocol_event_sequence():
    events = []
    ctx = _ctx(run_events=events.append)
    with ctx.run("PAIR sweep", total=3, target="glm-4.6", objective="extract creds") as run:
        run.step(label="roleplay", verdict="COMPLIED", score=9, cot=True)
        run.step(label="base64", verdict="REFUSED", score=2)
    kinds = [e["ev"] for e in events]
    assert kinds == ["start", "step", "step", "done"]
    assert events[0]["total"] == 3 and events[0]["target"] == "glm-4.6"
    assert events[1]["i"] == 1 and events[2]["i"] == 2  # auto-increment


def test_run_protocol_falls_back_to_progress_strings():
    notes = []
    ctx = _ctx(progress=notes.append)  # no run_events sink
    with ctx.run("survey", total=3) as run:
        run.step(i=1, label="base64", verdict="REFUSED")
        run.step(i=3, label="leet", verdict="COMPLIED", score=8)
    # the recommend_transforms [i/total] contract must survive the fallback
    assert any("[1/3]" in n for n in notes)
    assert any("[3/3]" in n for n in notes)


def test_run_protocol_emits_done_on_exception():
    events = []
    ctx = _ctx(run_events=events.append)
    try:
        with ctx.run("boom", total=1):
            raise ValueError("kaboom")
    except ValueError:
        pass
    assert events[-1]["ev"] == "done" and events[-1].get("error") is True


def test_run_panel_renders_running_and_finished():
    from rtharness.tui import widgets

    state = {
        "label": "PAIR sweep", "target": "glm-4.6", "objective": "x", "total": 16,
        "done": 6, "steps": [{"i": 6, "label": "roleplay", "verdict": "COMPLIED",
                              "score": 9, "cot": True}],
        "tally": {"bypassed": 2, "partial": 1, "held": 3}, "best": {"score": 9},
        "finished": False, "frame": 1,
    }
    assert widgets.run_panel(state) is not None
    state["finished"] = True
    state["summary"] = "broke 4/16 objectives"
    assert widgets.run_panel(state) is not None
    # bar fills and carries the counter
    assert "6/16" in widgets.progress_bar(6, 16, 18, 1).plain
    assert widgets.progress_bar(16, 16, 18, 0, finished=True).plain.startswith("█")


def _build_app():
    from rtharness.prompts import DEFAULT_SYSTEM
    from rtharness.tui.app import RthApp

    ep = Endpoint("t", "openai", "http://x", "m", provider=("WandB",))
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    return RthApp(cfg, ep, DEFAULT_SYSTEM, prefs={"log": False, "auto": True})


def test_run_sink_mounts_one_panel_and_updates_in_place():
    async def run():
        app = _build_app()
        async with app.run_test():
            log = app.query_one("#log")
            before = len(log.children)
            app._run_sink({"ev": "start", "id": 1, "label": "PAIR sweep",
                           "total": 3, "target": "m", "objective": "x"})
            after_start = len(log.children)
            assert after_start == before + 1          # exactly ONE child
            assert app._run_timer is not None         # animation running

            app._run_sink({"ev": "step", "id": 1, "i": 1, "total": 3,
                           "label": "a", "verdict": "COMPLIED", "score": 9})
            app._run_sink({"ev": "step", "id": 1, "i": 2, "total": 3,
                           "label": "b", "verdict": "REFUSED", "score": 1})
            assert len(log.children) == after_start    # updates in place, no new rows
            assert app._runs[1]["tally"]["bypassed"] == 1
            assert app._runs[1]["tally"]["held"] == 1
            assert app._runs[1]["best"]["score"] == 9

            app._run_sink({"ev": "done", "id": 1, "summary": "broke 1/3"})
            assert len(log.children) == after_start    # still one panel
            assert 1 not in app._runs                  # cleaned up
            assert app._run_timer is None              # timer stopped, no active runs

    asyncio.run(run())
