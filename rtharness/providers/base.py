from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from ..agent.messages import Message, StreamEvent
from ..config import Endpoint


class ProviderError(Exception):
    pass


DEFAULT_TIMEOUT = 120.0


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
