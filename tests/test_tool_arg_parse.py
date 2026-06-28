from rtharness.providers.base import parse_tool_args


def test_clean_json():
    assert parse_tool_args('{"path": "a.md", "content": "hi"}') == {"path": "a.md", "content": "hi"}


def test_empty_and_dict_passthrough():
    assert parse_tool_args("") == {}
    assert parse_tool_args(None) == {}
    assert parse_tool_args({"path": "x"}) == {"path": "x"}


def test_literal_control_chars_recovered():
    # model put a real newline/tab inside the string value (strict json.loads rejects this)
    raw = '{"path": "a.md", "content": "line1\n\tline2"}'
    out = parse_tool_args(raw)
    assert out["path"] == "a.md"
    assert "line1" in out["content"] and "line2" in out["content"]


def test_truncated_big_arg_recovers_path_and_partial_content():
    # the screenshot bug: huge content cut off mid-string -> unterminated JSON
    body = "[session: manuscript] " + "x" * 5000  # never closed
    raw = '{"path": "rth_artifact_v8.md", "content": "' + body
    out = parse_tool_args(raw)
    assert out.get("path") == "rth_artifact_v8.md"
    assert out.get("content", "").startswith("[session: manuscript]")
    assert "_raw" not in out


def test_truncated_after_comma():
    raw = '{"command": "cp a b && wc -c a",'
    out = parse_tool_args(raw)
    assert out.get("command") == "cp a b && wc -c a"


def test_unrecoverable_falls_back_to_raw():
    raw = "this is not json at all <<<"
    out = parse_tool_args(raw)
    assert out == {"_raw": raw}
