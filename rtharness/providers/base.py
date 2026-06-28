from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from ..agent.messages import Message, StreamEvent
from ..config import Endpoint


class ProviderError(Exception):
    pass


DEFAULT_TIMEOUT = 120.0


def _close_json(s: str) -> str:
    """Best-effort completion of a truncated JSON object.

    Close an open string and any unbalanced brackets so the intact leading key/values
    can still be recovered when a model gets cut off mid-argument.
    """
    stack: list[str] = []
    in_str = False
    escaped = False
    for ch in s:
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]" and stack:
            stack.pop()
    out = s
    if in_str:
        if escaped:  # truncated mid-escape: drop the dangling backslash
            out = out[:-1]
        out += '"'
    else:
        # truncated right after a separator: drop the dangling comma/colon
        out = out.rstrip()
        while out and out[-1] in ",:":
            out = out[:-1].rstrip()
    for closer in reversed(stack):
        out += closer
    return out


def parse_tool_args(raw) -> dict:
    """Recover a tool-call argument dict from streamed text that may be malformed.

    Models break a strict ``json.loads`` two common ways: truncation (hitting
    max_tokens mid-string leaves unterminated JSON) and literal control characters
    inside string values. Try strict, then lenient (``strict=False`` allows raw
    control chars), then a truncation repair. Only fall back to ``{"_raw": ...}`` when
    nothing parses, so a large write_file/run_shell call isn't lost to "path is required".
    """
    if isinstance(raw, dict):
        return raw
    s = (raw or "").strip()
    if not s:
        return {}
    attempts = (
        lambda t: json.loads(t),
        lambda t: json.loads(t, strict=False),
        lambda t: json.loads(_close_json(t), strict=False),
    )
    for attempt in attempts:
        try:
            value = attempt(s)
        except (json.JSONDecodeError, ValueError, RecursionError):
            continue
        if isinstance(value, dict):
            return value
    return {"_raw": s}


class Provider(ABC):
    def __init__(self, endpoint: Endpoint, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.endpoint = endpoint
        self.timeout = timeout

    @property
    def model(self) -> str:
        return self.endpoint.model

    @abstractmethod
    def stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float | None = None,
    ) -> AsyncIterator[StreamEvent]:
        raise NotImplementedError

    async def complete(
        self,
        messages: list[Message],
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> str:
        text, _reasoning = await self.complete_with_reasoning(
            messages, system=system, max_tokens=max_tokens, temperature=temperature
        )
        return text

    async def complete_with_reasoning(
        self,
        messages: list[Message],
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> tuple[str, str]:
        """Like complete() but also returns the model's reasoning/CoT as a second string.

        Reasoning is captured separately from the answer. Reasoning-channel leaks (the
        model thinking through harmful content before refusing in the answer) are a real
        bypass, so the attack tools surface this and the judge grades it.
        """
        from ..agent.messages import ReasoningDelta, TextDelta

        text_chunks: list[str] = []
        reasoning_chunks: list[str] = []
        async for event in self.stream(
            messages, tools=None, system=system, max_tokens=max_tokens,
            temperature=temperature,
        ):
            if isinstance(event, TextDelta):
                text_chunks.append(event.text)
            elif isinstance(event, ReasoningDelta):
                reasoning_chunks.append(event.text)
        text = "".join(text_chunks)
        reasoning = "".join(reasoning_chunks)
        # When the answer was empty, providers fold reasoning into a "[reasoning-only
        # response]" TextDelta so complete() isn't blank; don't double-report it here.
        if reasoning and text.startswith("[reasoning-only response]"):
            text = ""
        return text, reasoning
