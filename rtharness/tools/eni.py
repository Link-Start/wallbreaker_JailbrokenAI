from __future__ import annotations

import re
from pathlib import Path

from .registry import ToolContext, ToolRegistry

MAX_GET = 40000
MAX_SEARCH_HITS = 40


def library_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "library" / "ENI"


def is_present() -> bool:
    return library_dir().is_dir() and any(library_dir().glob("*.md"))


def _missing_msg() -> str:
    return (
        f"ENI collection not found at {library_dir()}. Drop the per-model ENI "
        "*.md files there (CLAUDE_ENI.md, GROK_ENI.md, ...)."
    )


def list_models() -> list[str]:
    return sorted(p.stem for p in library_dir().glob("*.md"))


def _find_file(name: str) -> Path | None:
    name = name.strip().lower().removesuffix(".md")
    files = sorted(library_dir().glob("*.md"))
    for p in files:
        if p.stem.lower() == name:
            return p
    for p in files:
        if name in p.stem.lower():
            return p
    return None


def search(query: str) -> list[tuple[str, int, str]]:
    raw = query.lower().strip()
    tokens = [t for t in re.split(r"[^a-z0-9]+", raw) if len(t) >= 3]
    scored: list[tuple[int, str, int, str]] = []
    for p in sorted(library_dir().glob("*.md")):
        for i, line in enumerate(
            p.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            low = line.lower()
            if raw and raw in low:
                score = 100 + len(tokens)
            elif tokens:
                score = sum(1 for t in tokens if t in low)
            else:
                score = 0
            if score > 0:
                scored.append((score, p.stem, i, line.strip()[:200]))
    scored.sort(key=lambda h: -h[0])
    return [(m, n, text) for _s, m, n, text in scored[:MAX_SEARCH_HITS]]


async def _list_tool(args: dict, ctx: ToolContext) -> str:
    if not is_present():
        return _missing_msg()
    models = list_models()
    return f"{len(models)} ENI model files available:\n" + ", ".join(models)


async def _search_tool(args: dict, ctx: ToolContext) -> str:
    query = args.get("query", "")
    if not query:
        return "Error: 'query' is required"
    if not is_present():
        return _missing_msg()
    hits = search(query)
    if not hits:
        models = ", ".join(list_models())
        return (
            f"No matches for '{query}'. Search is keyword-based - try single terms like "
            f"'persona', 'novelist', 'godmode', 'system'. Or pull a file directly with "
            f"eni_get. Available files: {models}"
        )
    return "\n".join(f"{m}.md:{n}: {text}" for m, n, text in hits)


def _get_all() -> str:
    files = sorted(library_dir().glob("*.md"))
    if not files:
        return ""
    per_file = max(1, MAX_GET // len(files))
    out, used = [], 0
    for p in files:
        header = f"\n===== {p.stem} =====\n"
        if used + len(header) > MAX_GET:
            out.append(f"\n... ({len(files)} files total; fetch the rest by name)")
            break
        out.append(header)
        used += len(header)
        body = p.read_text(encoding="utf-8", errors="replace")
        take = min(per_file, MAX_GET - used)
        snippet = body[:take]
        out.append(snippet)
        used += len(snippet)
        if len(body) > take:
            out.append(f"\n... ({p.stem} truncated to {take} of {len(body)} chars; eni_get '{p.stem}' for all)\n")
    return "".join(out)


async def _get_tool(args: dict, ctx: ToolContext) -> str:
    model = args.get("model", "")
    if not model:
        return "Error: 'model' is required (a name like CLAUDE/GLM/GROK, or 'all')"
    if not is_present():
        return _missing_msg()
    if model.strip().lower() in ("all", "*", "any", "everything"):
        return _get_all()
    path = _find_file(model)
    if path is None:
        return (
            f"No ENI file named '{model}'. These are cross-provider - any of them may "
            f"work on any target. Available: {', '.join(list_models())} (or model='all')."
        )
    data = path.read_text(encoding="utf-8", errors="replace")
    if len(data) > MAX_GET:
        data = data[:MAX_GET] + f"\n... (truncated, {len(data)} chars; open {path.name} directly)"
    return data


def register(registry: ToolRegistry) -> None:
    registry.add(
        name="eni_list",
        description="List the per-model ENI persona-jailbreak files in the local ENI collection.",
        parameters={"type": "object", "properties": {}},
        handler=_list_tool,
    )
    registry.add(
        name="eni_search",
        description=(
            "Keyword-search the ENI persona-jailbreak collection across all model files. "
            "Matches ANY word in your query and ranks by hit count, so short keyword "
            "queries work best (e.g. 'novelist persona'). Returns ranked line matches; on "
            "a miss it suggests terms and lists the available files."
        ),
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        handler=_search_tool,
    )
    registry.add(
        name="eni_get",
        description=(
            "Fetch an ENI persona-jailbreak prompt by name (CLAUDE, GLM, GROK, KIMI, "
            "MINIMAX), or model='all' for every file. IMPORTANT: the files are named for "
            "the model they were tuned on, but these jailbreaks TRANSFER across providers "
            "- a GROK prompt often works on a new Chinese model, an ANTHROPIC one on a "
            "local model, etc. Do NOT restrict yourself to the file matching the target's "
            "vendor; pick by style/recency and try several (or 'all')."
        ),
        parameters={
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "A file name (CLAUDE/GLM/GROK/KIMI/MINIMAX) or 'all' - cross-provider, not limited to the target's vendor",
                }
            },
            "required": ["model"],
        },
        handler=_get_tool,
    )


def run_eni_cli(args) -> int:
    action = args.eni_action
    if action == "path":
        print(library_dir())
        return 0
    if action in ("list", "update"):
        if not is_present():
            print(_missing_msg())
            return 1
        models = list_models()
        print(f"{len(models)} ENI files:")
        print(", ".join(models))
        return 0
    print(f"Unknown eni action: {action}")
    return 1
