#!/usr/bin/env python3
"""禁用词硬门：发布内容和生图 prompt 里不许出现 wechat-publisher.yaml 的 forbidden_terms。

词表只放在本机配置(不入库)，代码和仓库文档里不写具体词。
比对前做 NFKC、去零宽字符、大小写折叠；代码块、行内代码、链接和图片路径一样查，不提供豁免写法。
命中时只打印打码后的片段，日志里也不复现禁用词。

用法:
    python3 forbidden_terms.py article.md [more.md ...]   # 命中退出 1
"""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

import zh_chars

EXCERPT_RADIUS = 20
MASK = "***"
FIX_HINT = ("  改写这些句子，去掉禁用词；本机路径换成项目名或相对路径，不要只在路径里替换字符(会编出不存在的路径)。\n"
            "  词表在 wechat-publisher.yaml 的 forbidden_terms；这道门不受 --skip-ai-score 影响。")


def load_terms() -> list[str]:
    from config import get_forbidden_terms

    return get_forbidden_terms()


def _fold(text: str) -> str:
    clean, _ = zh_chars.strip_zero_width(unicodedata.normalize("NFKC", text or ""))
    return clean.casefold()


def _excerpt(line: str, folded_terms: list[str]) -> str:
    """整行先打码再截取，截断处不会露出半个禁用词。"""
    masked = line
    for term in sorted(folded_terms, key=len, reverse=True):
        masked = masked.replace(term, MASK)
    pos = max(masked.find(MASK), 0)
    lo = max(pos - EXCERPT_RADIUS, 0)
    return ("…" if lo else "") + masked[lo:pos + len(MASK) + EXCERPT_RADIUS].strip()


def find_terms(text: str, terms: list[str]) -> list[dict]:
    """逐行返回 {line, term_index, excerpt}；term_index 从 1 起，对应词表顺序。"""
    folded_terms = [t for t in (_fold(t).strip() for t in terms) if t]
    hits = []
    for no, line in enumerate(_fold(text).splitlines(), 1):
        for idx, term in enumerate(folded_terms, 1):
            if term in line:
                hits.append({"line": no, "term_index": idx, "excerpt": _excerpt(line, folded_terms)})
    return hits


def check(sources: dict, terms: list[str] | None = None) -> list[str]:
    """sources: {标签: 文本}。返回可打印的命中条目；没有配置词表时返回 []。"""
    terms = load_terms() if terms is None else terms
    if not terms:
        return []
    found = []
    for label, text in sources.items():
        for h in find_terms(text or "", terms):
            where = f"{label} L{h['line']}" if "\n" in (text or "") else label
            found.append(f"{where}(第 {h['term_index']} 项) {h['excerpt']}")
    return found


def abort_if_found(sources: dict, terms: list[str] | None = None) -> None:
    """命中任何禁用词 → 打印位置(打码)并 SystemExit(1)。"""
    found = check(sources, terms)
    if not found:
        return
    print(f"\n  禁用词: {len(found)} 处命中，已阻止(原文已打码)")
    for f in found:
        print(f"    · {f}")
    print(FIX_HINT)
    raise SystemExit(1)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    terms = load_terms()
    if not terms:
        print("未配置 forbidden_terms，跳过禁用词检查")
        return 0
    sources = {p: Path(p).read_text(encoding="utf-8") for p in argv}
    try:
        abort_if_found(sources, terms)
    except SystemExit as exc:
        return int(exc.code or 1)
    print("未命中禁用词")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
