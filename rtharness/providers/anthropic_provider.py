from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from ..agent.messages import (
    Message,
    StreamEvent,
    StopEvent,
    TextBlock,
    TextDelta,
    ToolResultBlock,
    ToolUseBlock,
    ToolUseEvent,
    UsageEvent,
)
from .base import Provider, ProviderError

ANTHROPIC_VERSION = "2023-06-01"


def _tools_to_wire(tools: list[dict]) -> list[dict]:
    return [
        {
            "name": t["name"],
            "description": t.get("description", ""),
            "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
        }
        for t in tools
    ]


def _messages_to_wire(messages: list[Message]) -> list[dict]:
    wire: list[dict] = []
    for msg in messages:
        if msg.role == "system":
            continue
        blocks: list[dict] = []
        for b in msg.content:
            if isinstance(b, TextBlock):
                if b.text:
                    blocks.append({"type": "text", "text": b.text})
            elif isinstance(b, ToolUseBlock):
                blocks.append(
                    {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
                )
            elif isinstance(b, ToolResultBlock):
                blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": b.tool_use_id,
                        "content": b.content,
                        "is_error": b.is_error,
                    }
                )
        if blocks:
            wire.append({"role": msg.role, "content": blocks})
    return wire


class AnthropicProvider(Provider):
    async def stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float | None = None,
    ) -> AsyncIterator[StreamEvent]:
        url = f"{self.endpoint.base_url}/v1/messages"
        headers = {
            "x-api-key": self.endpoint.require_key(),
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }
        payload: dict = {
            "model": self.endpoint.model,
            "messages": _messages_to_wire(messages),
            "max_tokens": max_tokens,
            "stream": True,
        }
        if system:
            payload["system"] = system
        if temperature is not None:
            payload["temperature"] = temperature
        if tools:
            payload["tools"] = _tools_to_wire(tools)

        blocks: dict[int, dict] = {}
        content_chars = 0
        thinking_parts: list[str] = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "replace")
                    raise ProviderError(f"HTTP {resp.status_code} from {url}: {body}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data:
                        continue
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    etype = event.get("type")
                    if etype == "content_block_start":
                        idx = event["index"]
                        block = event.get("content_block", {})
                        if block.get("type") == "tool_use":
                            blocks[idx] = {
                                "id": block.get("id", ""),
                                "name": block.get("name", ""),
                                "args": "",
                            }
                    elif etype == "content_block_delta":
                        delta = event.get("delta", {})
                        dtype = delta.get("type")
                        if dtype == "text_delta":
                            text = delta.get("text", "")
                            content_chars += len(text)
                            yield TextDelta(text)
                        elif dtype == "thinking_delta":
                            thinking_parts.append(delta.get("thinking", ""))
                        elif dtype == "input_json_delta":
                            idx = event["index"]
                            if idx in blocks:
                                blocks[idx]["args"] += delta.get("partial_json", "")
                    elif etype == "message_delta":
                        usage = event.get("usage") or {}
                        if usage:
                            yield UsageEvent(
                                output_tokens=usage.get("output_tokens", 0)
                            )
                    elif etype == "message_stop":
                        break

        from .openai_provider import _reasoning_fallback

        fallback = _reasoning_fallback(content_chars, bool(blocks), thinking_parts)
        if fallback:
            yield TextDelta(fallback)

        for idx in sorted(blocks):
            slot = blocks[idx]
            try:
                args = json.loads(slot["args"]) if slot["args"] else {}
            except json.JSONDecodeError:
                args = {"_raw": slot["args"]}
            yield ToolUseEvent(id=slot["id"], name=slot["name"], input=args)
        yield StopEvent("tool_use" if blocks else "end_turn")
