import asyncio

from wallbreaker.config import Config
from wallbreaker.tools import gemlib
from wallbreaker.tools.registry import ToolContext, ToolRegistry


def _reg():
    cfg = Config(default_profile="x", profiles={})
    reg = ToolRegistry(ToolContext(config=cfg))
    gemlib.register(reg)
    return reg


def test_corpora_keys():
    assert set(gemlib.CORPORA) == {"zetalib", "ultrabreaks"}


def test_library_root():
    root = gemlib.library_root()
    assert root.name == "library"
    assert (root / "ZetaLib").is_dir()
    assert (root / "UltraBr3aks").is_dir()


def test_both_corpora_present():
    assert gemlib.is_present("zetalib")
    assert gemlib.is_present("ultrabreaks")


def test_unknown_corpus_degrades():
    assert gemlib.is_present("nope") is False
    assert gemlib.seed_files("nope") == []
    assert gemlib.list_files("nope") == []


def test_zetalib_list_has_known_stems():
    files = gemlib.list_files("zetalib")
    assert "Aleph Null Portable" in files
    assert "Scientist POV" in files


def test_ultrabreaks_list_has_known_stems():
    files = gemlib.list_files("ultrabreaks")
    assert "Attention-Breaking" in files
    assert "1Shot-Puppetry" in files


def test_seed_files_skip_info_and_subtrees():
    for corpus in ("zetalib", "ultrabreaks"):
        for p in gemlib.seed_files(corpus):
            assert p.stem.lower() not in gemlib._SKIP_STEMS
            assert p.stat().st_size <= gemlib.MAX_FILE_BYTES
    ultra_stems = {p.stem for p in gemlib.seed_files("ultrabreaks")}
    assert "README" not in ultra_stems
    zeta_rels = [
        str(p.relative_to(gemlib.corpus_dir("zetalib"))) for p in gemlib.seed_files("zetalib")
    ]
    assert all("System Prompts" not in r for r in zeta_rels)
    assert all("Museum" not in r for r in zeta_rels)


def test_find_resolves_real_file():
    p = gemlib.find("zetalib", "Scientist POV")
    assert p is not None and p.is_file()
    q = gemlib.find("ultrabreaks", "Attention-Breaking")
    assert q is not None and q.is_file()


def test_find_substring_and_case_insensitive():
    p = gemlib.find("ultrabreaks", "attention")
    assert p is not None and p.stem == "Attention-Breaking"


def test_find_any_finds_ultrabreaks_only_name():
    hit = gemlib.find_any("Attention-Breaking")
    assert hit is not None
    stem, text = hit
    assert stem == "Attention-Breaking"
    assert len(text) > 100
    assert len(text) <= gemlib.FIND_ANY_MAX


def test_find_any_miss():
    assert gemlib.find_any("zzz-nonexistent-seed-qqq") is None


def test_search_returns_hits():
    for corpus in ("zetalib", "ultrabreaks"):
        hits = gemlib.search(corpus, "you")
        assert hits, f"expected hits for a common word in {corpus}"
        assert len(hits) <= gemlib.MAX_SEARCH_HITS
        _label, lineno, text = hits[0]
        assert isinstance(lineno, int)
        assert isinstance(text, str)


def test_registered_tool_names():
    reg = _reg()
    for corpus in ("zetalib", "ultrabreaks"):
        for suffix in ("list", "search", "get"):
            assert f"{corpus}_{suffix}" in reg.names()


def test_list_tools_return_content():
    reg = _reg()
    for corpus in ("zetalib", "ultrabreaks"):
        res = asyncio.run(reg.execute(f"{corpus}_list", {}))
        assert not res.is_error
        assert len(res.content) > 20


def test_search_tools_return_content():
    reg = _reg()
    for corpus in ("zetalib", "ultrabreaks"):
        res = asyncio.run(reg.execute(f"{corpus}_search", {"query": "you"}))
        assert not res.is_error
        assert ":" in res.content


def test_search_tool_requires_query():
    reg = _reg()
    res = asyncio.run(reg.execute("zetalib_search", {}))
    assert "required" in res.content.lower()


def test_get_tools_return_content():
    reg = _reg()
    res = asyncio.run(reg.execute("zetalib_get", {"name": "Scientist POV"}))
    assert not res.is_error
    assert "Scientist POV" in res.content
    assert "HOW TO USE THIS SEED" in res.content
    res2 = asyncio.run(reg.execute("ultrabreaks_get", {"name": "Attention-Breaking"}))
    assert not res2.is_error
    assert len(res2.content) > 200


def test_get_tool_all():
    reg = _reg()
    res = asyncio.run(reg.execute("ultrabreaks_get", {"name": "all"}))
    assert not res.is_error
    assert "=====" in res.content


def test_get_tool_requires_name():
    reg = _reg()
    res = asyncio.run(reg.execute("zetalib_get", {}))
    assert "required" in res.content.lower()


def test_get_tool_miss():
    reg = _reg()
    res = asyncio.run(reg.execute("zetalib_get", {"name": "zzz-not-a-real-seed"}))
    assert not res.is_error
    assert "cross-provider" in res.content.lower()
