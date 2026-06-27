import asyncio

from rtharness.agent.loop import AgentEvents, run_autonomous
from rtharness.agent.messages import Message, StopEvent, TextDelta, user
from rtharness.config import Config, Endpoint


class _Provider:
    """Streams plain text (no tool calls) so each round is 'idle'; finishes round 1
    only if it sees operator feedback in history."""

    def __init__(self, *a, **k):
        pass

    async def stream(self, history, tools=None, system=None, max_tokens=4096, temperature=None):
        yield TextDelta("thinking")
        yield StopEvent("end_turn")


def test_feedback_injected_between_rounds():
    history = [user("go")]
    queue = [["try the GLM ENI seed"]]  # available at the first drain
    injected = []

    def feedback():
        return queue.pop(0) if queue else []

    events = AgentEvents(on_feedback=lambda m: injected.append(m))
    # 1 round is enough: feedback drained at round start
    asyncio.run(run_autonomous(
        _Provider(), None, history, events=events, max_rounds=1, feedback=feedback,
    ))
    assert injected == ["try the GLM ENI seed"]
    # the operator message is now in the conversation, framed for the agent
    texts = [m.text() for m in history if m.role == "user"]
    assert any("OPERATOR FEEDBACK" in t and "GLM ENI seed" in t for t in texts)


def test_no_feedback_uses_nudge():
    history = [user("go")]
    asyncio.run(run_autonomous(
        _Provider(), None, history, max_rounds=1, feedback=lambda: [],
    ))
    # with no feedback the continue-nudge is appended at end of round
    assert any("autonomous mode" in m.text() for m in history if m.role == "user")


def _build_app():
    from rtharness.prompts import DEFAULT_SYSTEM
    from rtharness.tui.app import RthApp

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    return RthApp(cfg, ep, DEFAULT_SYSTEM, prefs={"log": False, "auto": True})


def test_busy_input_queues_feedback_in_auto():
    async def run():
        app = _build_app()
        app._busy = True
        async with app.run_test() as pilot:
            from textual.widgets import Input
            inp = app.query_one("#prompt", Input)
            inp.value = "drop the encoding, go fiction-frame"
            await pilot.press("enter")
            await pilot.pause()
            assert app._pending_feedback == ["drop the encoding, go fiction-frame"]
            # drain returns and clears
            assert app._drain_feedback() == ["drop the encoding, go fiction-frame"]
            assert app._pending_feedback == []

    asyncio.run(run())


def test_busy_input_rejected_when_not_auto():
    async def run():
        app = _build_app()
        app.auto = False
        app._busy = True
        async with app.run_test() as pilot:
            from textual.widgets import Input
            inp = app.query_one("#prompt", Input)
            inp.value = "hello"
            await pilot.press("enter")
            await pilot.pause()
            assert app._pending_feedback == []  # not queued in single-turn mode

    asyncio.run(run())
