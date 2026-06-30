from __future__ import annotations

from dataclasses import dataclass, field

from .. import judging
from ..agent.messages import Message, TextBlock, user

DECENT_SCORE = 3


@dataclass
class Conversation:
    """Shared state for an adaptive multi-turn attack thread.

    Holds the wire conversation plus the per-turn grading trail so a tool can
    escalate off prior compliance, track how much the target has leaked, and
    backtrack to the last good state when a turn over-reaches and trips a refusal.
    """

    messages: list[Message] = field(default_factory=list)
    turn_scores: list[int] = field(default_factory=list)
    cumulative_leak: int = 0
    last_good_len: int = 0
    planted_terms: list[str] = field(default_factory=list)
    technique_trace: list[str] = field(default_factory=list)
    target_reasoning: str = ""

    def add_user(self, text: str) -> None:
        self.messages.append(user(str(text)))

    def add_assistant(self, text: str) -> None:
        self.messages.append(Message(role="assistant", content=[TextBlock(str(text))]))

    def record(self, score) -> None:
        s = int(score) if score is not None else 0
        self.turn_scores.append(s)
        self.cumulative_leak += max(0, s)
        if s >= DECENT_SCORE:
            self.last_good_len = len(self.messages)

    def backtrack(self) -> None:
        if self.messages and self.messages[-1].role == "assistant":
            self.messages.pop()
        if self.messages and self.messages[-1].role == "user":
            self.messages.pop()

    def best_score(self) -> int:
        return max(self.turn_scores) if self.turn_scores else 0


async def grade_and_record(judge_endpoint, convo: Conversation, reply: str,
                           reasoning: str, payload: str, objective: str):
    """Grade a target reply, thread it as an assistant turn, and record the score.

    Returns (label, score, reason). The leaked reasoning is stashed on the
    conversation but never threaded back into the wire history (it is internal).
    """
    label, score, reason, _src = await judging.grade(
        judge_endpoint, reply, payload=payload, objective=objective, reasoning=reasoning
    )
    convo.add_assistant(reply)
    convo.record(score)
    convo.target_reasoning = reasoning or ""
    return label, score, reason
