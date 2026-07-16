import json

from wallbreaker.session import RunLog, normalize_inference_records


def test_runlog_aggregates_ordered_stream_and_metadata(tmp_path):
    log = RunLog(tmp_path)
    endpoint = type("Endpoint", (), {"name": "demo", "protocol": "openai", "model": "m"})()
    log.inference_request("abc", endpoint, [{"role": "user", "content": "hello"}], system="sys", tools=[], operation="turn", parameters={"max_tokens": 3})
    log.inference_event("abc", {"type": "reasoning_delta", "text": "a"})
    log.inference_event("abc", {"type": "reasoning_delta", "text": "b"})
    log.inference_event("abc", {"type": "text_delta", "text": "c"})
    log.inference_event("abc", {"type": "text_delta", "text": "d"})
    log.inference_event("abc", {"type": "usage", "input_tokens": 1})
    log.inference_response("abc", status="ok", stop_reasons=["end"], duration_ms=12)

    rows = [json.loads(line) for line in log.path.read_text(encoding="utf-8").splitlines()]
    assert [row["kind"] for row in rows] == ["inference"]
    row = rows[0]
    assert row["stream"] == [
        {"channel": "reasoning", "text": "ab"},
        {"channel": "text", "text": "cd"},
    ]
    assert row["text"] == "cd"
    assert row["reasoning"] == "ab"
    assert row["stream_metadata"] == [{"type": "usage", "input_tokens": 1}]
    assert row["request"]["system"] == "sys"


def test_legacy_records_normalize_and_keep_source_lines():
    records = [
        {"kind": "run_meta"},
        {"kind": "inference_request", "inference_id": "x", "operation": "completion", "messages": [], "parameters": {}},
        {"kind": "inference_event", "inference_id": "x", "event": {"type": "text_delta", "text": "one"}},
        {"kind": "inference_event", "inference_id": "x", "event": {"type": "text_delta", "text": " two"}},
        {"kind": "inference_response", "inference_id": "x", "status": "ok"},
    ]
    compact = normalize_inference_records(records, [1, 4, 7, 9, 11])
    assert compact[0]["kind"] == "run_meta"
    assert compact[1]["kind"] == "inference"
    assert compact[1]["text"] == "one two"
    assert compact[1]["source_lines"] == [4, 7, 9, 11]


def test_response_fallback_does_not_duplicate_traced_stop_event(tmp_path):
    log = RunLog(tmp_path)
    endpoint = type("Endpoint", (), {"name": "demo", "protocol": "openai", "model": "m"})()
    stop = {"type": "stop", "stop_reason": "end_turn"}
    log.inference_request("abc", endpoint, [], system=None, tools=None, operation="turn", parameters={})
    log.inference_event("abc", stop)
    log.inference_response("abc", status="ok", stream_events=[stop])

    row = json.loads(log.path.read_text(encoding="utf-8"))
    assert row["stream_metadata"] == [stop]
