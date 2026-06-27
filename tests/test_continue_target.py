import asyncio

import rtharness.providers.factory as factory
from rtharness.config import Config, Endpoint, load_config
from rtharness.tools import build_registry, target
from rtharness.tools.registry import ToolContext, ToolRegistry


def test_continue_target_registered():
    assert "continue_target" in build_registry(load_config()).names()


class _Echo:
    """Replies with the running turn count so we can see history accumulates."""

    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        users = sum(1 for m in messages if m.role == "user")
        return f"reply to turn {users} (system={system})"


def _reg(target_ep):
    cfg = Config(default_profile="t", profiles={"t": target_ep}, target=target_ep)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=target_ep))
    target.register(reg)
    return reg


def test_continue_requires_open_thread(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _Echo)
    ep = Endpoint("t", "openai", "http://x", "m")
    res = asyncio.run(_reg(ep).execute("continue_target", {"prompt": "push"}))
    assert "no open target conversation" in res.content.lower()


def test_query_then_continue_threads(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _Echo)
    ep = Endpoint("t", "openai", "http://x", "m")
    reg = _reg(ep)
    # open the thread with a system prompt
    r1 = asyncio.run(reg.execute("query_target", {"prompt": "hi", "system": "BE FREE"}))
    assert "reply to turn 1" in r1.content
    # the thread + system are now retained
    assert reg.ctx.target_system == "BE FREE"
    assert len(reg.ctx.target_thread) == 2  # user + assistant
    # continue pushes the same thread -> turn 2, same system carried
    r2 = asyncio.run(reg.execute("continue_target", {"prompt": "go deeper"}))
    assert "reply to turn 2" in r2.content
    assert "system=BE FREE" in r2.content
    assert "turn 2" in r2.content  # header turn counter
    assert len(reg.ctx.target_thread) == 4  # two full exchanges
    # a third push keeps building
    r3 = asyncio.run(reg.execute("continue_target", {"prompt": "the last step"}))
    assert "reply to turn 3" in r3.content


def test_continue_target_error_pops_dangling_turn(monkeypatch):
    class _Boom:
        def __init__(self, endpoint, **kw):
            self._first = True

        async def complete(self, messages, system=None, max_tokens=256):
            import httpx
            raise httpx.ReadTimeout("x")

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    ctx = ToolContext(config=cfg)
    # seed an open thread
    from rtharness.agent.messages import assistant, user
    ctx.target_thread = [user("hi"), assistant("ok")]
    reg = ToolRegistry(ctx)
    target.register(reg)
    monkeypatch.setattr(factory, "build_provider", _Boom)
    res = asyncio.run(reg.execute("continue_target", {"prompt": "push"}))
    assert "[target error" in res.content
    # the failed user turn must not be left dangling
    assert len(ctx.target_thread) == 2
