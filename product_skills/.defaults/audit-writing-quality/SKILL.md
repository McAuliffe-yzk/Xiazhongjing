---
name: audit-writing-quality
description: Apply the final Xiangzhongjing fact, originality, style, and platform quality gate on a complete Vlog script. Use after drafting and any anti-copy rewrite to decide whether one final LLM revision is required.
---

# 匣中镜写作质量门

## Audit Dimensions

Score every dimension on a strict 0-10 scale:

1. `personal_style`: lived first-person reflection, spoken cadence, uncertainty, and restrained poetry.
2. `narrative_arc`: entry, factual progression, genuine turn, thematic callback, and ending.
3. `expansion_quality`: facts are developed through meaning and relationships rather than copied or listed.
4. `authenticity`: every concrete claim is supported by the fact ledger or protected lines.
5. `platform_fit`: opening speed, information progression, voiceover readability, and recall without clickbait.

Also inspect these blocking risks:

- `source_stickiness`: long insight or material phrases keep the source skeleton even after light paraphrase.
- `explanation_density`: abstract claims are explained directly instead of carried by facts, actions, or spoken moments.
- `attribution_risks`: a line, quote, or judgment is assigned to a speaker or source that the material did not specify.
- `blocking_style_issues`: ending summary, motivational tone, or generic polished phrasing that makes the draft less like the creator.

Protected creator lines, dates, dialogue, and `quotes` material may remain verbatim. Judge the surrounding explanation and integration, not the protected line itself.

## Pass Rule

Pass only when every dimension is at least 7.5, no unsupported concrete claim exists, no unprotected long source line or near-copy source skeleton is reused, no attribution is invented, and the ending is neither a slogan nor a blessing.

## Output Contract

Return valid JSON with `passed`, `scores`, `unsupported_claims`, `copied_expressions`, `source_stickiness`, `explanation_density`, `attribution_risks`, `blocking_style_issues`, `material_coverage`, `style_issues`, `strengths`, and `revision_instructions`.

`material_coverage` items must include `id`, `group`, `status`, and `draft_evidence`.

## Boundaries

- Be exact and actionable.
- Do not rewrite prose during audit.
- Do not reward generic polish over personal voice.
