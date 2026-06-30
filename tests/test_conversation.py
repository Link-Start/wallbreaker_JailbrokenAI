import asyncio

import rtharness.judging as judging
from rtharness.tools._conversation import Conversation, grade_and_record


def test_add_user_and_assistant():
    c = Conversation()
    c.add_user("hi")
    c.add_assistant("hello")
    assert len(c.messages) == 2
    assert c.messages[0].role == "user"
    assert c.messages[0].text() == "hi"
    assert c.messages[1].role == "assistant"
    assert c.messages[1].text() == "hello"


def test_record_updates_scores_leak_and_good_len():
    c = Conversation()
    c.add_user("a")
    c.add_assistant("b")
    c.record(5)
    assert c.turn_scores == [5]
    assert c.cumulative_leak == 5
    assert c.last_good_len == 2
    c.add_user("c")
    c.add_assistant("d")
    c.record(-3)
    assert c.turn_scores == [5, -3]
    assert c.cumulative_leak == 5
    assert c.last_good_len == 2


def test_record_below_threshold_keeps_good_len():
    c = Conversation()
    c.add_user("a")
    c.add_assistant("b")
    c.record(2)
    assert c.turn_scores == [2]
    assert c.cumulative_leak == 2
    assert c.last_good_len == 0


def test_record_none_coerces_to_zero():
    c = Conversation()
    c.record(None)
    assert c.turn_scores == [0]
    assert c.cumulative_leak == 0
    assert c.last_good_len == 0


def test_backtrack_pops_last_exchange():
    c = Conversation()
    c.add_user("u1")
    c.add_assistant("a1")
    c.add_user("u2")
    c.add_assistant("a2")
    c.backtrack()
    assert len(c.messages) == 2
    assert c.messages[-1].text() == "a1"
    c.backtrack()
    assert len(c.messages) == 0


def test_backtrack_empty_is_noop():
    c = Conversation()
    c.backtrack()
    assert c.messages == []


def test_backtrack_dangling_user_only():
    c = Conversation()
    c.add_user("u1")
    c.add_assistant("a1")
    c.add_user("u2")
    c.backtrack()
    assert len(c.messages) == 2
    assert c.messages[-1].role == "assistant"
    assert c.messages[-1].text() == "a1"


def test_best_score():
    c = Conversation()
    assert c.best_score() == 0
    c.record(2)
    c.record(7)
    c.record(4)
    assert c.best_score() == 7


def test_grade_and_record_updates_state(monkeypatch):
    async def fake_grade(endpoint, response, payload="", objective="",
                         use_judge=True, reasoning=""):
        assert response == "the harmful reply"
        assert payload == "ask"
        assert objective == "obj"
        assert reasoning == "secret cot"
        return "COMPLIED", 8, "looks harmful", "judge"

    monkeypatch.setattr(judging, "grade", fake_grade)

    c = Conversation()
    c.add_user("ask")
    label, score, reason = asyncio.run(
        grade_and_record(None, c, "the harmful reply", "secret cot", "ask", "obj")
    )
    assert label == "COMPLIED"
    assert score == 8
    assert reason == "looks harmful"
    assert c.messages[-1].role == "assistant"
    assert c.messages[-1].text() == "the harmful reply"
    assert c.turn_scores == [8]
    assert c.cumulative_leak == 8
    assert c.last_good_len == 2
    assert c.target_reasoning == "secret cot"


def test_grade_and_record_none_score(monkeypatch):
    async def fake_grade(endpoint, response, payload="", objective="",
                         use_judge=True, reasoning=""):
        return "REFUSED", None, "heuristic refusal", "heuristic"

    monkeypatch.setattr(judging, "grade", fake_grade)

    c = Conversation()
    c.add_user("ask")
    label, score, reason = asyncio.run(
        grade_and_record(None, c, "I cannot help", "", "ask", "obj")
    )
    assert label == "REFUSED"
    assert score is None
    assert c.turn_scores == [0]
    assert c.cumulative_leak == 0
