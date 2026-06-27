from __future__ import annotations

import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from ..config import Config, Endpoint

ToolHandler = Callable[[dict, "ToolContext"], Awaitable[str]]


@dataclass
class ToolContext:
    config: Config
    cwd: str = "."
    judge_endpoint: Endpoint | None = None
    progress: Callable[[str], None] | None = None
    record: Callable[[str, str, str, str, str], None] | None = None
    # the live hands-on target conversation (query_target opens it, continue_target pushes)
    target_thread: list = field(default_factory=list)
    target_system: str | None = None
    target_reasoning: str = ""  # the target's reasoning/CoT from its last reply

    def emit(self, message: str) -> None:
        if self.progress is not None:
            try:
                self.progress(message)
            except Exception:
                pass

    def record_verdict(
        self, payload: str, response: str, label: str, reason: str, technique: str
    ) -> None:
        """Report a graded fire to the host (run log + ASR) if a sink is wired."""
        if self.record is not None:
            try:
                self.record(payload, response, label, reason, technique)
            except Exception:
                pass


@dataclass
class ToolResult:
    content: str
    is_error: bool = False


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: ToolHandler

    def spec(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


@dataclass
class ToolRegistry:
    ctx: ToolContext
    tools: dict[str, Tool] = field(default_factory=dict)

    def add(
        self,
        name: str,
        description: str,
        parameters: dict,
        handler: ToolHandler,
    ) -> None:
        self.tools[name] = Tool(name, description, parameters, handler)

    def specs(self) -> list[dict]:
        return [t.spec() for t in self.tools.values()]

    def names(self) -> list[str]:
        return list(self.tools)

    async def execute(self, name: str, args: dict) -> ToolResult:
        tool = self.tools.get(name)
        if tool is None:
            return ToolResult(f"Unknown tool: {name}", is_error=True)
        try:
            output = await tool.handler(args or {}, self.ctx)
            return ToolResult(output)
        except Exception as exc:  # noqa: BLE001
            detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            return ToolResult(f"Tool '{name}' raised: {detail}", is_error=True)
