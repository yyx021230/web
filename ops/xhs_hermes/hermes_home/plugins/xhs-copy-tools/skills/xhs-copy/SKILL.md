---
name: xhs-copy
description: Minimally adapt one code-assigned automotive mother copy and block only objective hard errors.
---

# XHS Mother-Copy Adaptation

The batch program assigns a unique mother-copy ID to every post. Call
`xhs_get_copy_case` with that exact `case_id` and `mother_id`. Use only the
returned mother: never choose a different mother and never merge structures.

Preserve the mother's title pattern, paragraph order, line order, emojis,
punctuation, lead-capture position, and final topic line. Replace only its old
brand/model, stale time/event, explicit banned terms, and factual slots that
conflict with the supplied policy.

Do not force a policy, configuration, price, product fact, or new paragraph
into a mother that did not contain that dimension. Never fill several unknown
product slots with phrases such as “以官方发布为准”, “以官方信息为准”,
“以具体版本为准”, “待公布”, or similar placeholders. Prefer unused facts
from the supplied case while retaining the visual skeleton; if no suitable
facts exist, delete the unsupported section heading and all of its detail
lines instead of leaving a list of empty factual shells.

Call `xhs_sanitize_copy` once after drafting, then validate the returned complete
title and body with `xhs_validate_copy`. Only `hard_errors`
block delivery. Warnings are informational and must not trigger a rewrite.
Repair only the failing line. The final answer must be one JSON object with the
assigned mother ID, complete title, complete body, and validation result.
