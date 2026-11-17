#!/usr/bin/env python3
"""中文标点全角化:转换(落盘时用)与残留检查(发布前用)共用同一套判定。

只转 , : ; ? ! (紧邻汉字或全角标点,中间可隔一个空格、可隔行内标记)和成对的 ( ) 与 ASCII 双引号(内容含汉字或左侧是汉字)。
front matter、代码、URL、链接/图片路径、HTML 标签、!! 标色标记不动;数字内部
(2,768、11:27)和整句英文引文两侧都不是汉字,自然不动。判定宁可漏转,不可错改。
    python3 zh_punct.py article.md            # 列出半角残留,有残留 exit 1
    python3 zh_punct.py article.md --write    # 原地转换
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import zh_text as T

SINGLE = {",": "，", ":": "：", ";": "；", "?": "？", "!": "！"}
PAREN, QUOTE = ("（", "）"), ("“", "”")
_CN_RE = re.compile("[㐀-鿿豈-﫿　-〿＀-￯“”‘’]")
_HAN_RE = re.compile("[㐀-鿿豈-﫿]")
_MARKERS = "*_=~^@%&+"            # 行内标记字符:找邻居时跳过
_PROTECT = (
    re.compile(r"`[^`\n]+`"),                       # 行内代码
    re.compile(r"(?:https?|ftp)://[^\s)<>　-〿＀-￯]+"),
    re.compile(r"(?<=\])\([^)\n]*\)"),              # 链接 / 图片路径
    re.compile(r"!(?=\[)"),                         # 图片的 !
    re.compile(r"<[^>\n]+>"), re.compile(r"&#?\w+;"),
    re.compile(r"!{2,}"),                           # !! 标色标记
)
_PAIR_RES = ((re.compile(r"\(([^()\n]*)\)"), PAREN), (re.compile(r'"([^"\n]{1,80})"'), QUOTE))
EXCERPT_MAX = 60
MAX_PASSES = 3                    # 引号对依赖左侧标点先转,两轮就能收敛,留一轮余量
_KEEP_SPACE_NEXT_TO = " \t\n|"


def _protected(md: str) -> bytearray:
    masked = T.mask_blocks(md)             # front matter / 围栏代码 / HTML 注释,等长
    prot = bytearray(a != b for a, b in zip(md, masked))
    for rx in _PROTECT:
        for m in rx.finditer(md):
            prot[m.start():m.end()] = b"\x01" * (m.end() - m.start())
    return prot


def _side(chars: list[str], i: int, step: int) -> str:
    """i 一侧最近的有效字符:最多跳过一个空格,行内标记不限。"""
    j, spaces = i + step, 0
    while 0 <= j < len(chars):
        c = chars[j]
        if c in " \t" and not spaces:
            spaces = 1
        elif c not in _MARKERS:
            return c
        j += step
    return ""


def _cn(c: str) -> bool:
    return bool(c) and bool(_CN_RE.match(c))


def _odd_quote_lines(md: str, prot: bytearray) -> set[int]:
    """未受保护的 ASCII 双引号是奇数个的行(配不上对,整行引号都不动)。"""
    odd, line, count = set(), 0, 0
    for i, c in enumerate(md + "\n"):
        if c == "\n":
            if count % 2:
                odd.add(line)
            line, count = line + 1, 0
        elif c == '"' and not prot[i]:
            count += 1
    return odd


def _convert_pairs(md: str, chars: list[str], prot: bytearray) -> list[int]:
    odd, done = _odd_quote_lines(md, prot), []
    for rx, (left, right) in _PAIR_RES:
        for m in rx.finditer(md):
            a, b = m.start(), m.end() - 1
            if prot[a] or prot[b] or (rx.pattern[0] == '"' and md.count("\n", 0, a) in odd):
                continue
            # 只看内容和左侧:右侧是汉字不算,foo(bar) 后面接中文很常见
            if _HAN_RE.search(m.group(1)) or _cn(_side(chars, a, -1)):
                chars[a], chars[b] = left, right
                done += [a, b]
    return done


def _convert(md: str) -> list[str]:
    """返回转换后的字符表;删除的空格记为空串,保持下标不变。"""
    prot, chars = _protected(md), list(md)
    done = _convert_pairs(md, chars, prot)
    for i, c in enumerate(chars):
        if c in SINGLE and not prot[i] and (_cn(_side(chars, i, -1)) or _cn(_side(chars, i, 1))):
            chars[i] = SINGLE[c]
            done.append(i)
    for i in done:                          # 全角标点自带间距,去掉两侧各一个多余空格(表格竖线旁的不动)
        if i > 1 and chars[i - 1] in " \t" and chars[i - 2] not in _KEEP_SPACE_NEXT_TO:
            chars[i - 1] = ""
        if i + 2 < len(chars) and chars[i + 1] in " \t" and chars[i + 2] not in _KEEP_SPACE_NEXT_TO:
            chars[i + 1] = ""
    return chars


def to_fullwidth(md: str) -> str:
    """转到不再变化为止:引号对的左侧标点本轮才转成全角时,下一轮引号才满足条件。"""
    md = T.normalize(md)
    for _ in range(MAX_PASSES):
        out = "".join(_convert(md))
        if out == md:
            break
        md = out
    return md


def halfwidth_left(md: str) -> list[dict]:
    """转换会改动的行:{line, excerpt}。行号从 1 起。"""
    md = T.normalize(md)
    pairs = zip(md.split("\n"), to_fullwidth(md).split("\n"))
    return [{"line": n, "excerpt": a.strip()[:EXCERPT_MAX]} for n, (a, b) in enumerate(pairs, 1) if a != b]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", type=Path)
    ap.add_argument("--write", action="store_true", help="原地把可转换的半角标点改成全角")
    args = ap.parse_args()
    text = args.path.read_text(encoding="utf-8")
    if args.write:
        fixed = to_fullwidth(text)
        changed = len(halfwidth_left(text))
        if fixed != text:
            args.path.write_text(fixed, encoding="utf-8")
        print(f"已转换 {changed} 行")
        return 0
    left = halfwidth_left(text)
    for r in left:
        print(f"L{r['line']} {r['excerpt']}")
    print(f"半角标点残留 {len(left)} 行" if left else "无半角标点残留")
    return 1 if left else 0


if __name__ == "__main__":
    raise SystemExit(main())
