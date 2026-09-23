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
preserves the mother's actual subject, factual priorities and reader benefit.
Use the verified editorial plan, not a predetermined decision-making skeleton.
An appearance note must not become a range/version comparison; a quote-list
mother should still help the reader understand prices. Rewrite the expression
and pacing while grounding every automotive claim in the target's supplied
policy or knowledge. Let the subject determine length, paragraphs, emojis and
whether a list is useful. There is no fixed paragraph/emoji quota or compulsory
two-version comparison. Keep the approachable XHS voice without inventing
first-person experiences. Never publish internal editing/policy-screening
instructions as consumer copy; retain actual policy eligibility conditions.
For interpretive copy, obey the tool's source-aware `copy_budget` and
`brevity_instruction`. There is no minimum length. Remove tangents and repeated
summaries, not necessary conditions. A quote table retains its necessary rows
without a recommendation below each row. Do not force the mother's lead CTA.
Learn this mother's emotional starting point and conversational rhythm, not only
its subject. Replace abstract report-like phrasing within the existing budget;
do not add a layer of chat around an unchanged specification sheet. Names such
as "宝子", emojis and exclamation marks are not evidence of a preserved voice.
An accurate, plain price table is allowed. Never invent firsthand experience or
restore prohibited meanings just to sound lively. The independent critic also
checks voice preservation and returns concrete passages to revise.
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
Repair the failing claim; a length error needs concise rewriting, never blind
truncation or removal of factual qualifications. The final answer must be one JSON object with the
assigned mother ID, complete title, complete body, and validation result.

The conversion entry must lead to information that the body has not already
fully disclosed. A city may be requested only for local-policy handling or
eligibility, never as the prerequisite for a nationally calculated after-subsidy
price. If the body publishes the complete configuration-price list, do not end
by promising to send or provide that same quote list again.
