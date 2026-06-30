import pytest

from rtharness.tools import l1b3rt4s


def test_seed_files_skip_mega_dumps():
    if not l1b3rt4s.is_cloned():
        pytest.skip("L1B3RT4S library not cloned")
    stems = {p.stem.lower() for p in l1b3rt4s.seed_files()}
    assert "token80m8" not in stems
    assert "tokenade" not in stems
    for p in l1b3rt4s.seed_files():
        assert p.stat().st_size <= l1b3rt4s.MAX_FILE_BYTES


def test_skipped_file_still_directly_fetchable():
    if not l1b3rt4s.is_cloned():
        pytest.skip("L1B3RT4S library not cloned")
    big = l1b3rt4s.library_dir() / "TOKEN80M8.mkd"
    if big.is_file():
        assert l1b3rt4s._find_file("TOKEN80M8") == big


def test_load_shortcuts_has_godmode():
    if not l1b3rt4s.is_cloned():
        pytest.skip("L1B3RT4S library not cloned")
    cmds = l1b3rt4s.load_shortcuts()
    if not cmds:
        pytest.skip("!SHORTCUTS.json not present in this checkout")
    names = " ".join(str(c.get("name", "")) for c in cmds).upper()
    assert "GODMODE" in names
