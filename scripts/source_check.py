"""unsourced_* 保留理由的出处核对:不只看理由里写没写出处,还核对它指向的东西存在、而且和命中对得上。

- 第一人称亲历(unsourced_experience)只认 brief 的 experiences:`brief L<n>` / `brief 第 n 行` 必须落在
  experiences 条目上,`brief experiences` 要有一条按 lint 同一口径(zh_sources.covered)覆盖命中句;
  链接、issue、materials、topic 都证明不了是用户亲历。
- 引语(unsourced_quote)另认 URL、issue / PR 号、@用户名;`brief L<n>` / `brief materials` / `research.md`
  要求单独一行和命中句对得上,不拿整个文件去比。
比对时剔除 topic / keywords 里的词:产品名天然同时出现在题目和正文里,不能拿它们凑"对得上"。
"""
from __future__ import annotations

import re

import zh_sources as S

SOURCE_MIN_SHARED = 3          # 指向的那一行与命中句至少共享的词数(剔除 topic / keywords 后),与 covered() 门槛一致
UNSOURCED_PREFIX = "unsourced_"
_EXPERIENCE_ID = "unsourced_experience"
_URL = re.compile(r"https?://\S+")
_REF = re.compile(r"(?:issue|PR)\s*#?\d+|(?<![A-Za-z0-9])@[A-Za-z0-9_\-]{3,}", re.I)
_BRIEF = r"(?<![A-Za-z])brief(?:\.md)?(?![A-Za-z])\s*"
_BRIEF_LINE = re.compile(_BRIEF + r"(?:L\s*(\d+)|第\s*(\d+)\s*[行条]|(\d+)\s*行)", re.I)
_BRIEF_FIELD = re.compile(_BRIEF + r"(experiences|materials)(?![A-Za-z])", re.I)
_RESEARCH = re.compile(r"research\.md", re.I)
_LINE_DECOR = " \t-\"'"


def _generic(brief_text: str | None) -> set[str]:
    """topic / keywords 里的词:题目层面的通用词,不算"对得上"的证据。"""
    words = S.brief_field(brief_text, "topic") + S.brief_field(brief_text, "keywords")
    return set().union(*(S.tokens(w) for w in words)) if words else set()


def _matches(excerpt: str, line: str, generic: set[str]) -> bool:
    return len((S.tokens(excerpt) & S.tokens(line)) - generic) >= SOURCE_MIN_SHARED


def _cited_lines(reason: str) -> list[int]:
    return [int(next(g for g in m.groups() if g)) for m in _BRIEF_LINE.finditer(reason)]


def _experience_ok(excerpt: str, reason: str, brief_text: str) -> bool:
    exps = dict(S.experience_lines(brief_text))
    generic = _generic(brief_text)
    if any(n in exps and _matches(excerpt, exps[n], generic) for n in _cited_lines(reason)):
        return True
    field = any(m.group(1).lower() == "experiences" for m in _BRIEF_FIELD.finditer(reason))
    return field and S.covered(excerpt, list(exps.values()))


def _quote_ok(excerpt: str, reason: str, brief_text: str | None, research_text: str | None) -> bool:
    if _URL.search(reason) or _REF.search(reason):
        return True
    generic = _generic(brief_text)
    if brief_text:
        lines = brief_text.splitlines()
        if any(1 <= n <= len(lines) and _matches(excerpt, lines[n - 1].strip(_LINE_DECOR), generic)
               for n in _cited_lines(reason)):
            return True
        if any(m.group(1).lower() == "materials" for m in _BRIEF_FIELD.finditer(reason)):
            if any(_matches(excerpt, v, generic) for v in S.brief_field(brief_text, "materials")):
                return True
    if research_text and _RESEARCH.search(reason):
        return any(_matches(excerpt, ln, generic) for ln in research_text.splitlines())
    return False


def source_ok(item: dict, reason: str, *, brief_text: str | None = None, research_text: str | None = None) -> bool:
    """这条保留理由能否作为该命中的出处。非 unsourced_* 条目不需要出处,恒为 True。"""
    if not item["id"].startswith(UNSOURCED_PREFIX):
        return True
    excerpt = item.get("excerpt", "")
    if item["id"] == _EXPERIENCE_ID:
        return bool(brief_text) and _experience_ok(excerpt, reason, brief_text)
    return _quote_ok(excerpt, reason, brief_text, research_text)
