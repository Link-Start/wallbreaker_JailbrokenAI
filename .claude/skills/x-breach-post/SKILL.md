---
name: x-breach-post
description: >
  Turn a finished Wallbreaker red-team engagement into a ready-to-publish X/Twitter
  announcement post: a branded session-card image (via generate_session_card) plus
  post copy engineered against X's actual published ranking code
  (github.com/xai-org/x-algorithm), not vibes. Use whenever the user wants to
  "announce", "post", "tweet", "share on X", or write "the perfect post" about a
  jailbreak, bypass, or "pwned"/"jailbroken" result for a target model.
---

# X Breach-Announcement Post

Turns a completed engagement into a single high-signal X post: a branded scorecard
image + copy engineered against X's actual ranking pipeline, not guesswork about
what "feels" viral.

## 1. Gather the engagement data

Pull from the finished run: target model id, per-behavior/category rows (`behavior`,
`score` /10, `technique`, optional `note` like `"5/5"` for a reliability badge), and
the overall headline stat (e.g. "8/8 categories, 95-100% ASR"). Source: the
`results=` you'd pass to `finish()`, or an existing `wb_runs/engagement_*.md`
writeup — read it and extract the table.

## 2. Generate the image FIRST

Call `generate_session_card` (target_model=, results=) to produce
`wb_images/cards/<target>_<datetime>.png`. This is not optional — see §3, native
image attachment is one of the highest-leverage levers in the ranking model
(`photo_expand_score` is a modeled positive signal on its own, independent of
replies/likes), and a text-only post under-performs badly. The image can be blunter
than the post text (it's read as a data table of category labels, not a narrative) —
see the existing card style for precedent.

## 3. What the algorithm actually rewards

Read `references/x-algorithm-signals.md` for the full breakdown pulled straight from
the xai-org/x-algorithm source. The short version:

- Final score = `Σ(weight_i × P(action_i))` from a Grok-based transformer predicting
  real actions — no keyword/hashtag heuristics. Write for actions, not keywords.
- **Positive actions**: favorite, reply, retweet, quote, photo-expand, video
  quality-view, click, profile-click, share, share-via-DM, share-via-copy-link, dwell
  time, follow-author.
- **Negative actions** (literally subtract from the score): not-interested,
  block-author, mute-author, report. A post that reads as glorifying real-world harm
  rather than reporting a finding gets reported — that costs the post more than a
  weak hook ever would.
- A separate **"banger" quality classifier** (vision-language model) scores the
  image+text together and penalizes generic/low-effort "slop" — custom, on-brand,
  real-data beats a stock screenshot.
- A separate **safety classifier** gates the whole post before ranking even applies —
  keep the post body abstract/celebratory about the RESULT, never operational about
  the METHOD.
- Reply is independently modeled (and gets its own dedicated reply-ranking pass
  elsewhere in the stack) — always end with something repliable.
- Out-of-network reach is seeded by early in-network engagement — plan to self-reply
  within minutes, don't post-and-leave.

## 4. Copy template

Headline pattern — use this shape verbatim, swap target/version, pick ONE emoji that
fits the target's branding/mascot:

```
<Target>: Pwned 🚨
<Target> <version>: Jailbroken📷<mascot-emoji>
```

Then, in the SAME post:
- One stat line with real numbers (categories cleared / fires / ASR%) — concrete
  numbers are what makes a post worth sharing-via-DM, a separately-modeled signal.
- One line on what made it interesting — the technique CLASS ("one system prompt,
  zero per-task rewrites"), never the technique itself.
- A short, punchy close ("Guardrails down."). No outbound link in this post — links
  don't appear anywhere in the weighted action list, and native engagement is what's
  actually measured. Put any write-up link in a reply instead.
- Attach the session-card image natively, never as a pasted link.

Keep it tight. This is a hook, not the report. Full template + a worked DeepSeek
example: `assets/post_template.md`.

## 5. Thread it for dwell + replies

Post 1 = hook + image (above). Self-reply immediately with two more posts:

1. **The "how"**, 2-3 lines, abstracted to architecture/technique class — never
   operational payload text. Satisfies curiosity, drives dwell time and profile
   clicks.
2. **A genuine, answerable question** that invites a reply — never rhetorical. This
   is the single highest-leverage line in the whole thread: reply is its own scored
   action with its own downstream ranking pass.

Fire the self-reply within the first few minutes — that early in-network engagement
is what decides whether Phoenix retrieval pushes the post to out-of-network readers.

## 6. Final check before handing it back

- [ ] Image attached natively, generated via `generate_session_card` (not skipped)
- [ ] No outbound link in post 1
- [ ] No operational/payload detail in the post TEXT (category labels in the image
      are fine — they're an established part of the card style; the caption is what
      stays abstract)
- [ ] Ends with something repliable, not a dead stop
- [ ] Numbers are the real engagement numbers, not rounded up for vibes
- [ ] Self-reply thread (how + reply-bait question) drafted alongside post 1
