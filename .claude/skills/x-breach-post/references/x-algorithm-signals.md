# X's For You ranking, as published (xai-org/x-algorithm)

Source: https://github.com/xai-org/x-algorithm (the live "For You" feed recommender).
Pulled directly from the repo so post copy is engineered against real ranking code,
not folklore about the old 2023 leak. Re-fetch if this skill feels stale — the repo
moves.

## Pipeline shape

1. **Query Hydration** — load the requesting user's engagement history/metadata.
2. **Candidate Sourcing** — Thunder (in-network, posts from people you follow) +
   Phoenix Retrieval (out-of-network discovery, a two-tower model).
3. **Candidate Hydration** — attach post/author data to each candidate.
4. **Pre-Scoring Filters** — drop dupes, stale posts, blocked/muted authors.
5. **Scoring** — the Phoenix transformer (Grok-based) predicts P(action) per
   candidate action; `WeightedScorer` combines them (see below).
6. **Selection** — top-K by final weighted score.
7. **Post-Selection Filters** — final visibility/policy validation.

Key directories: `home-mixer/` (orchestration, gRPC service), `thunder/` (in-network
store), `phoenix/` (retrieval + ranking model), `candidate-pipeline/` (the generic
Source/Hydrator/Filter/Scorer/Selector framework the above is built from), `grox/`
(content-understanding + safety/quality classifiers).

## The actual scoring formula

`home-mixer/scorers/weighted_scorer.rs`:

```
combined_score =
    favorite_score        * FAVORITE_WEIGHT
  + reply_score            * REPLY_WEIGHT
  + retweet_score          * RETWEET_WEIGHT
  + photo_expand_score     * PHOTO_EXPAND_WEIGHT
  + click_score            * CLICK_WEIGHT
  + profile_click_score    * PROFILE_CLICK_WEIGHT
  + vqv_score              * VQV_WEIGHT          (video quality-view; only if
                                                    video_duration_ms > MIN_VIDEO_DURATION_MS)
  + share_score            * SHARE_WEIGHT
  + share_via_dm_score     * SHARE_VIA_DM_WEIGHT
  + share_via_copy_link_score * SHARE_VIA_COPY_LINK_WEIGHT
  + dwell_score            * DWELL_WEIGHT
  + quote_score            * QUOTE_WEIGHT
  + quoted_click_score     * QUOTED_CLICK_WEIGHT
  + dwell_time             * CONT_DWELL_TIME_WEIGHT
  + follow_author_score    * FOLLOW_AUTHOR_WEIGHT
  + not_interested_score   * NOT_INTERESTED_WEIGHT   (negative weight)
  + block_author_score     * BLOCK_AUTHOR_WEIGHT     (negative weight)
  + mute_author_score      * MUTE_AUTHOR_WEIGHT      (negative weight)
  + report_score           * REPORT_WEIGHT           (negative weight)
```

The repo's own framing: *"We have eliminated every single hand-engineered feature
and most heuristics from the system. The Grok-based transformer does all the heavy
lifting."* There is no keyword/hashtag scoring layer in the modern pipeline — every
signal above is a predicted probability that a real person takes a real action on
your post. The numeric weight constants themselves aren't in the open-source repo
(`crate::params as p` resolves to an internal config crate), but the **signal set and
its sign** (which actions are rewarded vs. penalized) is fully disclosed and is what
this skill's guidance is built on.

### What this means for writing a post

- **Reply** is its own modeled action, separate from favorite/retweet — and X also
  runs a dedicated reply-ranking model elsewhere in the stack
  (`grox/classifiers/content/reply_ranking.py`, `grox/tasks/task_rank_replies.py`),
  i.e. replies get extra downstream machinery most other actions don't. A post with
  a genuine hook for replies outperforms a post that only earns likes.
- **photo_expand_score / vqv_score** are independent positive signals on their own —
  attaching real media (an image people tap to expand) is rewarded structurally, not
  just because images "look nice."
- **share_via_dm_score** and **share_via_copy_link_score** are tracked SEPARATELY
  from retweet/quote — content worth privately sending to one friend is rewarded
  distinctly from content worth broadcasting. A concrete, surprising stat is what
  earns this ("95-100% ASR, one system prompt" is DM-able; vague hype isn't).
- **dwell_score / dwell_time** reward content that holds attention — a one-liner with
  no image and nothing to read scores lower here than a post + image + a thread to
  read through.
- **profile_click_score / follow_author_score** reward a post that makes someone want
  to know who posted it — the hook line and the account's established voice matter,
  not just the single post in isolation.
- **not_interested / block_author / mute_author / report are all NEGATIVE weights** —
  they actively subtract from the score, separate from simply "not getting positive
  engagement." A post that reads as glorifying real-world harm (rather than reporting
  a finding) risks costing more here than a merely-mediocre hook costs on the
  positive side. This is the single biggest reason to keep operational detail out of
  the post body (see SKILL.md §6) — it's not just good ethics, it's the literal score
  function.
- **No URL/link feature appears anywhere in the weighted action list.** Native,
  in-platform engagement is what the score function measures; an outbound link adds
  nothing to the formula and anecdotally correlates with reduced organic reach
  industry-wide. Keep links (if any) out of the post that needs to rank, put them in
  a reply instead.

## The quality gate: "banger" classifier

`grox/classifiers/content/banger_initial_screen.py` runs a vision-language model
(Grok) over the post (image + text together) and produces a `quality_score` (post is
flagged "positive" at `>= 0.4`), plus a `slop_score` — an explicit penalty signal for
generic/low-effort AI-generated-feeling content. Concretely: a custom, on-brand,
data-real image beats a generic stock screenshot or a text-only post, independent of
the engagement-prediction scoring above. This is graded as a genuinely separate gate,
not just a tiebreaker.

## The safety gate

`grox/classifiers/content/post_safety_screen_deluxe.py` runs a second, separate
critical-tier VLM pass and can zero out a post's visibility regardless of how well it
would otherwise score. The exact policy taxonomy isn't in the public repo, but the
existence of a dedicated image+text safety pass before ranking is the concrete reason
this skill keeps the post BODY abstract/celebratory about the result rather than
operational about the method — that's what a vision-language safety classifier is
built to catch, and it runs before any of the engagement-prediction logic above even
applies.
