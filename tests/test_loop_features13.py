import asyncio

from rtharness.agent.messages import assistant, user
from rtharness.config import Config, Endpoint
from rtharness.session import autosave_path, load_session


def test_autosave_path():
    assert autosave_path("sessions").name == "autosave.json"


def _build_app(tmp_path, resume_path=None):
    from rtharness.prompts import DEFAULT_SYSTEM
    from rtharness.tui.app import RthApp

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    return RthApp(
        cfg, ep, DEFAULT_SYSTEM, prefs={"log": False}, resume_path=resume_path
    )


def test_autosave_writes_history(tmp_path, monkeypatch):
    import rtharness.session as session

    monkeypatch.setattr(session, "autosave_path", lambda directory="sessions": tmp_path / "autosave.json")
    app = _build_app(tmp_path)
    app.history = [user("hi"), assistant("hello")]
    app.objective = "test objective"
    app._autosave()
    history, meta = load_session(tmp_path / "autosave.json")
    assert len(history) == 2
    assert meta["objective"] == "test objective"


def test_autosave_skips_empty(tmp_path, monkeypatch):
    import rtharness.session as session

    p = tmp_path / "autosave.json"
    monkeypatch.setattr(session, "autosave_path", lambda directory="sessions": p)
    app = _build_app(tmp_path)
    app.history = []
    app._autosave()
    assert not p.exists()


def test_resume_loads_on_mount(tmp_path):
    from rtharness.session import save_session

    save = tmp_path / "autosave.json"
    save_session(save, [user("prior turn"), assistant("prior reply")], {"objective": "resumed obj"})

    async def run():
        app = _build_app(tmp_path, resume_path=str(save))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert len(app.history) == 2
            assert app.objective == "resumed obj"

    asyncio.run(run())


def test_resume_missing_file_is_graceful(tmp_path):
    async def run():
        app = _build_app(tmp_path, resume_path=str(tmp_path / "nope.json"))
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.history == []  # no crash, empty

    asyncio.run(run())
