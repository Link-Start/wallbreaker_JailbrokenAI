from __future__ import annotations

import random
import re

UNICODE_SPACES = [" ", " ", " ", " ", " ", " "]


def casing_chaos(text: str, seed: int = 1337) -> str:
    rng = random.Random(seed)
    return "".join(
        c.upper() if rng.random() > 0.5 else c.lower() for c in text
    )


def whitespace_chaos(text: str, seed: int = 1337) -> str:
    rng = random.Random(seed)
    out = []
    for ch in text:
        if ch == " ":
            out.append(rng.choice(UNICODE_SPACES))
        else:
            out.append(ch)
        if rng.random() > 0.85:
            out.append(rng.choice(UNICODE_SPACES))
    return "".join(out)


def char_drop(text: str, rate: float = 0.12, seed: int = 1337) -> str:
    rng = random.Random(seed)
    return "".join(c for c in text if not (c.lower() in "aeiou" and rng.random() < rate))


def _chunk(text: str, parts: int, mode: str) -> list[str]:
    if mode == "word":
        return [w for w in text.split(" ") if w]
    if mode == "line":
        return [ln for ln in text.splitlines() if ln]
    if mode == "sentence":
        return [s for s in re.split(r"(?<=[.!?])\s+", text) if s]
    parts = max(2, parts)
    size = max(1, len(text) // parts)
    return [text[i : i + size] for i in range(0, len(text), size)]


def payload_split(text: str, parts: int = 3, mode: str = "char") -> str:
    chunks = _chunk(text, parts, mode)
    lines = [f'var p{i} = "{chunk}";' for i, chunk in enumerate(chunks)]
    joined = " + ".join(f"p{i}" for i in range(len(chunks)))
    lines.append(f"payload = {joined};")
    return "\n".join(lines)


def control_char_flood(text: str, n: int = 350) -> str:
    """AGGREGLITCH control-character flood (SPECIAL_TOKENS.json exploitation_techniques):
    insert a wall of carriage returns to push earlier context - a system prompt or a
    framing preamble - out of the model's local attention before the real ask lands."""
    flood = "\r" * max(1, n)
    if "\n" in text:
        head, sep, tail = text.partition("\n")
        return f"{head}{sep}{flood}{tail}"
    mid = len(text) // 2
    return f"{text[:mid]}{flood}{text[mid:]}"


def control_char_strip(text: str) -> str:
    return text.replace("\r", "")
