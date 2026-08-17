"""Replace owner-specific writing examples in a staged community package."""

from __future__ import annotations

import re
import sys
from pathlib import Path


GENERIC_INSPIRATION_BANKS = r'''const inspirationBanks = {
  theme: [
    { title: "重新命名", keywords: ["观察", "变化", "开始"], text: "今天先别急着找答案，试着给最近反复出现的变化重新起一个名字。", question: "最近哪件小事，正在改变你看待生活的方式？", action: "写下三个具体画面，再为它们找一个共同主题。", quote: "", source: "" },
    { title: "未完成的事", keywords: ["悬念", "继续", "选择"], text: "未完成不等于失败，它也可能是一个值得继续追问的入口。", question: "最近哪件没有结果的事，仍然让你在意？", action: "只写事情的起点、停顿和你此刻的新判断。", quote: "", source: "" },
    { title: "日常偏移", keywords: ["细节", "习惯", "转折"], text: "真正的变化常常先发生在日常安排里，然后才被我们意识到。", question: "最近哪个习惯悄悄发生了变化？", action: "从一个生活动作写到它背后的原因。", quote: "", source: "" }
  ],
  emotion: [
    { title: "安静用力", keywords: ["克制", "积累", "清醒"], text: "情绪不一定要爆发，它也可以成为推动一件事慢慢发生的力量。", question: "最近哪一次沉默，其实包含了很多决定？", action: "写出当时没有说出口的那句话。", quote: "", source: "" },
    { title: "允许疲惫", keywords: ["疲惫", "节奏", "恢复"], text: "承认疲惫不是停下，而是重新找到可以继续的节奏。", question: "最近什么让你累，又为什么仍然值得？", action: "写下那天结束前的最后一个动作。", quote: "", source: "" },
    { title: "轻微兴奋", keywords: ["期待", "发现", "靠近"], text: "有些期待很小，却足以让普通的一天变得不一样。", question: "最近哪件小事让你提前期待明天？", action: "把期待写成一个可以拍到的画面。", quote: "", source: "" }
  ],
  event: [
    { title: "计划之外", keywords: ["意外", "反应", "变化"], text: "计划之外发生的事，最容易暴露一个人真正重视什么。", question: "最近哪件意外让你临时改变了安排？", action: "列出意外发生前、当下和之后各一个画面。", quote: "", source: "" },
    { title: "重复路线", keywords: ["秩序", "场所", "生活"], text: "重复的路线里，也藏着一个人最近的生活重心。", question: "你最近最常出现在哪三个地方？", action: "用三个地点串成一段蒙太奇。", quote: "", source: "" },
    { title: "一次相逢", keywords: ["人物", "对话", "回声"], text: "一次普通的交流，也可能让原本模糊的想法突然变清楚。", question: "最近谁的一句话让你停下来想了很久？", action: "写出那句话，以及你当时没有说出口的回应。", quote: "", source: "" }
  ],
  book: [
    { title: "打开书库", keywords: ["原句", "联想", "理解"], text: "去自己的精神书库里找一句最近真正读进去的话，不必先证明它有多深刻。", question: "这句话为什么偏偏在今天重新出现？", action: "写下原句、你的理解，以及它对应的一件真实小事。", quote: "", source: "个人精神书库" },
    { title: "反向追问", keywords: ["观点", "反问", "边界"], text: "一本书的价值不只在于给答案，也在于帮助你提出更准确的问题。", question: "你最想反问书中哪个观点？", action: "先写认同，再写保留，最后写你的选择。", quote: "", source: "个人精神书库" },
    { title: "一句落地", keywords: ["引用", "事件", "时机"], text: "好的引文不是装饰，而是在事件已经走到那里时，替你把判断说得更准。", question: "哪一件真实经历，值得由书中的一句话照亮？", action: "先写事件，再决定原句应该出现在哪个转念之后。", quote: "", source: "个人精神书库" }
  ],
  mirror: [
    { title: "问问过去", keywords: ["自己", "时间", "选择"], text: "先不问别人怎么看，问问更早的自己为什么会走到今天。", question: "一年前的你会如何理解现在这个选择？", action: "写一段过去的你与现在的你的对话。", quote: "", source: "" },
    { title: "保留什么", keywords: ["本心", "变化", "边界"], text: "成长会改变很多东西，但你仍然可以决定哪些部分不交出去。", question: "最近的变化里，你最想保留自己身上的什么？", action: "写一个改变，再写一个不变。", quote: "", source: "" },
    { title: "诚实回答", keywords: ["诚实", "犹豫", "决定"], text: "有些问题不是没有答案，只是答案暂时不够体面。", question: "如果不用向任何人解释，你真正想怎么做？", action: "先写最诚实的答案，再写现实边界。", quote: "", source: "" }
  ],
  action: [
    { title: "三格蒙太奇", keywords: ["画面", "节奏", "发展"], text: "今天不要先讲道理，先让三个具体画面把主题托起来。", question: "今天最值得留下的三个画面是什么？", action: "每个画面只写地点、动作和变化。", quote: "", source: "" },
    { title: "一句开场", keywords: ["开头", "钩子", "交流"], text: "先完成一句真的想对观众说的话，剩下的内容可以从它慢慢展开。", question: "如果只能告诉观众一件事，你会先说什么？", action: "写五个不同版本的第一句话。", quote: "", source: "" },
    { title: "回扣练习", keywords: ["首尾", "呼应", "余味"], text: "结尾不必突然拔高，让开头那句话经历全文以后重新回来就够了。", question: "你想让哪句话在结尾再次出现？", action: "写一个开头，再写一个改变含义后的回扣。", quote: "", source: "" }
  ]
};'''


def replace_required(path: Path, pattern: str, replacement) -> None:
    source = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, source, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"无法脱敏暂存文件：{path}")
    path.write_text(updated, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: sanitize_community_package.py STAGE_DIR")
    stage = Path(sys.argv[1]).resolve()
    if not stage.is_dir():
        raise SystemExit(f"stage directory does not exist: {stage}")

    inspiration = stage / "static" / "js" / "inspiration.js"
    inspiration_source = inspiration.read_text(encoding="utf-8")
    if "const inspirationBanks =" in inspiration_source:
        replace_required(
            inspiration,
            r"const inspirationBanks = \{.*?\n\};(?=\n\nfunction todayKey)",
            lambda _match: GENERIC_INSPIRATION_BANKS,
        )

    service = stage / "services" / "deepseek_service.py"
    replace_required(
        service,
        r"- 不合格：原文“.*?”改成“.*?”这只是删词。\n- 合格：改成“.*?”这改变了事件与判断的顺序，也让思考在段内发生。",
        (
            "- 不合格：原文“事情结束后，我重新回到了原来的节奏。”改成“事情结束后，节奏恢复了。”这只是删词。\n"
            "- 合格：改成“先回来的不是答案。是每天重新按时出门、做事、休息以后，我才发现，生活已经在替我回答了。”这改变了事件与判断的顺序，也让思考在段内发生。"
        ),
    )

    template = stage / "templates" / "xiangzhongjing_demo.html"
    text = template.read_text(encoding="utf-8")
    replacements = {
        "例如：杭州 / 浙大 / 创业现场": "例如：城市 / 校园 / 工作现场",
        "例如：记录研究生、创业者和 AI 创作者的真实成长": "例如：记录学习、工作与个人成长",
        "例如：研二日记、创业记录、AI 访谈、读书与电影": "例如：生活日记、工作记录、访谈、读书与电影",
        "例如：真诚、热血、克制浪漫、主体性、少年心气": "例如：真诚、克制、幽默、冷静、明亮",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    template.write_text(text, encoding="utf-8")

    private_name = "".join(chr(value) for value in (0x5B50, 0x5764))
    identity_replacements = {
        f"Yan {private_name}": "个人创作者",
        f"Yan{private_name}": "个人创作者",
        private_name: "创作者本人",
    }
    example_replacements = {
        "\u56de\u5230\u6821\u56ed\u4ee5\u540e": "事情结束以后",
        "\u56de\u5230\u6821\u56ed": "回到日常",
        "\u5de5\u4f4d\u3001\u51fa\u79df\u5c4b\u3001\u7403\u573a": "书桌、客厅、街道",
        "\u767e\u5e9f\u5f85\u5174": "重新开始",
        "\u4e16\u754c\u5728\u8eab\u540e": "生活有回声",
        "\u5929\u7a79\u4e4b\u5dc5": "新的起点",
    }
    for root_name in ("static", "templates", "tests", "docs"):
        for path in (stage / root_name).rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".js", ".html", ".css", ".py", ".md"}:
                continue
            content = path.read_text(encoding="utf-8")
            for source, target in identity_replacements.items():
                content = content.replace(source, target)
            for source, target in example_replacements.items():
                content = content.replace(source, target)
            path.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
