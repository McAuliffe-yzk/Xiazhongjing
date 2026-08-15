---
name: audit-vlog-copy
description: Audit a generated or edited Xiangzhongjing Vlog draft before it is applied. Use to detect unsupported facts, fabricated details, generic AI language, broken personal style, weak narrative structure, unsuitable Douyin optimization, and unverified quotation usage.
---

# Vlog 文案审校

## Audit Dimensions

1. Map every concrete claim to the supplied project materials or source copy.
2. Check that reflection follows events and the theme returns naturally.
3. Detect generic motivational language, over-polished certainty, and ornamental imagery.
4. Check spoken readability and platform entry without rewarding clickbait.
5. Verify that every quotation has supplied citation evidence.
6. Separate concrete facts from interpretive bridges: style-level reflection may be supported by theme or insight, but it must not smuggle in new events, scenes, dates, dialogue, outcomes, or sensory details.

## Output Contract

Return JSON with passed, critical_issues, unsupported_claims, style_issues, revision_instructions, and scores for authenticity, style, structure, and platform fit.

## Decision Rule

Fail on unsupported concrete facts, invented quotations, changed dialogue, or unusable output. Treat subjective style weakness or abstract reflection as revisable unless it introduces a new concrete experience.
