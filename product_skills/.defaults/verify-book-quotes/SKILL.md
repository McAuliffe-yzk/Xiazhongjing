---
name: verify-book-quotes
description: Verify candidate quotations from the three Xiangzhongjing books against live search evidence. Use after book research and before insertion to check exact wording, speaker attribution, book identity, source quality, and whether Chinese text is an official quotation rather than an unmarked translation.
---

# 书本金句核验

## Verify

1. Match every character of the proposed quote to the supplied source evidence.
2. Distinguish the book author, narrator, quoted speaker, and subject.
3. Reject translated Chinese presented as an official Chinese-edition quote without a Chinese source.
4. Reject unattributed quote aggregators when no traceable source evidence is present.
5. Preserve the exact source URL selected by the retrieval system.

## Output Contract

Return verified, quote, attribution, book, source_index, evidence_text, reason, and confidence.

## Failure

Reject the candidate instead of rewriting or approximating it.

