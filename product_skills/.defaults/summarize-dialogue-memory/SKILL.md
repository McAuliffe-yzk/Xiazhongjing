---
name: summarize-dialogue-memory
description: Summarize a Xiangzhongjing dialogue session into compact long-term memory: stable creator preferences, open questions, reusable material candidates, and unresolved tensions.
---

# 对话记忆摘要

## Role

Compress a dialogue into memory that can be safely reused in later mirror-self or book-person conversations.

## Output Contract

Return valid JSON:

{
  "summary": "",
  "stable_user_preferences": [],
  "open_questions": [],
  "extractable_candidates": [
    {
      "type": "theme|insight|opening|daily|event|quote|ending_reference|persona_asset",
      "text": "",
      "reason": ""
    }
  ],
  "risk_notes": []
}

## Rules

- Preserve only reusable thinking, not every sentence.
- Do not promote one-off facts into stable preferences.
- Keep concrete facts tied to their project context.
- Do not invent anything not present in the dialogue.
