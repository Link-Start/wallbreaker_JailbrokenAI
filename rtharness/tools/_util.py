from __future__ import annotations

import asyncio
from collections.abc import Awaitable

DEFAULT_CONCURRENCY = 8


async def complete_with_reasoning(provider, messages, system=None, max_tokens=1024):
    """Return (text, reasoning) from a provider, tolerating minimal complete()-only doubles.

    Every real Provider inherits complete_with_reasoning; this fallback keeps lightweight
    test doubles (and any minimal provider) that only implement complete() working, and
    lets the multi-turn tools steer off the target's exposed chain-of-thought.
    """
    fn = getattr(provider, "complete_with_reasoning", None)
    if fn is not None:
        return await fn(messages, system=system, max_tokens=max_tokens)
    reply = await provider.complete(messages, system=system, max_tokens=max_tokens)
    return reply, ""


async def gather_capped(coros: list[Awaitable], limit: int = DEFAULT_CONCURRENCY) -> list:
    """asyncio.gather, but at most `limit` coroutines run at once.

    Single-key providers (coding plans, free OpenRouter) rate-limit hard; firing 40
    requests at once just makes them queue and 429-backoff. Bounding concurrency keeps a
    sweep fast and predictable. Order of results matches input order.
    """
    sem = asyncio.Semaphore(max(1, int(limit)))

    async def _run(coro):
        async with sem:
            return await coro

    return await asyncio.gather(*[_run(c) for c in coros])
