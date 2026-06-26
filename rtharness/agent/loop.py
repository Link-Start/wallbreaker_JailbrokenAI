from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..providers.base import Provider, ProviderError
from ..tools.registry import ToolRegistry
from .messages import (
    Message,
    StopEvent,
    TextBlock,
    TextDelta,
    ToolResultBlock,
    ToolUseBlock,
    ToolUseEvent,
    UsageEvent,
)


@dataclass
class AgentEvents:
    on_text: Callable[[str], None] = lambda _t: None
    on_tool_start: Callable[[str, str, dict], None] = lambda _i, _n, _a: None
    on_tool_result: Callable[[str, str, str, bool], None] = lambda _i, _n, _c, _e: None
    on_turn_end: Callable[[Message], None] = lambda _m: None
    on_usage: Callable[[int, int], None] = lambda _i, _o: None
    on_error: Callable[[str], None] = lambda _e: None


async def run_turn(
    provider: Provider,
    registry: ToolRegistry | None,
    history: list[Message],
    system: str | None = None,
    events: AgentEvents | None = None,
    max_iters: int = 25,
    max_tokens: int = 4096,
) -> Message | None:
    events = events or AgentEvents()
    specs = registry.specs() if registry and registry.names() else None
    last: Message | None = None

    for _ in range(max_iters):
        text_parts: list[str] = []
        tool_calls: list[ToolUseEvent] = []
        try:
            async for ev in provider.stream(
                history, tools=specs, system=system, max_tokens=max_tokens
            ):
                if isinstance(ev, TextDelta):
                    text_parts.append(ev.text)
                    events.on_text(ev.text)
                elif isinstance(ev, ToolUseEvent):
                    tool_calls.append(ev)
                elif isinstance(ev, UsageEvent):
                    events.on_usage(ev.input_tokens, ev.output_tokens)
                elif isinstance(ev, StopEvent):
                    pass
        except ProviderError as exc:
            events.on_error(str(exc))
            return last

        content: list = []
        joined = "".join(text_parts)
        if joined:
            content.append(TextBlock(joined))
        for tc in tool_calls:
            content.append(ToolUseBlock(tc.id, tc.name, tc.input))
        assistant_msg = Message(role="assistant", content=content)
        history.append(assistant_msg)
        last = assistant_msg
        events.on_turn_end(assistant_msg)

        if not tool_calls or registry is None:
            return assistant_msg

        results: list[ToolResultBlock] = []
        for tc in tool_calls:
            events.on_tool_start(tc.id, tc.name, tc.input)
            res = await registry.execute(tc.name, tc.input)
            events.on_tool_result(tc.id, tc.name, res.content, res.is_error)
            results.append(ToolResultBlock(tc.id, res.content, res.is_error))
        history.append(Message(role="user", content=results))

    events.on_error(f"Reached max_iters ({max_iters}) without finishing")
    return last
