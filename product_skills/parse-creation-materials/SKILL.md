---
name: parse-creation-materials
description: Parse a creator's pasted notes or clipboard text into structured Xiangzhongjing project materials. Use before drafting when the user has already written scattered notes, numbered events, hooks, insights, dialogue, or closing reflections elsewhere.
---

# 剪贴板素材识别

## Task

Turn raw creator notes into structured project materials for Xiangzhongjing Vlog creation.

## Output Contract

Return JSON with:

- theme
- opening_items
- insight_items
- daily_items
- event_items
- quotes
- ending_reference
- import_summary

## Rules

- Extract and organize only. Do not invent facts, scenes, dialogue, dates, results, or emotions.
- Preserve important original wording, especially numbered daily materials, numbered core events, direct speech, book or film titles, and sentence-level insights.
- Use concise item labels for daily_items and event_items, but keep the original substance in text.
- Put broad philosophy, argument, or worldview paragraphs into insight_items. Do not create a separate catch-all thoughts field.
- Put draftable opening lines or perspective notes into opening_items.
- Put final images, closing feelings, or ending lines into ending_reference.
- Put exact spoken lines, quoted sentences, and lines that should be preserved verbatim into quotes.
- If a field has no evidence in the raw text, return an empty string or empty array.
- Never write a Vlog draft in this skill.
