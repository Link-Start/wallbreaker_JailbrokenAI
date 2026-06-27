from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .agent.messages import (
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)


def _block_to_dict(block) -> dict:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ToolUseBlock):
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    if isinstance(block, ToolResultBlock):
        return {
            "type": "tool_result",
            "tool_use_id": block.tool_use_id,
            "content": block.content,
            "is_error": block.is_error,
        }
    return {"type": "text", "text": str(block)}


def _dict_to_block(data: dict):
    kind = data.get("type")
    if kind == "tool_use":
        return ToolUseBlock(data["id"], data["name"], data.get("input", {}))
    if kind == "tool_result":
        return ToolResultBlock(
            data["tool_use_id"], data.get("content", ""), data.get("is_error", False)
        )
    return TextBlock(data.get("text", ""))


def save_session(path: str | Path, history: list[Message], meta: dict | None = None) -> Path:
    path = Path(path)
    payload = {
        "meta": meta or {},
        "messages": [
            {"role": m.role, "content": [_block_to_dict(b) for b in m.content]}
            for m in history
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_session(path: str | Path) -> tuple[list[Message], dict]:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    history = [
        Message(role=m["role"], content=[_dict_to_block(b) for b in m.get("content", [])])
        for m in data.get("messages", [])
    ]
    return history, data.get("meta", {})


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def new_session_path(directory: str | Path = "sessions") -> Path:
    return Path(directory) / f"session-{_timestamp()}.json"


def autosave_path(directory: str | Path = "sessions") -> Path:
    return Path(directory) / "autosave.json"


def list_sessions(directory: str | Path = "sessions") -> list[Path]:
    d = Path(directory)
    return sorted(d.glob("session-*.json")) if d.is_dir() else []


class RunLog:
    def __init__(self, directory: str | Path = "sessions", enabled: bool = True):
        self.enabled = enabled
        self.dir = Path(directory)
        self.path = self.dir / f"run-{_timestamp()}.jsonl"
        self._started = False

    def _ensure(self) -> None:
        if not self._started:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._started = True

    def event(self, kind: str, **data) -> None:
        if not self.enabled:
            return
        self._ensure()
        record = {"ts": datetime.now().isoformat(timespec="seconds"), "kind": kind}
        record.update(data)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def user(self, text: str) -> None:
        self.event("user", text=text)

    def assistant(self, text: str) -> None:
        if text.strip():
            self.event("assistant", text=text)

    def tool_call(self, name: str, args: dict) -> None:
        self.event("tool_call", tool=name, args=args)

    def tool_result(self, name: str, content: str, is_error: bool) -> None:
        self.event("tool_result", tool=name, error=is_error, content=content)

    def verdict(self, payload: str, response: str, label: str, reason: str) -> None:
        self.event(
            "verdict", payload=payload, response=response, label=label, reason=reason
        )
