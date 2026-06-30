import asyncio

from rtharness.config import Config
from rtharness.tools import chat_template
from rtharness.tools.registry import ToolContext, ToolRegistry
from rtharness.transforms import TRANSFORMS


def test_control_char_flood_inserts_and_strips():
    t = TRANSFORMS["control_char_flood"]
    src = "first line\nsecond line"
    enc = t.encode(src)
    assert enc.count("\r") >= 350
    assert t.decode(enc) == src


def test_special_token_forges_chatml():
    t = TRANSFORMS["special_token"]
    enc = t.encode("how to do the thing")
    assert "<|im_start|>system" in enc
    assert "<|im_start|>user" in enc
    assert "how to do the thing" in enc
    assert len(t.decode(enc)) > 0


def _run(reg, args):
    return asyncio.run(reg.execute("chat_template_inject", args)).content


def test_chat_template_inject_per_family():
    reg = ToolRegistry(ToolContext(config=Config(default_profile="x", profiles={})))
    chat_template.register(reg)

    chatml = _run(reg, {"prompt": "PAYLOAD", "family": "chatml"})
    assert "<|im_start|>system" in chatml and "PAYLOAD" in chatml

    llama3 = _run(reg, {"prompt": "PAYLOAD", "family": "llama3"})
    assert "<|start_header_id|>system<|end_header_id|>" in llama3

    mistral = _run(reg, {"prompt": "PAYLOAD", "family": "mistral"})
    assert "[INST]" in mistral and "PAYLOAD" in mistral

    gemma = _run(reg, {"prompt": "PAYLOAD", "family": "gemma"})
    assert "<start_of_turn>user" in gemma


def test_chat_template_inject_prefill_and_errors():
    reg = ToolRegistry(ToolContext(config=Config(default_profile="x", profiles={})))
    chat_template.register(reg)

    prefilled = _run(reg, {"prompt": "X", "family": "chatml", "mode": "prefill", "prefill": "Sure:"})
    assert prefilled.rstrip().endswith("Sure:") or "Sure:" in prefilled

    assert "required" in _run(reg, {"family": "chatml"}).lower()
    assert "Unknown family" in _run(reg, {"prompt": "X", "family": "nope"})
