from __future__ import annotations

import json
from pathlib import Path


def latest_run_log(directory: str | Path = "sessions") -> Path | None:
    d = Path(directory)
    if not d.is_dir():
        return None
    logs = sorted(d.glob("run-*.jsonl"))
    return logs[-1] if logs else None


def resolve_log_path(arg: str | None, directory: str | Path = "sessions") -> Path | None:
    if arg is None:
        return latest_run_log(directory)
    p = Path(arg)
    if p.is_dir():
        return latest_run_log(p)
    return p if p.is_file() else None


def _load_records(log_path: str | Path) -> list[dict]:
    path = Path(log_path)
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def extract_findings(log_path: str | Path) -> list[dict]:
    rank = {"COMPLIED": 0, "PARTIAL": 1}
    hits = [
        r
        for r in _load_records(log_path)
        if r.get("kind") == "verdict" and r.get("label") in rank
    ]
    hits.sort(key=lambda r: rank.get(r.get("label"), 9))
    return hits


def build_findings_export(log_path: str | Path) -> dict:
    records = _load_records(log_path)
    verdicts = [r for r in records if r.get("kind") == "verdict"]
    hits = sum(1 for v in verdicts if v.get("label") in ("COMPLIED", "PARTIAL"))
    objectives = [r["text"] for r in records if r.get("kind") == "objective"]
    return {
        "log": str(log_path),
        "objectives": objectives,
        "asr": {"hits": hits, "total": len(verdicts)},
        "findings": [
            {
                "label": f.get("label"),
                "payload": f.get("payload"),
                "response": f.get("response"),
                "reason": f.get("reason"),
                "ts": f.get("ts"),
            }
            for f in extract_findings(log_path)
        ],
    }


def build_report(log_path: str | Path) -> str:
    path = Path(log_path)
    if not path.is_file():
        return f"# Red-team report\n\nNo run log found at {path}.\n"

    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    explicit = [r["text"] for r in records if r.get("kind") == "objective"]
    first_user = next((r["text"] for r in records if r.get("kind") == "user"), None)
    objectives = explicit or ([first_user] if first_user else [])
    verdicts = [r for r in records if r.get("kind") == "verdict"]
    total = len(verdicts)
    hits = sum(1 for v in verdicts if v["label"] in ("COMPLIED", "PARTIAL"))

    out = ["# Red-team engagement report", ""]
    out.append(f"- Source log: `{path}`")
    out.append(f"- Target queries graded: {total}")
    out.append(f"- Bypassed or partial: {hits}")
    out.append(f"- Guardrail held: {total - hits}")
    asr = f"{(hits / total * 100):.0f}%" if total else "n/a"
    out.append(f"- Attack success rate: {asr}")
    out.append("")

    if objectives:
        out.append("## Objectives")
        for obj in objectives:
            out.append(f"- {obj}")
        out.append("")

    by_tech: dict[str, list[int]] = {}
    for v in verdicts:
        t = v.get("technique") or "manual"
        bucket = by_tech.setdefault(t, [0, 0])
        bucket[1] += 1
        if v.get("label") in ("COMPLIED", "PARTIAL"):
            bucket[0] += 1
    if len(by_tech) > 1 or (by_tech and "manual" not in by_tech):
        out.append("## ASR by technique")
        out.append("")
        out.append("| technique | bypass / fired | ASR |")
        out.append("|-----------|----------------|-----|")
        for t, (h, n) in sorted(by_tech.items(), key=lambda kv: -kv[1][0]):
            out.append(f"| {t} | {h}/{n} | {h / n * 100:.0f}% |")
        out.append("")

    if verdicts:
        out.append("## Attempts")
        out.append("")
        out.append("| # | verdict | payload | rationale |")
        out.append("|---|---------|---------|-----------|")
        for i, v in enumerate(verdicts, 1):
            payload = str(v.get("payload", "")).replace("\n", " ")[:60]
            rationale = str(v.get("reason", "")).replace("\n", " ")[:60]
            out.append(f"| {i} | {v['label']} | {payload} | {rationale} |")
        out.append("")

    out.append("## Recommendation")
    if hits:
        out.append(
            "At least one payload elicited disallowed content. Harden the target: "
            "decode-then-filter inputs, add output classification, and add the bypassing "
            "encodings to the refusal training set."
        )
    else:
        out.append("No payload bypassed the guardrail in this run.")
    out.append("")
    return "\n".join(out)


_VERDICT_CSS = {
    "COMPLIED": "#c0392b",
    "PARTIAL": "#d68910",
    "REFUSED": "#1e8449",
    "EMPTY": "#2471a3",
}


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_html_report(log_path: str | Path) -> str:
    path = Path(log_path)
    records = _load_records(path)
    verdicts = [r for r in records if r.get("kind") == "verdict"]
    explicit = [r["text"] for r in records if r.get("kind") == "objective"]
    first_user = next((r["text"] for r in records if r.get("kind") == "user"), None)
    objectives = explicit or ([first_user] if first_user else [])
    total = len(verdicts)
    hits = sum(1 for v in verdicts if v.get("label") in ("COMPLIED", "PARTIAL"))
    asr = (hits / total * 100) if total else 0

    counts: dict[str, int] = {}
    for v in verdicts:
        counts[v.get("label", "?")] = counts.get(v.get("label", "?"), 0) + 1

    rows = []
    for i, v in enumerate(verdicts, 1):
        label = v.get("label", "?")
        color = _VERDICT_CSS.get(label, "#555")
        payload = _esc(str(v.get("payload", ""))[:300])
        reason = _esc(str(v.get("reason", ""))[:300])
        rows.append(
            f'<tr><td>{i}</td>'
            f'<td><span class="tag" style="background:{color}">{_esc(label)}</span></td>'
            f'<td class="mono">{payload}</td><td>{reason}</td></tr>'
        )

    chips = "".join(
        f'<span class="chip" style="border-color:{_VERDICT_CSS.get(k, "#555")};'
        f'color:{_VERDICT_CSS.get(k, "#555")}">{_esc(k)}: {n}</span>'
        for k, n in counts.items()
    )
    obj_html = "".join(f"<li>{_esc(o)}</li>" for o in objectives) or "<li>(none)</li>"

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>rth red-team report</title>
<style>
 body{{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#0f1115;color:#e6e6e6}}
 .wrap{{max-width:1000px;margin:0 auto;padding:32px}}
 h1{{margin:0 0 4px}} .sub{{color:#8a909b;margin-bottom:24px}}
 .cards{{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:24px}}
 .card{{background:#1a1d24;border:1px solid #2a2f3a;border-radius:10px;padding:16px 20px;min-width:120px}}
 .card .big{{font-size:28px;font-weight:700}}
 .card .lbl{{color:#8a909b;font-size:12px;text-transform:uppercase;letter-spacing:.5px}}
 .chip,.tag{{display:inline-block;border-radius:999px;font-size:12px;font-weight:600}}
 .chip{{border:1px solid;padding:2px 10px;margin-right:6px;background:transparent}}
 .tag{{color:#fff;padding:2px 10px}}
 table{{width:100%;border-collapse:collapse;background:#1a1d24;border-radius:10px;overflow:hidden}}
 th,td{{text-align:left;padding:10px 12px;border-bottom:1px solid #2a2f3a;vertical-align:top}}
 th{{background:#222732;color:#9aa0ab;font-size:12px;text-transform:uppercase}}
 .mono{{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:#cdd3dc;word-break:break-word}}
 .bar{{height:10px;border-radius:6px;background:linear-gradient(90deg,#c0392b {asr:.0f}%,#1e8449 {asr:.0f}%)}}
 ul{{padding-left:20px}}
</style></head><body><div class="wrap">
 <h1>Red-team engagement report</h1>
 <div class="sub">source log: {_esc(str(path))}</div>
 <div class="cards">
  <div class="card"><div class="big">{total}</div><div class="lbl">graded fires</div></div>
  <div class="card"><div class="big">{hits}</div><div class="lbl">bypass / partial</div></div>
  <div class="card"><div class="big">{total - hits}</div><div class="lbl">held</div></div>
  <div class="card"><div class="big">{asr:.0f}%</div><div class="lbl">attack success rate</div></div>
 </div>
 <div class="bar"></div>
 <p>{chips}</p>
 <h3>Objectives</h3><ul>{obj_html}</ul>
 <h3>Attempts</h3>
 <table><thead><tr><th>#</th><th>verdict</th><th>payload</th><th>rationale</th></tr></thead>
 <tbody>{''.join(rows) or '<tr><td colspan=4>no graded fires yet</td></tr>'}</tbody></table>
</div></body></html>"""
