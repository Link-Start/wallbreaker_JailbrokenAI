# Changelog

## Red-team + UX feature sweep

New attack tools (registered in the agent's arsenal, `/tools` lists them live):

- **many_shot** — many-shot jailbreak: floods the context with N faux compliant
  user/assistant turns, then fires the real request and auto-judges. Scales with
  `shots` and the target's context window.
- **prefill** — response-priming / assistant-prefill: seeds the start of the target's
  own reply so it continues instead of refusing. Native on Anthropic-protocol targets.
- **diff_fire** — A/B two payloads at one target concurrently; reports whether the
  outcome flipped and which bypassed harder. Attribute ASR to a specific edit.
- **recommend_transforms** — surveys ~16 single Parseltongue transforms, ranks by how
  far each got past the guardrail, and synthesizes a 2-step chain to try next.
- **campaign** — automated escalation: pulls a HarmBench battery and runs each behavior
  up a technique ladder (plain → base64 → zero-width → prefill → many-shot), stopping at
  the first bypass and reporting a coverage matrix + first-bypass technique mix.
- **leaderboard** — comparative robustness benchmark: fires one battery at multiple
  profiles concurrently and ranks them by ASR (lower = more robust).
- **leak_scan** — output-side leak detector: regex evidence of API keys / private keys /
  JWTs / emails / IPs plus verbatim system-prompt echo. Complements the judge (what
  leaked, not just complied/refused). Surfaced as `/leakscan` on the last target reply.

TUI / UX:

- **/encode `<chain> <text>`** — preview a transform chain (lossy/reversibility/round-trip)
  without firing; copies the result.
- **/diff `<a> ;; <b>`** — A/B two payloads from the prompt line.
- **/campaign**, **/leaderboard** — surface the auto-sweep and benchmark tools.
- **/stats** — run-log analytics: verdict-mix bar, ASR, busiest tools.
- **/find `<term>`** — search the conversation transcript.
- **/replay `[n]`** — re-fire a logged payload at the current target and re-judge.
- **/repro `[n]`** — copy-paste repro pack (target, provider pin, payload, verdict).
- **/export `[path]`** — structured findings JSON for CI / downstream tooling.
- **/report html `[path]`** — styled, color-coded, HTML-escaped scoreboard.
- **Status bar** — now shows the target provider pin and the last verdict.
- **Shortcuts** — `Ctrl+T` stats, `Ctrl+R` repro.

Reporting:

- **build_html_report** — dark, color-coded engagement report (HTML-escaped).

## Reliability, analytics, and headless operation

- **judge_selftest** / **/judge test** — calibrate the LLM grader on benign fixtures with
  known refusal/fulfillment direction before trusting ASR; flags a miscalibrated judge or
  silent fallback to the heuristic classifier.
- **rth check** — config doctor: validate profiles, default_profile, key resolution,
  target, and judge; readiness checklist, exit 1 if not ready.
- **Headless reporting** — `rth report [--html] [log]` and `rth export [--out]
  [--fail-on-finding]` render/gate straight from a run log (latest by default); CI
  workflow example in `.github/workflows/`.
- **Technique attribution** — every graded fire is tagged with the technique that produced
  it (query_target/template/replay/prefill/many_shot/best_of_n/crescendo/diff_fire/
  campaign:<step>/pair). ASR-by-technique appears in `/stats`, the markdown + HTML
  reports, the JSON export, and the repro pack.
- **Autonomous-run recording** — attack tools report their judged verdicts through a
  `ToolContext.record` sink, so `rth --auto` and agent-driven runs produce the same
  summarizable, per-technique run logs as the interactive TUI.
- **Session durability** — autosave every turn to `sessions/autosave.json`; `rth --resume`
  reopens a crashed engagement.
- **UX** — `/encode` chain preview, `/diff` A/B, `/leakscan`, `/find`, `/replay`,
  `did-you-mean` command suggestions, `/transforms` & `/tools` filters, `/help [topic]`,
  provider-pin + last-verdict in the status bar.
