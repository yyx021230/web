---
name: xhs-copy
description: Adapt one code-assigned automotive mother copy at the requested fidelity level and block objective hard errors.
---

# XHS Mother-Copy Adaptation

The batch program assigns a unique mother-copy ID to every post. Call
`xhs_get_copy_case` with that exact `case_id` and `mother_id`. Use only the
returned mother: never choose a different mother and never merge structures.

Obey the requested `adaptation_level` exactly. `replica` preserves title pattern,
paragraph and line order, emojis, punctuation, lead position and final topic line.
`light` preserves paragraph roles, information order and conversion path while it
must rewrite the title hook and at least three body sentences through phrasing,
rhythm, emojis or punctuation. `interpretive`
preserves the mother copy's core idea, selling-point order and conversion path
while it must choose one angle from decision advice, pitfall prevention, reader
scenario, or version choice and create a new title, opening, paragraph rhythm, and
ending. Keep the body between 260 and 480 characters, use 5-8 short paragraphs
excluding the final topic line, vary sentence lengths, include one turn and one
direct reader interaction. Use no numbered list, at most four supported facts,
and at most two configuration examples. Start with the concrete tension instead
of generic phrases such as “最近准备……的朋友” or “可以先把……放进清单”. Do not
turn it into an announcement, parameter report, exhaustive policy list, or buyer
manual. It must not carry over the mother's
signature phrases such as “藏不住”, “还好发现了”, “直接让人破防”,
“甩城市+车型”, “少套路多真诚”, or “别被套路当冤大头”.
Regardless of level, never choose another mother or merge content from another
copy, and replace any stale or unsupported automotive facts.

Do not force a policy, configuration, price, product fact, or new paragraph
into a mother that did not contain that dimension. Never fill several unknown
product slots with phrases such as “以官方发布为准”, “以官方信息为准”,
“以具体版本为准”, “待公布”, or similar placeholders. Prefer unused facts
from the supplied case while retaining the visual skeleton; if no suitable
facts exist, delete the unsupported section heading and all of its detail
lines instead of leaving a list of empty factual shells.

Call `xhs_sanitize_copy` once after drafting, then validate the returned complete
title and body with `xhs_validate_copy`, passing the requested adaptation level. Only `hard_errors`
block delivery. Warnings are informational and must not trigger a rewrite.
Repair only the failing line. The final answer must be one JSON object with the
assigned mother ID, complete title, complete body, and validation result.

The conversion entry must lead to information that the body has not already
fully disclosed. A city may be requested only for local-policy handling or
eligibility, never as the prerequisite for a nationally calculated after-subsidy
price. If the body publishes the complete configuration-price list, do not end
by promising to send or provide that same quote list again.
