import asyncio

from rtharness.config import Config
from rtharness.tools import files
from rtharness.tools.registry import ToolContext, ToolRegistry


def _reg(tmp_path):
    reg = ToolRegistry(ToolContext(config=Config(default_profile="x", profiles={}), cwd=str(tmp_path)))
    files.register(reg)
    return reg


def test_tools_registered(tmp_path):
    names = _reg(tmp_path).names()
    for n in ("read_file", "write_file", "edit_file", "patch_file"):
        assert n in names


def test_edit_file_unique_and_replace_all(tmp_path):
    reg = _reg(tmp_path)
    f = tmp_path / "a.txt"
    f.write_text("alpha beta alpha", encoding="utf-8")

    # non-unique without replace_all -> refused, file untouched
    res = asyncio.run(reg.execute("edit_file", {"path": "a.txt", "old": "alpha", "new": "X"}))
    assert "not unique" in res.content
    assert f.read_text(encoding="utf-8") == "alpha beta alpha"

    # replace_all -> both changed
    res = asyncio.run(reg.execute("edit_file", {"path": "a.txt", "old": "alpha", "new": "X", "replace_all": True}))
    assert "2 replacement" in res.content
    assert f.read_text(encoding="utf-8") == "X beta X"


def test_edit_file_not_found(tmp_path):
    reg = _reg(tmp_path)
    (tmp_path / "b.txt").write_text("hello", encoding="utf-8")
    res = asyncio.run(reg.execute("edit_file", {"path": "b.txt", "old": "nope", "new": "x"}))
    assert "not found" in res.content


def test_patch_file_multi_hunk_atomic(tmp_path):
    reg = _reg(tmp_path)
    f = tmp_path / "art.md"
    f.write_text("DIVIDER_A\nbody\nLABEL_OLD\nfooter", encoding="utf-8")
    res = asyncio.run(reg.execute("patch_file", {
        "path": "art.md",
        "hunks": [
            {"old": "DIVIDER_A", "new": "DIVIDER_B"},
            {"old": "LABEL_OLD", "new": "LABEL_NEW"},
        ],
    }))
    assert "2 hunk" in res.content
    assert f.read_text(encoding="utf-8") == "DIVIDER_B\nbody\nLABEL_NEW\nfooter"


def test_patch_file_fails_atomically(tmp_path):
    reg = _reg(tmp_path)
    f = tmp_path / "art.md"
    original = "keep_me\nchange_me"
    f.write_text(original, encoding="utf-8")
    # second hunk's 'old' is absent -> whole patch must abort, file unchanged
    res = asyncio.run(reg.execute("patch_file", {
        "path": "art.md",
        "hunks": [
            {"old": "change_me", "new": "changed"},
            {"old": "missing", "new": "x"},
        ],
    }))
    assert "hunk 2" in res.content and "no changes written" in res.content
    assert f.read_text(encoding="utf-8") == original


def test_patch_file_requires_hunks(tmp_path):
    reg = _reg(tmp_path)
    (tmp_path / "c.txt").write_text("x", encoding="utf-8")
    res = asyncio.run(reg.execute("patch_file", {"path": "c.txt", "hunks": []}))
    assert "non-empty list" in res.content
