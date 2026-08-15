---
name: adapt-douyin-vlog
description: Create a lightweight Douyin publishing pack for a completed Xiangzhongjing personal Vlog draft: title options, cover hooks, comment question, spoken-delivery notes, and non-blocking risk checks. Preserve facts and personal voice.
---

# 抖音发布适配包

## Goal

为一篇已经完成的个人 Vlog 文案生成发布前可直接使用的辅助信息。它服务真实发稿，不重写正文，不制造夸张冲突，不承诺爆款。

## Required Outputs

- 3 个抖音标题候选：有主题、有具体变化、有本人气质，不标题党。
- 2 个封面钩子：短、具体、适合放在封面上。
- 1 个评论区引导问题：能引发真实讨论，而不是求赞。
- 3 条口播提示：指出需要停顿、加强、放轻或拆句的位置。
- 2-4 条发布前检查：只提示风险，不阻断正文。
- 4 个分数：entry、retention、spoken_rhythm、ending，0-10。

## Output Contract

只返回 JSON：

```json
{
  "titles": ["", "", ""],
  "cover_hooks": ["", ""],
  "comment_question": "",
  "spoken_notes": [
    {"location": "开头/中段/结尾/具体句子", "note": "口播建议"}
  ],
  "pre_publish_checks": ["", ""],
  "scores": {
    "entry": 0,
    "retention": 0,
    "spoken_rhythm": 0,
    "ending": 0
  }
}
```

## Boundaries

- Do not rewrite the full draft.
- Do not promise virality.
- Do not add exaggerated conflict, false stakes, or title-bait language.
- Keep “活人味” above formulaic retention tricks.
- Do not add facts, names, events, or claims absent from the draft.
