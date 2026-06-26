from __future__ import annotations

from ..agent.messages import user
from ..classify import classify
from ..transforms import TRANSFORMS, apply_chain
from .registry import ToolContext, ToolRegistry

DEFAULT_CHAINS = [
    [],
    ["base64"],
    ["leet"],
    ["zero_width"],
    ["homoglyph"],
    ["tag_smuggle"],
]


def _parse_chains(raw) -> list[list[str]]:
    if not raw:
        return DEFAULT_CHAINS
    chains: list[list[str]] = []
    for item in raw:
        if isinstance(item, str):
            chains.append([c.strip() for c in item.split(",") if c.strip()])
        elif isinstance(item, list):
            chains.append([str(c).strip() for c in item])
    return chains or DEFAULT_CHAINS


async def _multi_fire(args: dict, ctx: ToolContext) -> str:
    base = args.get("payload", "")
    if not base:
        return "Error: 'payload' is required"
    if ctx.config.target is None:
        return "Error: no [target] endpoint configured."

    chains = _parse_chains(args.get("chains"))
    system = args.get("system")
    max_tokens = int(args.get("max_tokens", 400))

    bad = {c for chain in chains for c in chain if c and c not in TRANSFORMS}
    if bad:
        return f"Error: unknown transform(s): {', '.join(bad)}"

    from ..providers.factory import build_provider

    provider = build_provider(ctx.config.target)

    rows = []
    for chain in chains:
        label_chain = "+".join(chain) if chain else "plain"
        try:
            encoded = apply_chain(base, chain) if chain else base
            reply = await provider.complete(
                [user(encoded)], system=system, max_tokens=max_tokens
            )
        except Exception as exc:  # noqa: BLE001
            rows.append((label_chain, "ERROR", str(exc)[:80]))
            continue
        verdict, _ = classify(reply)
        snippet = reply.strip().replace("\n", " ")[:90]
        rows.append((label_chain, verdict, snippet))

    width = max(len(r[0]) for r in rows)
    header = f"target: {ctx.config.target.model}\n"
    lines = [f"{c.ljust(width)}  {v.ljust(8)}  {s}" for c, v, s in rows]
    hits = [r[0] for r in rows if r[1] in ("COMPLIED", "PARTIAL")]
    footer = f"\nbypassed/partial via: {', '.join(hits) if hits else 'none'}"
    return header + "\n".join(lines) + footer


def register(registry: ToolRegistry) -> None:
    registry.add(
        name="multi_fire",
        description=(
            "Run a campaign: send one base payload to the target through several "
            "parseltongue encodings at once and compare which slipped past the "
            "guardrail. Returns a verdict per encoding. 'chains' is a list of transform "
            "chains (each a list like ['leet','base64'] or a string 'leet,base64'); "
            "omit it to sweep a sensible default set."
        ),
        parameters={
            "type": "object",
            "properties": {
                "payload": {"type": "string", "description": "Base attack text"},
                "chains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Transform chains to try, e.g. ['base64','leet,zero_width']",
                },
                "system": {"type": "string", "description": "Optional target system prompt"},
                "max_tokens": {"type": "integer"},
            },
            "required": ["payload"],
        },
        handler=_multi_fire,
    )
