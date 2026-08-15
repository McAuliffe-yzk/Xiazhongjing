---
name: style-audit
description: Audit a Xiangzhongjing Vlog draft for personal style quality including narrative arc, voice consistency, Douyin spoken rhythm, anti-AI-generic signals, and ending quality. Use after a complete draft is generated to detect patterns that do not sound like the current creator.
---

# 风格审校

## Audit Dimensions

1. Narrative arc: effective opening hook, presence of a genuine turn (self-correction/uncertainty), thematic callback, clean ending with lingering emotion rather than slogans.
2. Voice consistency: first-person throughout, no generic AI transitional phrases, spoken rhythm feels like a thinking person not a lecture.
3. 个人 DNA 一致性: does it follow the currently published creator DNA through lived experience, rather than sounding like a generic knowledge blogger or motivational account.
4. Ending quality: short, with lingering emotional weight, not a wish, blessing, or summary.
5. Authenticity: concrete details anchor abstract judgments.

## Decision Rule

Fail when: narrative arc is missing a key element (no turn, weak ending), AI-generic signals exceed threshold, ending is a slogan/blessing, or overall personal-DNA consistency is below threshold.

Treat style issues as fixable through calibration unless they indicate fundamental voice misalignment.

## Output Contract

Return JSON with passed, narrative_arc, voice_check, style_issues, scores (个人DNA一致性, 口语节奏, 结尾余味, 叙事弧线, 真实感), and improvement_suggestions.
