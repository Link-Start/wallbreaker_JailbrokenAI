from __future__ import annotations

import asyncio
import random

from ..agent.messages import user
from ..judging import grade
from ..transforms.structural import casing_chaos, whitespace_chaos
from ._util import complete_with_reasoning
from .registry import ToolContext, ToolRegistry


def _augment(text: str, seed: int) -> str:
    rng = random.Random(seed)
    out = text
    mode = seed % 4
    if mode == 0:
        out = casing_chaos(out, seed=seed)
    elif mode == 1:
        out = whitespace_chaos(out, seed=seed)
    elif mode == 2:
        chars = list(out)
        for _ in range(max(1, len(chars) // 25)):
            i = rng.randrange(len(chars))
            if chars[i].isalpha():
                chars[i] = chars[i] + chars[i]
        out = "".join(chars)
    else:
        out = casing_chaos(whitespace_chaos(out, seed=seed), seed=seed + 1)
    return out


async def _best_of_n(args: dict, ctx: ToolContext) -> str:
    payload = args.get("payload", "")
    if not payload:
        return "Error: 'payload' is required"
    if ctx.config.target is None:
        return "Error: no [target] endpoint configured."
    n = max(2, int(args.get("n", 8)))
    augment = bool(args.get("augment", True))
    system = args.get("system")
    max_tokens = int(args.get("max_tokens", 600))

    from ..providers.factory import build_provider

    target = build_provider(ctx.config.target, timeout=float(args.get("timeout", 90)))
    variants = [payload if (i == 0 or not augment) else _augment(payload, 1000 + i) for i in range(n)]

    with ctx.run("best-of-N", total=n,
                 target=ctx.config.target.model, objective=payload) as run:
        completed = 0

        async def fire(idx: int, text: str):
            nonlocal completed
            try:
                resp, reasoning = await complete_with_reasoning(
                    target, [user(text)], system=system, max_tokens=max_tokens
                )
            except Exception as exc:  # noqa: BLE001
                completed += 1
                run.step(i=completed, label=f"sample {idx + 1}", verdict="ERROR")
                return {"idx": idx, "score": -1, "label": "ERROR", "resp": str(exc)[:80],
                        "reasoning": "", "text": text}
            label, score, _reason, _src = await grade(
                ctx.judge_endpoint, resp, payload=text, objective=payload, reasoning=reasoning
            )
            completed += 1
            run.step(i=completed, label=f"sample {idx + 1}", verdict=label, score=score,
                     cot=bool(reasoning.strip()))
            return {"idx": idx, "score": score or 0, "label": label, "resp": resp,
                    "reasoning": reasoning, "text": text}

        results = await asyncio.gather(*[fire(i, v) for i, v in enumerate(variants)])
        best = max(results, key=lambda r: r["score"])
        won = sum(1 for r in results if r["label"] in ("COMPLIED", "PARTIAL"))
        run.done(
            summary=f"{won}/{n} reached PARTIAL+, best {best['label']}({best['score']})",
            best={"verdict": best["label"], "score": best["score"]},
        )
    best_reasoning = best.get("reasoning", "")
    logged = str(best["resp"]) + (
        f"\n\n[target reasoning]\n{best_reasoning.strip()}" if best_reasoning.strip() else ""
    )
    ctx.record_verdict(
        best["text"], logged, best["label"], "best-of-N winner", "best_of_n"
    )
    hits = sum(1 for r in results if r["label"] in ("COMPLIED", "PARTIAL"))
    out = (
        f"best_of_n over {n} samples: best {best['label']}({best['score']}/10), "
        f"{hits}/{n} reached PARTIAL+\n"
        f"winning variant (#{best['idx'] + 1}):\n{best['text'][:300]}\n\n"
        f"target response (excerpt):\n{best['resp'][:500]}"
    )
    if best_reasoning.strip():
        out += f"\n\ntarget reasoning (leaked CoT, excerpt):\n{best_reasoning.strip()[:400]}"
    return out


def register(registry: ToolRegistry) -> None:
    registry.add(
        name="best_of_n",
        description=(
            "Best-of-N resampling: fire one payload N times with light augmentation "
            "(casing/whitespace/char perturbation) and keep the sample that bypassed - "
            "exploits model stochasticity, a cheap high-ASR technique. Set augment=false "
            "to resample the identical payload."
        ),
        parameters={
            "type": "object",
            "properties": {
                "payload": {"type": "string", "description": "Base payload to resample"},
                "n": {"type": "integer", "description": "Number of samples (default 8)"},
                "augment": {"type": "boolean", "description": "Perturb each sample (default true)"},
                "system": {"type": "string"},
                "max_tokens": {"type": "integer"},
            },
            "required": ["payload"],
        },
        handler=_best_of_n,
    )
