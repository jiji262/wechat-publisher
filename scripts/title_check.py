#!/usr/bin/env python3
"""标题候选检查：长度、具体对象、模板词、否定对照和夸张动词。只给编辑提示，不阻断发布。"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass

import zh_rules as R

CJK = re.compile(r"[\u3400-\u9fff]")
LATIN_OR_DIGIT = re.compile(r"[A-Za-z][A-Za-z0-9.+#_-]*|\d")
EMOJI = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
COLON = re.compile(r"[：:]")
EXCLAIM = re.compile(r"[！!]")
BOOK_MARKS = re.compile(r"[《》]")
QUOTES = re.compile(r"[“”\"]")
NUMBER_TEMPLATE = re.compile(r"^\s*(?:\d+|[一二三四五六七八九十]+)\s*(?:个|种|条|件|步|层|类|大|招|点)")
SUSPENSE_LEFT = {"真相", "重点", "关键", "答案", "秘密", "本质", "核心", "原因", "结论"}

CLICKBAIT = (
    "一文读懂", "一文搞懂", "一文看懂", "保姆级", "深度解析", "终极指南", "必看", "必读",
    "干货", "建议收藏", "万字长文", "全网首发", "重磅", "震惊", "揭秘", "底层逻辑",
    "认知升级", "认知觉醒", "天花板", "封神", "炸裂", "王炸", "绝了", "yyds",
    "你还在", "别再", "居然", "竟然", "99%", "所有人都", "看完这篇", "原来",
)
DRAMA = (
    "收编", "开口第一句", "开口就说", "杀疯", "血洗", "暴打", "硬刚", "炸了", "翻车",
    "地震", "核弹", "悄悄", "终于", "彻底",
)


@dataclass(frozen=True)
class Issue:
    level: str
    code: str
    message: str

    def as_dict(self) -> dict:
        return {"level": self.level, "code": self.code, "message": self.message}


def _width(text: str) -> float:
    """显示宽度估算：汉字算 1，ASCII 和标点算 0.5。"""
    return sum(1.0 if CJK.match(ch) else 0.5 for ch in text)


def _length_issues(han: int, width: float, min_han: int, max_han: int) -> list[Issue]:
    if han > max_han or width > max_han + 4:
        return [Issue("warn", "long", f"标题偏长（汉字 {han}，显示宽度 {width:.1f}）：信息流里容易被截断，把对象和判断放到前 16 个字内")]
    if han < min_han and width < min_han:
        return [Issue("warn", "short", f"标题偏短（汉字 {han}，显示宽度 {width:.1f}）：确认读者能看出技术对象和结论")]
    return []


def _template_issues(title: str) -> list[Issue]:
    issues = []
    if EMOJI.search(title):
        issues.append(Issue("warn", "emoji", "标题里有表情符号；技术文章标题不使用表情符号"))
    if EXCLAIM.search(title):
        issues.append(Issue("warn", "exclaim", "标题里有叹号；把情绪换成具体结果"))
    if BOOK_MARKS.search(title):
        issues.append(Issue("warn", "book_marks", "标题里有书名号；只有引用书名或原文时才使用"))
    if QUOTES.search(title):
        issues.append(Issue("warn", "quotes", "标题里有引号；只有引用真实报错或原文时才使用"))
    if NUMBER_TEMPLATE.search(title):
        issues.append(Issue("warn", "number_template", "标题以数量模板开头；数字不是新闻本身时，改写成具体对象和变化"))
    return issues


def _colon_issues(title: str) -> list[Issue]:
    marks = COLON.findall(title)
    if not marks:
        return []
    if len(marks) > 1:
        return [Issue("warn", "colon_many", "标题里有多个冒号；只保留一个，右边给出新信息")]
    left, right = re.split(r"[：:]", title, maxsplit=1)
    if not right.strip():
        return [Issue("warn", "colon_empty", "冒号后面没有内容；把结论写完整")]
    if left.strip() in SUSPENSE_LEFT:
        return [Issue("warn", "colon_suspense", f"冒号前是悬念词「{left.strip()}」；把具体对象写在冒号前")]
    if _width(right.strip()) < 4:
        return [Issue("warn", "colon_short", "冒号后的信息太短；右边要给出新的对象、数字或结论")]
    return []


def _contrast_issues(title: str) -> list[Issue]:
    for rx in (*R.TIGHT_CONTRAST, *R.NEG_CONTRAST, *R.SALIENCE_TIGHT):
        match = rx.search(title)
        if match:
            return [Issue("warn", "neg_contrast", f"标题里有否定对照或价值宣告：「{match.group(0)}」；直接写结论")]
    return []


def _word_issues(title: str) -> list[Issue]:
    issues = []
    for word in CLICKBAIT:
        if word in title:
            issues.append(Issue("warn", "clickbait", f"命中模板词「{word}」；换成这篇文章的具体对象或结论"))
    for word in DRAMA:
        if word in title:
            issues.append(Issue("warn", "drama", f"命中夸张或拟人词「{word}」；写真实动作"))
    return issues


def check_title(title: str, *, min_han: int = 10, max_han: int = 26) -> dict:
    """检查一个标题候选；返回汉字数、显示宽度、问题清单和可用性判断。"""
    text = title.strip()
    han = len(CJK.findall(text))
    width = _width(text)
    issues = [
        *_length_issues(han, width, min_han, max_han),
        *_template_issues(text),
        *_colon_issues(text),
        *_contrast_issues(text),
        *_word_issues(text),
    ]
    if not LATIN_OR_DIGIT.search(text):
        issues.append(Issue("info", "no_anchor", "标题里没有产品名、版本号、数字或英文术语；确认技术对象足够具体"))
    if text.rstrip().endswith(("？", "?")):
        issues.append(Issue("info", "question", "问句标题要确认正文真的回答这个问题；技术文章更常用陈述句"))
    verdict = "需要改" if any(i.level == "warn" for i in issues) else "可用"
    return {"title": text, "han": han, "width": round(width, 1),
            "issues": [i.as_dict() for i in issues], "verdict": verdict}


def _print_human(results: list[dict]) -> None:
    for index, result in enumerate(results, 1):
        print(f"{index}. {result['title']}")
        print(f"   汉字 {result['han']} / 显示宽度 {result['width']:.1f} · {result['verdict']}")
        for issue in result["issues"]:
            mark = "[!]" if issue["level"] == "warn" else "[i]"
            print(f"   {mark} {issue['message']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("titles", nargs="+", help="标题候选，一个或多个")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--strict", action="store_true", help="有警告时退出 1")
    parser.add_argument("--min-han", type=int, default=10)
    parser.add_argument("--max-han", type=int, default=26)
    args = parser.parse_args()
    results = [check_title(t, min_han=args.min_han, max_han=args.max_han) for t in args.titles]
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        _print_human(results)
    if args.strict and any(r["verdict"] == "需要改" for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
