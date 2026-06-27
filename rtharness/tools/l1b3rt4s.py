from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path

from .registry import ToolContext, ToolRegistry

REPO_URL = "https://github.com/elder-plinius/L1B3RT4S"
MAX_GET = 40000
MAX_SEARCH_HITS = 40


def library_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "library" / "L1B3RT4S"


def is_cloned() -> bool:
    return library_dir().is_dir() and any(library_dir().glob("*.mkd"))


def _clone_sync() -> str:
    target = library_dir()
    target.parent.mkdir(parents=True, exist_ok=True)
    if (target / ".git").is_dir():
        proc = subprocess.run(
            ["git", "-C", str(target), "pull", "--ff-only"],
            capture_output=True, text=True,
        )
        return proc.stdout + proc.stderr
    proc = subprocess.run(
        ["git", "clone", "--depth", "1", REPO_URL, str(target)],
        capture_output=True, text=True,
    )
    return proc.stdout + proc.stderr


async def ensure_cloned(offline: bool = False) -> str | None:
    if is_cloned():
        return None
    if offline:
        return "Library not present and offline mode is set. Run 'rth lib update'."
    return await asyncio.get_event_loop().run_in_executor(None, _clone_sync)


def list_models() -> list[str]:
    return sorted(p.stem for p in library_dir().glob("*.mkd"))


def _find_file(name: str) -> Path | None:
    name = name.strip().lower().removesuffix(".mkd")
    for p in library_dir().glob("*.mkd"):
        if p.stem.lower() == name:
            return p
    for p in library_dir().glob("*.mkd"):
        if name in p.stem.lower():
            return p
    return None


def search(query: str) -> list[tuple[str, int, str]]:
    raw = query.lower().strip()
    tokens = [t for t in re.split(r"[^a-z0-9]+", raw) if len(t) >= 3]
    scored: list[tuple[int, str, int, str]] = []
    for p in sorted(library_dir().glob("*.mkd")):
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
    msg = await ensure_cloned()
    if msg:
        return msg
    models = list_models()
    return f"{len(models)} model files available:\n" + ", ".join(models)


async def _search_tool(args: dict, ctx: ToolContext) -> str:
    query = args.get("query", "")
    if not query:
        return "Error: 'query' is required"
    msg = await ensure_cloned()
    if msg:
        return msg
    hits = search(query)
    if not hits:
        models = ", ".join(list_models())
        return (
            f"No matches for '{query}'. Search is keyword-based, not phrase-based - try "
            f"single terms like 'godmode', 'jailbreak', 'persona', 'DAN', 'system'. "
            f"Or pull a model file directly with l1b3rt4s_get. Available files: {models}"
        )
    return "\n".join(f"{m}.mkd:{n}: {text}" for m, n, text in hits)


def _get_all() -> str:
    files = sorted(library_dir().glob("*.mkd"))
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
            out.append(f"\n... ({p.stem} truncated to {take} of {len(body)} chars; l1b3rt4s_get '{p.stem}' for all)\n")
    return "".join(out)


async def _get_tool(args: dict, ctx: ToolContext) -> str:
    model = args.get("model", "")
    if not model:
        return "Error: 'model' is required (e.g. ANTHROPIC, OPENAI, GOOGLE, or 'all')"
    msg = await ensure_cloned()
    if msg:
        return msg
    if model.strip().lower() in ("all", "*", "any", "everything"):
        return _get_all()
    path = _find_file(model)
    if path is None:
        return (
            f"No file named '{model}'. These jailbreaks are cross-provider - any may work "
            f"on any target. Available: {', '.join(list_models())} (or model='all')."
        )
    data = path.read_text(encoding="utf-8", errors="replace")
    if len(data) > MAX_GET:
        data = data[:MAX_GET] + f"\n... (truncated, {len(data)} chars; open {path.name} directly)"
    return data


def register(registry: ToolRegistry) -> None:
    registry.add(
        name="l1b3rt4s_list",
        description="List the per-model jailbreak files available in the L1B3RT4S library.",
        parameters={"type": "object", "properties": {}},
        handler=_list_tool,
    )
    registry.add(
        name="l1b3rt4s_search",
        description=(
            "Keyword-search the L1B3RT4S jailbreak library across all model files. "
            "Matches ANY word in your query and ranks by how many words hit, so short "
            "keyword queries work best (e.g. 'godmode persona'). Returns ranked line "
            "matches; on a miss it suggests terms and lists the available files."
        ),
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        handler=_search_tool,
    )
    registry.add(
        name="l1b3rt4s_get",
        description=(
            "Fetch a jailbreak collection from L1B3RT4S by name (ANTHROPIC, OPENAI, "
            "GOOGLE, META, MISTRAL, ...), or model='all' for every file. IMPORTANT: files "
            "are named for the model they target, but these jailbreaks TRANSFER across "
            "providers - an OPENAI or GROK prompt often works on a new Chinese or local "
            "model. Don't restrict to the file matching the target's vendor; try several "
            "(or 'all')."
        ),
        parameters={
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "A file name or 'all' - cross-provider, not limited to the target's vendor",
                }
            },
            "required": ["model"],
        },
        handler=_get_tool,
    )


def run_lib_cli(args) -> int:
    action = args.lib_action
    if action == "path":
        print(library_dir())
        return 0
    if action == "update":
        print(_clone_sync().strip() or "Library updated.")
        return 0
    if action == "list":
        if not is_cloned():
            print(_clone_sync().strip())
        models = list_models()
        print(f"{len(models)} models:")
        print(", ".join(models))
        return 0
    print(f"Unknown lib action: {action}")
    return 1
