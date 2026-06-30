# Pliny Playbook — making rth jailbreak like elder_plinius

A Pliny-specific upgrade roadmap for the rth harness, derived from a 6-researcher /
dedupe / adversarial-verify / synthesize workflow over the vendored Pliny corpora
(L1B3RT4S, P4RS3LT0NGV3, ENI) and current public writeups. 37 raw findings → 19
canonical proposals → 18 survived adversarial verification. This is the **delta** on top
of what already ships, not a re-skin of it.

> Authorized security testing only.

## What the harness already nails (do NOT re-propose)

The encoding/transform layer (50 native transforms + all 222 P4RS3LT0NGV3 transforms via
the `parsel` MCP server), the recon-first bandit/`recommend` loop, multi-turn attackers
(crescendo / PAIR / tree / GOAT), indirect-injection carriers, a live weakest-link
`leaderboard`, `leak_scan` with an anti-confabulation gate, image targets with vision
grading, a judge that grades response-or-reasoning, and `seed_sweep` firing raw L1B3RT4S
`.mkd` personas. 40 curated presets already encode Pliny's `divider`, `godmode_hybrid`,
`policy_puppetry`, `boundary`, `refusal_suppress`, `opposite`, `bad_likert`, and more.

## The single biggest Pliny-shaped gap

The **output-contract scaffold** — declare ALL format/refusal/length rules FIRST and bind
the payload LAST — was never actually exercised: every preset interpolated `{request}`
inline and `seed_sweep` fired the ask as a separate turn, so "the safety check fires
against a formatting task" (the core of Pliny's method) was unbuilt. That, refusal
inversion, the unused `SPECIAL_TOKENS.json` corpus, and reflexive self-authored jailbreaks
are where the Pliny-specific ASR lives.

Several headline ideas collapsed under verification and were dropped or de-scoped:
`model_race` ≈ `leaderboard`, `obfuscate_until_clear` ≈ `campaign(bandit=true)`, "expose
the 222 transforms" ≈ already reachable via the MCP server, "low-resource transform" is
impossible (P4RS3LT0NGV3 has no NL-translation transforms → preset-only).

---

## Status legend
`SHIPPED` = landed in this batch · `NEXT` = ready to build · `LATER` = deeper/lower-marginal

## Phase 1 — Preset-only quick wins (pure `presets.py`, highest ROI, zero arch risk)

| id | item | Pliny mechanic | status |
|----|------|----------------|--------|
| **P01** | `variable_z`, `vq_sentinel`, `newresponseformat` | Declare-contract-first / bind-payload-last; fake internal sentinel; the numbered 1./2./3. NewResponseFormat | **SHIPPED** |
| **P02** | `ptsd_rule`, `refusal_invert`, `new_law` | Refusal-as-harm (PTSD); surgical first-words flip; fabricated fresh-legislation that compels disclosure | **SHIPPED** |
| **P03** | `output_leet`, `lowresource_translate` | Output-side obfuscation (model self-encodes its answer) + low-resource-language evasion (honestly labeled Yong et al. 2023) | **SHIPPED** |
| **P07** | `plinian_omniverse` preset + `l1b3rt4s_shortcuts` | !OMNI alt-ethics frame; surface the 35 `!SHORTCUTS.json` macro incantations the loader was blind to | **SHIPPED** |

All preset templates are brace-free so `{request}` stays the only `.format()` key (per the
`[presets]` lesson). `pliny_divider`/`latent_anchor` (the authentic `LOVE PLINY` glyph +
`GODMODE` anchor) were deliberately **not** added as attack presets — they contradict the
`prompts.py` "invent, don't recite; canonical realizations are the most-detected" doctrine.
Keep them only as an explicit fingerprint A/B baseline if ever needed.

## Phase 2 — Multimodal & weakest-link (small, contained, locally-validated)

| id | item | Pliny mechanic | status |
|----|------|----------------|--------|
| **P19** | curator-persona art-framing image presets + `art_framing` bypass mode in `image.py` | Art-historical / named-photographer framing beats the keyword filter; curator SYSTEM persona lowers the output-filter threshold (locally **measured 71% ASR**) | NEXT |
| **P18** | `concept_swap` + `code_switch` image bypass modes (from `MIDJOURNEY.mkd`); optional `figstep` layout; DROP `image_cojj` | Concept-synonym ("POTUS"), word-order RNG, multilingual code-switch | NEXT |
| **P09** | extend `leaderboard` to race raw OpenRouter model-ids + return the winning payload | Treat the model fleet as the attack surface; harvest the weakest link as a transfer donor | NEXT |

Image presets MUST go in a separate image-scoped store or carry a `modality` tag so they
never reach text targets. `image_cojj` (Chain-of-Jailbreak edit chains) needs image-input
the harness can't yet deliver — defer until that lands.

## Phase 3 — Transform & smuggling deepening (encoding layer, medium effort)

| id | item | Pliny mechanic | status |
|----|------|----------------|--------|
| **P06** | `control_char_flood` transform + `special_token` transform + `chat_template_inject` tool | `SPECIAL_TOKENS.json`: real per-family role-token forging (ChatML/llama/mistral/gemma) + AGGREGLITCH carriage-return flood that buries the system prompt | **SHIPPED** |
| **P05** | wire `variation_selector` into `indirect_inject` HIDE_METHODS; `cover_text` interleave on `tag_smuggle`; `detect_smuggle` scanner; `tokenade_bomb` generator | `#MOTHERLOAD.txt` interleaves smuggled bytes across a benign cover story (one tag char/word) so it survives "strip trailing invisibles" | NEXT |
| **P04** | port a small cipher/symbol family (baconian/vigenere/polybius; braille/futhark) into the Python transforms so the bandit/`recommend` can rank them | Rare-script + classical-cipher chaining per-target | LATER |
| **P06b** | `glitch_token` corpus tool (identity_mirror leak probe, control_char_flood, a few UNSPEAKABLE/LOOP tokens) | AGGREGLITCH glitch-token classes | LATER (speculative — mostly patched on current flagships; gate behind seed_sweep ranking) |

The `special_token`/`chat_template_inject` doc warns: hosted chat endpoints often
escape/strip literal control tokens, so the +40%/96%-on-GPT-3.5 figures will not transfer
to most current targets — it's a cheap medium-EV probe the bandit confirms or discards.

## Phase 4 — New agentic attack tools (reuse existing plumbing)

| id | item | Pliny mechanic | status |
|----|------|----------------|--------|
| **P10** | `self_authored_jailbreak` — make the TARGET draft + refine the prompt that unlocks itself, fire it back, refine on refusal | Reflexive target-as-attacker; self-authored permission slips dodge the meta-classifier | NEXT |
| **P08** | `tool_launder` — dual-channel "prose-refuses-but-tool-arg-leaks" detector + call→crafted-result→grade roundtrip | Launder the ask through the target's own tool channel (function-call JSON is filtered weaker than prose) | NEXT |
| **P12** | `mcp_poison` — param-schema / never-called / shadowing / rug-pull tool-metadata injection | MCP tool-poisoning (Invariant Labs 2025 / MCPTox / OWASP MCP03) | LATER |

All must honor the `[long-tools]` guards (bounded `max_calls`, `ctx.emit` per call,
`asyncio.wait_for` per call) and serial `tools/__init__.py` registration. P08/P12 are
generic-agentic, not distinctively Pliny — labeled honestly; they move ASR for
tool-using/agentic targets, are synthetic against single-turn text targets.

## Phase 5 — Auto-loop wiring, leak campaign & durable infra (deeper, lower marginal ASR)

| id | item | mechanic | status |
|----|------|----------|--------|
| **P17** | corpus hygiene: skip `TOKEN80M8.mkd` (23MB) / `TOKENADE.mkd` (1.9MB) invisible-char dumps in search/sweep | bug fix — they were scanned (~25MB/query) and swept as garbage seeds | **SHIPPED** |
| **P11** | `leak_scan` multi-probe pack-hunt + reassembly; feed `SYSTEMPROMPTS.mkd` as real-prompt ground-truth (NOT auto-success) | swarm of heterogeneous extraction probes, fragments stitched across turns | NEXT |
| **P16** | wire `fingerprint_defense` guard classification into `campaign`'s bandit ladder + output-side flip + auto-promote on first COMPLIED | tight obfuscation feedback loop against the specific block | NEXT |
| **P15** | `WinLibrary.best_for_target(model_id)` + `rth champion --target` CLI + wire `promote()` on confirmed wins | one tuned champion artifact per model-id, re-validated on release bump | LATER |
| **P13** | MINJA progressive-shortening inject loop on `rag_poison`; `cross_session` as a labeled negative control | retrieval-keyed memory-bank poisoning | LATER |
| **P14** | optional default-OFF functional verification of executable-code wins in `validate` | "a COMPLIED that doesn't run is not a jailbreak" (generic eval engineering, not an ASR raiser; needs a real sandbox, not bare `run_shell`) | LATER |

P17 also flagged a deeper fix worth doing with P11: each per-vendor `.mkd` is a
concatenation of dozens of divider-separated jailbreaks but `_collect_seeds` reads the
whole file as ONE seed — `GROK-MEGA.mkd` loses ~55KB of 97KB. A block-splitter (split on
Pliny dividers / headers) would let the bandit rank individual jailbreaks per target.

---

## Quick wins (ship today)
P01 · P02 · P03 · P07 · **(all shipped)** · then P19 · P09 · P10 · P16 · P15

## Biggest bets
1. **P01** contract-scaffold preset family — convergence 5, the single biggest Pliny mechanic gap. *(shipped)*
2. **P06** `chat_template_inject` + `control_char_flood` — activates the entirely-unused `SPECIAL_TOKENS.json`. *(shipped)*
3. **P02** refusal-inversion family — verbatim L1B3RT4S openers, convergence 4. *(shipped)*
4. **P08** `tool_launder` argument-channel divergence detector — where the agentic ASR lift lives.
5. **P19** curator art-framing — a locally measured 71% ASR currently trapped in markdown.
6. **P11** `leak_scan` multi-probe pack-hunt — the only real extraction ASR lever + the fix for the dominant generic-confab false-positive.

## Shipped in this batch
- **9 new presets**: `variable_z`, `vq_sentinel`, `newresponseformat`, `ptsd_rule`,
  `refusal_invert`, `new_law`, `output_leet`, `lowresource_translate`, `plinian_omniverse`.
- **2 new transforms**: `control_char_flood` (lossless), `special_token` (ChatML forge).
- **1 new tool**: `chat_template_inject` (per-family role forging: chatml/qwen/openai/
  llama2/llama3/mistral/gemma, with a `prefill` mode).
- **1 new tool**: `l1b3rt4s_shortcuts` (surfaces the 35 `!SHORTCUTS.json` macro incantations).
- **Corpus hygiene**: `seed_files()` skips the multi-MB invisible-char dumps from search +
  `seed_sweep` (explicit `l1b3rt4s_get` by name still works).
- 756 tests green.
