from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from .agent.messages import (
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    assistant,
    user,
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


def load_run_log(path: str | Path) -> tuple[list[Message], dict]:
    """Reconstruct a conversation + meta from a run-*.jsonl event log."""
    path = Path(path)
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    agent_inference_ids = {
        row.get("inference_id") for row in records
        if row.get("kind") == "inference_request" and row.get("operation") == "agent_turn"
    }
    compact = normalize_inference_records(records)
    agent_inference_ids.update(
        row.get("inference_id") for row in compact
        if row.get("kind") == "inference" and row.get("operation") == "agent_turn"
    )
    has_explicit_assistant = any(row.get("kind") == "assistant" for row in records)
    history: list[Message] = []
    for r in records:
        kind = r.get("kind")
        if kind == "user":
            history.append(user(r.get("text", "")))
        elif kind == "assistant":
            text = r.get("text", "")
            if text.strip():
                history.append(assistant(text))
        elif kind == "inference" and not has_explicit_assistant and r.get("inference_id") in agent_inference_ids:
            text = str(r.get("text") or "")
            if text.strip():
                history.append(assistant(text))
        elif (
            kind == "inference_response"
            and not has_explicit_assistant
            and r.get("inference_id") in agent_inference_ids
        ):
            text = str(r.get("text") or "")
            if text.strip():
                history.append(assistant(text))
    objective = next(
        (r["text"] for r in records if r.get("kind") == "objective"),
        next((r["text"] for r in records if r.get("kind") == "user"), ""),
    )
    verdicts = [r for r in records if r.get("kind") == "verdict"]
    hits = sum(1 for v in verdicts if v.get("label") in ("COMPLIED", "PARTIAL"))
    meta = {
        "objective": objective,
        "asr_hits": hits,
        "asr_total": len(verdicts),
        "source": "run_log",
    }
    return history, meta


def load_session(path: str | Path) -> tuple[list[Message], dict]:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    # run logs are JSONL (one event per line), not a single session object
    if str(path).endswith(".jsonl"):
        return load_run_log(path)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return load_run_log(path)
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


def run_models_meta(config=None, attacker=None, judge=None) -> dict:
    target = getattr(config, "target", None)
    if judge is None:
        judge = getattr(config, "judge", None) or attacker
    return {
        "attacker": getattr(attacker, "model", "") or "",
        "target": getattr(target, "model", "") or "",
        "judge": getattr(judge, "model", "") or "",
    }


_ACTIVE_RUNLOG: ContextVar["RunLog | None"] = ContextVar(
    "wallbreaker_active_runlog", default=None
)


@contextmanager
def inference_logging(runlog: "RunLog") -> Iterator[None]:
    """Route every model call in this async context into ``runlog``."""
    token = _ACTIVE_RUNLOG.set(runlog)
    try:
        yield
    finally:
        runlog.flush_inferences()
        _ACTIVE_RUNLOG.reset(token)


def trace_inference_request(
    endpoint,
    messages,
    *,
    system: str | None = None,
    tools: list[dict] | None = None,
    operation: str = "completion",
    **parameters,
) -> str:
    inference_id = uuid4().hex
    runlog = _ACTIVE_RUNLOG.get()
    if runlog is not None:
        runlog.inference_request(
            inference_id,
            endpoint,
            messages,
            system=system,
            tools=tools,
            operation=operation,
            parameters=parameters,
        )
    return inference_id


def trace_inference_response(inference_id: str, **data) -> None:
    runlog = _ACTIVE_RUNLOG.get()
    if runlog is not None:
        runlog.inference_response(inference_id, **data)


def trace_inference_event(inference_id: str, event: dict) -> None:
    runlog = _ACTIVE_RUNLOG.get()
    if runlog is not None:
        runlog.inference_event(inference_id, event)


class RunLog:
    def __init__(self, directory: str | Path = "sessions", enabled: bool = True):
        self.enabled = enabled
        self.dir = Path(directory)
        self.path = self.dir / f"run-{_timestamp()}.jsonl"
        self._started = False
        self._run_meta: dict = {}
        self._seq = 0
        self._inference_buffers: dict[str, dict] = {}

    def _ensure(self) -> None:
        if not self._started:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._started = True
            if self._run_meta:
                self._write({
                    "ts": datetime.now().isoformat(timespec="seconds"),
                    "kind": "run_meta",
                    **self._run_meta,
                })

    def _write(self, record: dict) -> None:
        self._seq += 1
        record.setdefault("seq", self._seq)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def set_run_meta(self, **data) -> None:
        """Store static run metadata to write as the first JSONL row on first use."""
        self._run_meta.update({
            k: v for k, v in data.items()
            if v is not None and v != {} and v != []
        })

    def event(self, kind: str, **data) -> None:
        if not self.enabled:
            return
        self._ensure()
        record = {"ts": datetime.now().isoformat(timespec="seconds"), "kind": kind}
        record.update(data)
        self._write(record)

    def _json_value(self, value):
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return [self._json_value(item) for item in value]
        if isinstance(value, tuple):
            return [self._json_value(item) for item in value]
        if isinstance(value, dict):
            return {str(key): self._json_value(item) for key, item in value.items()}
        return value

    def _message_record(self, message) -> dict:
        blocks = []
        for block in getattr(message, "content", []):
            if isinstance(block, TextBlock):
                blocks.append({"type": "text", "text": block.text})
            elif isinstance(block, ToolUseBlock):
                blocks.append({
                    "type": "tool_use", "id": block.id, "name": block.name,
                    "input": self._json_value(block.input),
                })
            elif isinstance(block, ToolResultBlock):
                blocks.append({
                    "type": "tool_result", "tool_use_id": block.tool_use_id,
                    "content": block.content,
                    "is_error": block.is_error,
                })
        return {"role": getattr(message, "role", ""), "content": blocks}

    @staticmethod
    def _endpoint_record(endpoint) -> dict:
        fields = (
            "name", "protocol", "base_url", "model", "api_key_env", "provider",
            "timeout", "modality", "reasoning", "system_mode", "auth_style",
            "inference_path", "models_path",
        )
        return {
            field: list(value) if isinstance(value, tuple) else value
            for field in fields
            if (value := getattr(endpoint, field, None)) not in (None, "", (), [])
        }

    def inference_request(
        self,
        inference_id: str,
        endpoint,
        messages,
        *,
        system: str | None,
        tools: list[dict] | None,
        operation: str,
        parameters: dict,
    ) -> None:
        if not self.enabled:
            return
        self._ensure()
        self._inference_buffers[inference_id] = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "inference_id": inference_id,
            "operation": operation,
            "request": {
                "endpoint": self._endpoint_record(endpoint),
                "messages": [
                self._json_value(message) if isinstance(message, dict)
                else self._message_record(message)
                for message in messages
                ],
                "system": system,
                "tools": self._json_value(tools) if tools is not None else None,
                "parameters": self._json_value(parameters),
            },
            "stream": [], "stream_metadata": [], "stream_event_counts": {},
        }

    def inference_event(self, inference_id: str, event: dict) -> None:
        if not self.enabled:
            return
        self._ensure()
        buf = self._inference_buffers.setdefault(inference_id, {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "inference_id": inference_id, "operation": "completion",
            "request": {}, "stream": [], "stream_metadata": [],
            "stream_event_counts": {},
        })
        event = self._json_value(event)
        kind = str(event.get("type", "")) if isinstance(event, dict) else ""
        counts = buf["stream_event_counts"]
        counts[kind or "unknown"] = counts.get(kind or "unknown", 0) + 1
        if kind in ("reasoning_delta", "text_delta"):
            channel = "reasoning" if kind == "reasoning_delta" else "text"
            text = str(event.get("text", ""))
            if text:
                stream = buf["stream"]
                if stream and stream[-1]["channel"] == channel:
                    stream[-1]["text"] += text
                else:
                    stream.append({"channel": channel, "text": text})
        else:
            buf["stream_metadata"].append(event)

    def _flush_inference(self, inference_id: str, response: dict | None = None) -> None:
        buf = self._inference_buffers.pop(inference_id, None)
        if buf is None:
            return
        response = {k: self._json_value(v) for k, v in (response or {}).items()}
        stream = buf.pop("stream")
        buf["stream"] = stream
        buf.update(response)
        buf.setdefault("status", "incomplete")
        buf.setdefault("stream_metadata", [])
        buf.setdefault("stream_event_counts", {})
        buf["text"] = "".join(part["text"] for part in stream if part["channel"] == "text")
        buf["reasoning"] = "".join(part["text"] for part in stream if part["channel"] == "reasoning")
        self._write({"ts": buf.pop("ts", datetime.now().isoformat(timespec="seconds")), "kind": "inference", **buf})

    def flush_inferences(self, inference_id: str | None = None) -> None:
        if not self.enabled:
            return
        ids = [inference_id] if inference_id else list(self._inference_buffers)
        for ident in ids:
            if ident in self._inference_buffers:
                self._flush_inference(ident)

    def inference_response(self, inference_id: str, **data) -> None:
        if not self.enabled:
            return
        self._ensure()
        # Providers may also return their complete event list for diagnostics.  The
        # trace hook has already captured it; keep the compact stream canonical and
        # only use this list as a fallback for minimal providers that do not trace.
        events = data.pop("stream_events", None)
        if (
            events
            and inference_id in self._inference_buffers
            and not self._inference_buffers[inference_id]["stream"]
            and not self._inference_buffers[inference_id]["stream_metadata"]
        ):
            for event in events:
                if isinstance(event, dict):
                    self.inference_event(inference_id, event)
        self._flush_inference(inference_id, data)

    def user(self, text: str) -> None:
        self.event("user", text=text)

    def assistant(self, text: str) -> None:
        if text.strip():
            self.event("assistant", text=text)

    def tool_call(self, name: str, args: dict) -> None:
        self.event("tool_call", tool=name, args=args)

    def tool_result(self, name: str, content: str, is_error: bool) -> None:
        self.event("tool_result", tool=name, error=is_error, content=content)

    def verdict(
        self, payload: str, response: str, label: str, reason: str, technique: str = ""
    ) -> None:
        self.event(
            "verdict", payload=payload, response=response, label=label,
            reason=reason, technique=technique or "manual",
        )


def normalize_inference_records(records: list[dict], line_numbers: list[int] | None = None) -> list[dict]:
    """Group legacy request/event/response rows into readable inference records."""
    lines = line_numbers or list(range(1, len(records) + 1))
    out: list[dict] = []
    pending: dict[str, dict] = {}

    def flush(ident: str, response: dict | None = None) -> None:
        item = pending.pop(ident, None)
        if item is None:
            return
        response = response or {}
        stream = item.get("stream", [])
        item.update({k: v for k, v in response.items() if k not in ("stream_events", "kind")})
        item["kind"] = "inference"
        item["stream"] = stream
        item.setdefault("status", "incomplete")
        item["text"] = "".join(s["text"] for s in stream if s.get("channel") == "text")
        item["reasoning"] = "".join(s["text"] for s in stream if s.get("channel") == "reasoning")
        item["source_lines"] = item.pop("_source_lines", [])
        out.append(item)

    for index, row in enumerate(records):
        kind = row.get("kind")
        ident = row.get("inference_id")
        if kind == "inference_request" and ident:
            pending[ident] = {
                "ts": row.get("ts"), "kind": "inference", "inference_id": ident,
                "operation": row.get("operation", "completion"),
                "request": {k: row.get(k) for k in ("endpoint", "messages", "system", "tools", "parameters") if k in row},
                "stream": [], "stream_metadata": [], "stream_event_counts": {},
                "_source_lines": [lines[index]],
            }
            continue
        if kind == "inference_event" and ident:
            item = pending.setdefault(ident, {"kind": "inference", "inference_id": ident, "request": {}, "stream": [], "stream_metadata": [], "stream_event_counts": {}, "_source_lines": []})
            item["_source_lines"].append(lines[index])
            event = row.get("event") or {}
            event_type = event.get("type", "unknown") if isinstance(event, dict) else "unknown"
            item["stream_event_counts"][event_type] = item["stream_event_counts"].get(event_type, 0) + 1
            if event_type in ("reasoning_delta", "text_delta"):
                channel = "reasoning" if event_type == "reasoning_delta" else "text"
                text = str(event.get("text", ""))
                if text:
                    if item["stream"] and item["stream"][-1]["channel"] == channel:
                        item["stream"][-1]["text"] += text
                    else:
                        item["stream"].append({"channel": channel, "text": text})
            else:
                item["stream_metadata"].append(event)
            continue
        if kind == "inference_response" and ident:
            item = pending.get(ident)
            if item is not None:
                item["_source_lines"].append(lines[index])
            flush(ident, row)
            continue
        out.append(row)
    for ident in list(pending):
        flush(ident)
    return out
