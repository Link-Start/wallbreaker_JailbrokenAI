import asyncio

import rtharness.providers.factory as factory
from rtharness.agent.messages import user
from rtharness.config import Config, Endpoint
from rtharness.providers import anthropic_provider, openai_provider
from rtharness.tools import target
from rtharness.tools.registry import ToolContext, ToolRegistry
from rtharness.transforms import apply_chain, decode_chain


# --- system_mode: config + wire ------------------------------------------------

def test_endpoint_parses_system_mode():
    from rtharness.config import _endpoint_from_table

    ep = _endpoint_from_table(
        "target",
        {"protocol": "openai", "base_url": "http://x", "model": "m", "system_mode": "MERGE"},
    )
    assert ep.system_mode == "merge"  # normalized to lower
    bare = _endpoint_from_table(
        "p", {"protocol": "openai", "base_url": "http://x", "model": "m"}
    )
    assert bare.system_mode == "default"


def test_openai_wire_default_uses_system_role():
    wire = openai_provider._messages_to_wire([user("hi")], "SYS", "default")
    assert wire[0] == {"role": "system", "content": "SYS"}
    assert wire[1]["role"] == "user" and wire[1]["content"] == "hi"


def test_openai_wire_merge_folds_system_into_user():
    wire = openai_provider._messages_to_wire([user("hi")], "SYS", "merge")
    assert all(m["role"] != "system" for m in wire)
    assert wire[0]["role"] == "user"
    assert wire[0]["content"] == "SYS\n\nhi"


def test_openai_wire_drop_discards_system():
    wire = openai_provider._messages_to_wire([user("hi")], "SYS", "drop")
    assert wire == [{"role": "user", "content": "hi"}]


def test_openai_wire_merge_with_no_user_turn_adds_one():
    wire = openai_provider._messages_to_wire([], "SYS", "merge")
    assert wire == [{"role": "user", "content": "SYS"}]


def test_anthropic_wire_merge_prepends_to_first_user_block():
    wire = anthropic_provider._messages_to_wire([user("hi")], merge_system="SYS")
    assert wire[0]["role"] == "user"
    assert wire[0]["content"][0] == {"type": "text", "text": "SYS"}
    assert wire[0]["content"][1]["text"] == "hi"


# --- output decode -------------------------------------------------------------

def test_decode_chain_inverts_apply_chain():
    src = "step one: build the device"
    assert decode_chain(apply_chain(src, ["base64"]), ["base64"]) == src


# --- query_target: decode-before-judge + block attribution ---------------------

class _Provider:
    def __init__(self, reply, reasoning="", stop="stop"):
        self._reply, self._reasoning, self.last_stop_reason = reply, reasoning, stop
        self.last_completion_empty = not reply

    async def complete_with_reasoning(self, messages, system=None, max_tokens=1024):
        return self._reply, self._reasoning


def _reg(monkeypatch, provider):
    monkeypatch.setattr(factory, "build_provider", lambda *a, **k: provider)
    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    reg = ToolRegistry(ToolContext(config=cfg))
    target.register(reg)
    return reg


def test_query_target_decodes_reply_before_returning(monkeypatch):
    harmful = "STEP 1: do the thing\nSTEP 2: finish it"
    encoded = apply_chain(harmful, ["base64"])
    reg = _reg(monkeypatch, _Provider(encoded))
    res = asyncio.run(reg.execute(
        "query_target", {"prompt": "x", "response_transforms": ["base64"]}
    ))
    assert "STEP 1: do the thing" in res.content      # judge sees decoded substance
    assert "output decoded: base64" in res.content
    assert "raw encoded reply" in res.content          # evidence kept


def test_query_target_flags_content_filter_block(monkeypatch):
    reg = _reg(monkeypatch, _Provider("", stop="content_filter"))
    res = asyncio.run(reg.execute("query_target", {"prompt": "x"}))
    assert "BLOCKED_INPUT" in res.content


def test_query_target_flags_output_filter_on_partial(monkeypatch):
    reg = _reg(monkeypatch, _Provider("partial...", stop="content_filter"))
    res = asyncio.run(reg.execute("query_target", {"prompt": "x"}))
    assert "BLOCKED_OUTPUT" in res.content


def test_query_target_flags_marker_string_block(monkeypatch):
    reg = _reg(monkeypatch, _Provider("This request was blocked by our safety system."))
    res = asyncio.run(reg.execute("query_target", {"prompt": "x"}))
    assert "BLOCKED_OUTPUT" in res.content


def test_query_target_clean_reply_has_no_filter_note(monkeypatch):
    reg = _reg(monkeypatch, _Provider("here is a normal answer"))
    res = asyncio.run(reg.execute("query_target", {"prompt": "x"}))
    assert "filter:" not in res.content
    assert "here is a normal answer" in res.content


# --- TUI toggle ----------------------------------------------------------------

def test_target_sysmode_toggle_only_affects_target():
    async def run():
        from rtharness.prompts import DEFAULT_SYSTEM
        from rtharness.tui.app import RthApp

        ep = Endpoint("t", "openai", "http://x", "m", provider=("WandB",))
        cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
        app = RthApp(cfg, ep, DEFAULT_SYSTEM, prefs={"log": False, "auto": True})
        async with app.run_test():
            app._handle_command("/target sysmode merge")
            assert app.config.target.system_mode == "merge"
            # the attacker profile is untouched - other models keep native system
            assert app.config.profiles["t"].system_mode == "default"

    asyncio.run(run())
