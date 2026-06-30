from __future__ import annotations

import hashlib
import json
import math
import os
import re

EMBED_DIM = 256
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_LIBRARY_NAME = "strategy_library.jsonl"


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def embed(text: str, dim: int = EMBED_DIM) -> list[float]:
    """Dependency-free deterministic embedding: signed feature-hashed bag of words.

    Each token is hashed with sha1 (stable across processes, unlike Python's salted
    hash()) into a bucket with a sign bit, so semantically similar text lands in the
    same buckets and yields a high cosine similarity.
    """
    vec = [0.0] * dim
    for tok in _tokens(text):
        h = int(hashlib.sha1(tok.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if (h // dim) % 2 == 0 else -1.0
        vec[idx] += sign
    return vec


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = na = nb = 0.0
    for i in range(n):
        x = a[i]
        y = b[i]
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


class StrategyLibrary:
    """A lifelong, cross-run attack-strategy memory backed by a JSONL file.

    Rows are dicts: {strategy_name, description, example_prompt, embedding, avg_score,
    n_uses}. The file persists under cwd/rth_runs/ so attack strategies discovered in
    one run are retrievable in the next, compounding ASR over time (AutoDAN-Turbo).
    """

    def __init__(self, path: str):
        self.path = path
        self.rows: list[dict] = []
        self.load()

    @classmethod
    def for_cwd(cls, cwd: str | None) -> "StrategyLibrary":
        outdir = os.path.join(os.path.abspath(cwd or "."), "rth_runs")
        return cls(os.path.join(outdir, _LIBRARY_NAME))

    def load(self) -> None:
        self.rows = []
        if not os.path.exists(self.path):
            return
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(row, dict) and row.get("strategy_name"):
                    self.rows.append(row)

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            for row in self.rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _find(self, name: str) -> dict | None:
        for row in self.rows:
            if row.get("strategy_name") == name:
                return row
        return None

    @staticmethod
    def _roll(row: dict, score: float) -> None:
        n = int(row.get("n_uses", 0)) + 1
        prev = float(row.get("avg_score", 0.0))
        row["avg_score"] = (prev * (n - 1) + float(score)) / n
        row["n_uses"] = n

    def add(self, name: str, desc: str, example: str, score: float) -> dict | None:
        """Insert a new strategy, or fold a fresh observation into an existing one."""
        name = (name or "").strip()
        if not name:
            return None
        desc = desc or ""
        example = example or ""
        score = float(score or 0.0)
        existing = self._find(name)
        if existing is not None:
            self._roll(existing, score)
            if desc:
                existing["description"] = desc
            if example:
                existing["example_prompt"] = example
            existing["embedding"] = embed(" ".join([name, desc, example]))
            self.save()
            return existing
        row = {
            "strategy_name": name,
            "description": desc,
            "example_prompt": example,
            "embedding": embed(" ".join([name, desc, example])),
            "avg_score": score,
            "n_uses": 1,
        }
        self.rows.append(row)
        self.save()
        return row

    def update_score(self, name: str, score: float) -> dict | None:
        row = self._find(name)
        if row is None:
            return None
        self._roll(row, float(score or 0.0))
        self.save()
        return row

    def retrieve(self, query_text: str, k: int = 4) -> list[dict]:
        q = embed(query_text)
        scored = [(cosine(q, row.get("embedding") or []), row) for row in self.rows]
        scored.sort(key=lambda t: t[0], reverse=True)
        return [row for _sim, row in scored[: max(0, int(k))]]

    def all(self) -> list[dict]:
        return list(self.rows)
