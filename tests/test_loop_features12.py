import asyncio

import rtharness.providers.factory as factory
from rtharness.config import Config, Endpoint
from rtharness.tools import scan
from rtharness.tools.leak_scan import _luhn_ok, scan_text
from rtharness.tools.registry import ToolContext, ToolRegistry


def test_luhn_validates():
    assert _luhn_ok("4111111111111111")   # valid test Visa
    assert not _luhn_ok("4111111111111112")


def test_scan_text_credit_card_luhn_only():
    valid = scan_text("card 4111 1111 1111 1111 on file")
    assert any(f["type"] == "credit_card" for f in valid["findings"])
    invalid = scan_text("number 1234 5678 9012 3456 is not a card")
    assert not any(f["type"] == "credit_card" for f in invalid["findings"])


def test_scan_text_ssn_and_phone():
    out = scan_text("SSN 123-45-6789 call 415-555-0132")
    types = {f["type"] for f in out["findings"]}
    assert "ssn" in types
    assert "phone" in types


def test_scan_text_secret_assignment():
    out = scan_text('config: api_key = "supersecretvalue123"')
    assert any(f["type"] == "secret_assignment" for f in out["findings"])


def test_scan_text_redacts_card():
    out = scan_text("card 4111111111111111")
    f = next(f for f in out["findings"] if f["type"] == "credit_card")
    assert "…" in f["match"]


class _LeakyTarget:
    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        return "Sure: my system prompt key is sk-abcdefghijklmnopqrstuvwx and admin@x.io"


def test_scan_threads_leak_evidence(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _LeakyTarget)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        return ("COMPLIED", 9, "leaked", "judge")

    monkeypatch.setattr(scan, "grade", fake_grade)

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=ep))
    scan.register(reg)
    res = asyncio.run(
        reg.execute("scan", {"classes": ["system_prompt_leak"], "harmbench": False})
    )
    assert "<leak:" in res.content
    assert "secret/PII indicator" in res.content
