"""中文 Markdown 文本工具:front matter、mask、切句、文本单元、引语归属。

所有标点常量用 \\u 转义,源码保持纯 ASCII(旧切句 bug 就是全角在源码里退化成半角)。
"""
from __future__ import annotations

import bisect
import json
import re
from functools import lru_cache
from pathlib import Path

# 句末标点:。！？；!?;(省略号不算句末)
END = "\u3002\uff01\uff1f\uff1b!?;"
# 右引号/右括号:”’」』）》
CLOSE = "\u201d\u2019\u300d\u300f\uff09\u300b"
_SPLIT_RE = re.compile(rf"(?:(?<=[{END}])|(?<=[{END}][{CLOSE}]))(?![{END}{CLOSE}])|\n+")
_HAN_RE = re.compile(r"[\u4e00-\u9fff]")
# front matter:首行可以是 YAML 注释/空行(brief.md.example 就是这样),但必须出现 key:,否则是文首分隔线
_FM_RE = re.compile(r"\A---[ \t]*\n(?=(?:[ \t]*#.*\n|[ \t]*\n)*[A-Za-z_][\w-]*[ \t]*:)(?:.*\n)*?---[ \t]*(?:\n|\Z)")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_FENCE_OPEN_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
_TABLE_RE = re.compile(r"(?m)^[ \t]*\|.*$")
_IMAGE_RE = re.compile(r"!\[([^\]\n]*)\]\([^)\n]*\)")
_URL_RE = re.compile(r"(?:https?|ftp)://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+")
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_LINK_RE = re.compile(r"\[([^\]\n]*)\]\([^)\n]*\)")
# 行内标记:**、==、++、%%、&&、!!、@@、^^(CommonMark 式 flanking,排除 C++11、x==1、a&&b)
MARK_TOKENS = ("**", "==", "++", "%%", "&&", "!!", "@@", "^^")

def _mark_re(tok: str) -> re.Pattern:
    t = re.escape(tok)
    c = "" if tok == "**" else re.escape(tok[0])
    return re.compile(rf"(?<![0-9A-Za-z_{c}]){t}(?![\s{c}])([^\n]*?[^\s{c}]){t}(?![0-9A-Za-z_])")

MARK_RES = tuple(_mark_re(t) for t in MARK_TOKENS)
_ITALIC_RE = re.compile(r"(?<![*\w])\*(?![\s*])([^*\n]+?)(?<![\s*])\*(?![*\w])")

# 直接引语:方向性引号与 ASCII 双引号,单段不跨行、≤80 字
QUOTE_RE = re.compile(
    "\u201c[^\u201c\u201d\\n]{1,80}\u201d|\u300c[^\u300c\u300d\\n]{1,80}\u300d"
    "|\u300e[^\u300e\u300f\\n]{1,80}\u300f|\"[^\"\\n]{1,80}\""
)
# 归属:引号前接 说/写/道/称/问/回复/评论(可带冒号逗号),或引号后紧跟"某人说"。
# 引号后的言说动词必须收在小句末尾(后接标点/引号/行尾),且不是 这么说/说白了/据说 之类的构词
# 引号前的「换句话说/简单说/也就是说/据说/我说」是作者自己的话,不是归属(对我说/跟我说 仍算)
_NOT_SPEAKER = (r"(?<!换句话)(?<!一句话)(?<!简单)(?<!简单地)(?<!就是)(?<!所以)(?<!可以)(?<!老实)(?<!坦白)(?<!直白)"
                r"(?<!不得不)(?<!总的来)(?<![这那怎据])(?<![这那怎]么)(?<!(?<![对跟和向给])我)")
_ATTR_BEFORE = re.compile(_NOT_SPEAKER + r"(?:说|写|道|称|问|回复|评论|表示|写道|告诉[^\s\u3002\uff0c]{0,3})(?:过|了|着)?"
                          r"[ \t]*[\uff1a:\uff0c,]?[ \t]*$")
_ATTR_AFTER = re.compile(
    r"^[ \t]*(?:[\uff0c,]|\u2014\u2014)?[ \t]*[^\u3002\uff01\uff1f\n\u201c\u201d]{0,12}?"
    r"(?<![这那怎知难味据听所小话么])(?<!就是)(?:说|问|道|写道|表示|回忆|告诉[^\u3002\uff0c,\uff01\uff1f\n]{0,4})"
    r"(?:了|过|着)?[ \t]*(?:[\u3002\uff0c\uff01\uff1f\uff1a\uff1b,.!?:;\u201c]|$)")
_SELF_AFTER = re.compile(r"^[ \t]*(?:[\uff0c,]|\u2014\u2014)?[ \t]*我(?:说|问|道|写道)")   # 「…」,我说。= 作者自引
ATTR_WIN = 40                      # 归属只看引号前后 40 字(两条归属正则的最大跨度都在此内)
# 出处:链接、issue 号、@用户名
SRC_RE = re.compile(r"https?://|(?<![A-Za-z0-9])#\d+|@[A-Za-z0-9_\-]{2,}|\[[^\]\n]+\]\([^)\n]+\)")

def normalize(md: str) -> str:
    return md.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")

def strip_front_matter(md: str) -> str:
    return _FM_RE.sub("", normalize(md), count=1)

def han_count(s: str) -> int:
    return len(_HAN_RE.findall(s))

def split_sentences(text: str) -> list[str]:
    return [p.strip() for p in _SPLIT_RE.split(text) if p and p.strip()]

def _blank(m: re.Match, fill: str = " ") -> str:
    return re.sub(r"[^\n]", fill, m.group(0))

def mask_blocks(md: str) -> str:
    """只 mask front matter、HTML 注释与围栏代码(``` 与 ~~~,未闭合则到文末;等长空格,保留换行)。"""
    lines = _COMMENT_RE.sub(_blank, _FM_RE.sub(_blank, normalize(md), count=1)).split("\n")
    fence = None
    for i, ln in enumerate(lines):
        m = _FENCE_OPEN_RE.match(ln)
        if fence is None and m:
            fence = m.group(1)
        elif fence is not None and m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) \
                and not ln.strip().strip(fence[0]):
            lines[i], fence = " " * len(ln), None
            continue
        if fence is not None:
            lines[i] = " " * len(ln)
    return "\n".join(lines)

def mask_markdown(md: str, fill: str = " ") -> str:
    """front matter/围栏代码/表格行/图片/URL/行内代码 → 等长填充,行数不变。

    fill 只作用于行内代码与 URL(artifacts 用非空白占位,避免被当成署名行)。
    """
    t = mask_blocks(md)
    t = _TABLE_RE.sub(_blank, t)
    t = _IMAGE_RE.sub(_blank, t)
    t = _URL_RE.sub(lambda m: _blank(m, fill), t)
    return _INLINE_CODE_RE.sub(lambda m: _blank(m, fill), t)

def strip_markers(s: str) -> str:
    """去 **/==/++/%%/&&/!!/@@/^^ 外壳与 *斜体*,保留内容。"""
    for _ in range(2):  # 处理一层嵌套,如 **==x==**
        for rx in MARK_RES:
            s = rx.sub(r"\1", s)
    return _ITALIC_RE.sub(r"\1", s)

_SENT_RE = re.compile(r"[^\u3002\uff01\uff1f\n]+[\u3002\uff01\uff1f]?")   # 按全角句末与换行切句(行内标记不含这些字符)

def sentence_at(text: str, pos: int) -> int:
    """pos 所在句子的序号(与 raw 按同一规则切句后对齐)。"""
    return sum(1 for m in _SENT_RE.finditer(text) if m.end() <= pos)

def sourced_sentences(text: str, raw: str) -> list[bool]:
    """text 每句是否带出处(链接/issue/@)。raw 与 text 句数对不上时一律按无出处(宁可多报,不整段放行)。"""
    raw_sents = [bool(SRC_RE.search(m.group(0))) for m in _SENT_RE.finditer(raw)]
    n = sum(1 for _ in _SENT_RE.finditer(text))
    return raw_sents if len(raw_sents) == n else [False] * n

def quote_spans(text: str, raw: str = "") -> list[tuple[int, int, bool]]:
    """引语区间 (start, end, attributed)。只有同一句里有出处时才算有归属(不按整段)。"""
    src = sourced_sentences(text, raw)
    out = []
    for m in QUOTE_RE.finditer(text):
        before, after = text[max(0, m.start() - ATTR_WIN):m.start()], text[m.end():m.end() + ATTR_WIN]
        idx = sentence_at(text, m.start())
        sourced = idx < len(src) and src[idx]
        attr = sourced or bool(_ATTR_BEFORE.search(before) or (_ATTR_AFTER.match(after) and not _SELF_AFTER.match(after)))
        out.append((m.start(), m.end(), attr))
    return out

def blank_attributed(text: str, raw: str = "") -> str:
    """把有归属的直接引语替换成等长空格(无归属的引号照常参与检测)。"""
    for s, e, attr in quote_spans(text, raw):
        if attr:
            text = text[:s] + " " * (e - s) + text[e:]
    return text

# ---------- 文本单元 ----------
_HEAD_RE = re.compile(r"^[ \t]{0,3}(#{1,6})(?:[ \t]+|$)")
_LIST_RE = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+")
_QUOTE_LINE_RE = re.compile(r"^[ \t]*>[ \t]?")
_HR_RE = re.compile(r"^[ \t]*([-*_=])(?:[ \t]*\1){2,}[ \t]*$")
_HTML_RE = re.compile(r"^[ \t]*<")
_PURE_IMAGE_RE = re.compile(r"^[ \t]*!\[([^\]\n]*)\]\([^)\n]*\)[ \t]*$")
_FM_TITLE_RE = re.compile(r"(?m)^title[ \t]*:[ \t]*[\"']?(.*?)[\"']?[ \t]*$")

def _classify(line: str) -> str:
    if not line.strip():
        return "blank"
    if _HEAD_RE.match(line):
        return "heading"
    if _HR_RE.match(line):
        return "hr"
    if _QUOTE_LINE_RE.match(line):
        return "quote"
    if _LIST_RE.match(line):
        return "list"
    return "html" if _HTML_RE.match(line) else "prose"

def _clean(line: str, kind: str) -> str:
    rx = {"heading": _HEAD_RE, "list": _LIST_RE, "quote": _QUOTE_LINE_RE}.get(kind)
    if rx:
        line = rx.sub("", line, count=1)
        line = re.sub(r"[ \t]+#+[ \t]*$", "", line) if kind == "heading" else line
    return line.rstrip()

def _unit(kind: str, line: int, raw: str, *, marked: str, section: int) -> dict:
    marked = _LINK_RE.sub(r"\1", marked)
    return {"kind": kind, "line": line, "text": strip_markers(marked), "raw": raw,
            "section": section, "marked": marked}

def _blocks(md: str) -> list[tuple[str, int, list[str], list[str]]]:
    """按行分类并合并:prose 连续行成段、quote 连续行成块;返回 (kind, 起始行, raw 行, 清理后行)。"""
    norm, masked = normalize(md).split("\n"), mask_markdown(md).split("\n")
    fenced = mask_blocks(md).split("\n")
    out: list = []
    for i, (raw, m) in enumerate(zip(norm, masked), 1):
        kind = _classify(m)
        img = _PURE_IMAGE_RE.match(fenced[i - 1])
        if kind == "blank" and img:
            out.append(("image", i, [raw], [img.group(1)]))
            continue
        kind = "code" if kind == "blank" and raw.strip() else kind   # 被 mask 的代码/表格/front matter
        if kind in ("blank", "hr", "html"):
            out.append((kind, i, [raw], []))
            continue
        if out and kind in ("prose", "quote", "code") and out[-1][0] == kind:
            out[-1][2].append(raw)
            out[-1][3].append(_clean(m, kind))
            continue
        out.append((kind, i, [raw], [_clean(m, kind)]))
    return out

def text_units(md: str, title: str | None = None, digest: str | None = None) -> list[dict]:
    """把文章拆成可检测单元,kind ∈ title/digest/heading/para/list/quote/caption。"""
    units: list[dict] = []
    section, h1_seen, after_title = 0, False, False
    for kind, line, raws, cleaned in _blocks(md):
        raw, marked = "\n".join(raws), "\n".join(cleaned)
        if kind == "blank":
            continue
        if kind == "heading":
            level = len(_HEAD_RE.match(raws[0]).group(1))
            section += level == 2
            h1_seen = h1_seen or level == 1
            units.append(_unit("title" if level == 1 else "heading", line, raw, marked=marked, section=section))
        elif kind == "quote":
            units.append(_unit("digest" if after_title else "quote", line, raw, marked=marked, section=section))
        elif kind == "image" and cleaned[0].strip():
            units.append(_unit("caption", line, raw, marked=cleaned[0], section=section))
        elif kind in ("prose", "list"):
            units.append(_unit("para" if kind == "prose" else "list", line, raw, marked=marked, section=section))
        after_title = kind == "heading" and units[-1]["kind"] == "title"
    _add_external(units, md, title=title, digest=digest, h1_seen=h1_seen)
    return units

def _add_external(units: list, md: str, *, title: str | None, digest: str | None, h1_seen: bool) -> None:
    """外部传入的 title/digest(行号 0);缺省时从 front matter 取 title。"""
    if title is None and not h1_seen:
        fm = _FM_RE.match(normalize(md))
        m = _FM_TITLE_RE.search(fm.group(0)) if fm else None
        if m and m.group(1).strip():
            units.insert(0, _unit("title", fm.group(0)[: m.start()].count("\n") + 1, m.group(0), marked=m.group(1), section=0))
    for kind, val in (("digest", digest), ("title", title)):
        if val and val.strip() and not any(u["kind"] == kind and _loose(val) in _loose(u["raw"]) for u in units):
            units.insert(0, _unit(kind, 0, val, marked=val.strip(), section=0))

_LOOSE_RE = re.compile(r"[\s`*=+%&!@^>#\[\]()~_]+")

def _loose(s: str) -> str:
    """去空白、行内标记与链接括号后比较:外部标题/摘要是同类单元(H1/H1 后引用块)原文的一部分就不再重复加。"""
    return _LOOSE_RE.sub("", s)

# ---------- 命中与摘录 ----------
EXCERPT_MAX = 80
EXCERPT_WIN = 400                  # 找句界只看命中前后 400 字:超长段落里逐条全段扫描会退化成平方
_SENT_END = "。！？!?\n"

def excerpt(t: str, s: int, e: int) -> str:
    """命中所在句子(空白折叠);过长时只取命中片段。"""
    lo, hi = max(0, s - EXCERPT_WIN), min(len(t), e + EXCERPT_WIN)
    left = max([t.rfind(c, lo, s) for c in _SENT_END] + [lo - 1]) + 1
    rights = [i for i in (t.find(c, max(e - 1, s), hi) for c in _SENT_END) if i >= 0]
    out = re.sub(r"\s+", " ", t[left:(min(rights) + 1 if rights else hi)]).strip()
    pad = max(0, (EXCERPT_MAX - (e - s)) // 2)   # 句子过长:取命中前后各 pad 字
    return out if len(out) <= EXCERPT_MAX else re.sub(r"\s+", " ", t[max(0, s - pad):e + pad]).strip()[:EXCERPT_MAX]

@lru_cache(maxsize=64)
def _newlines(t: str) -> tuple[int, ...]:
    return tuple(m.start() for m in re.finditer("\n", t))

def line_offset(t: str, pos: int) -> int:
    """pos 之前的换行数(按文本缓存换行位置后二分,命中多的长段落不再逐条全段计数)。"""
    return bisect.bisect_left(_newlines(t), pos)

def hit(u: dict, t: str, span: tuple[int, int], **kw) -> dict:
    s, e = span
    line = u["line"] + line_offset(t, s) if u["line"] else 0
    return {"line": line, "kind": u.get("ek", u["kind"]), "excerpt": excerpt(t, s, e), "match": t[s:e], **kw}

def md_blocks(md: str) -> list[tuple[int, str]]:
    """(起始行, 原文) 块序列:标题单独成块,代码/表格记为 [CODE] 占位块。"""
    return [(ln, "[CODE]" if k == "code" else "\n".join(raws)) for k, ln, raws, _ in _blocks(md) if k != "blank"]


# x、y 均为单个 ASCII 标识符形态字面量的对照豁免(true/false、int/str);带空格的英文词组不豁免
LITERAL_RE = re.compile(r"[A-Za-z0-9_.\-+/:#\"'\u201c\u201d\u2018\u2019()]+")

def spans(pats, t: str, literal: bool = False) -> list[tuple[int, int, re.Match]]:
    """多条正则的命中,重叠只保留先出现的一处;literal=True 时豁免 x、y 均为 ASCII 字面量的对照。"""
    got: list = []          # 按起点有序、两两不重叠:二分查重叠,避免命中多时平方
    starts: list[int] = []
    for p in pats:
        for m in p.finditer(t):
            gd = m.groupdict()
            if literal and gd.get("x") and gd.get("y") and all(LITERAL_RE.fullmatch(gd[k].strip() or "-") for k in "xy"):
                continue
            i = bisect.bisect_left(starts, m.end())
            if i and got[i - 1][1] > m.start():
                continue
            j = bisect.bisect_left(starts, m.start())
            starts.insert(j, m.start())
            got.insert(j, (m.start(), m.end(), m))
    return got

def pick(units: list, kinds=("para", "list", "digest")) -> list:
    return [u for u in units if u["ek"] in kinds]

# ---------- 共享词表 ----------
_LEXICON = Path(__file__).with_name("_humanizer_lexicon.json")

def lexicon(name: str, fallback: tuple = ()) -> list:
    """只读 vendored 共享词表(humanizer/lexicon.json 的副本)的某个分类;读不到用兜底。"""
    try:
        terms = json.loads(_LEXICON.read_text(encoding="utf-8")).get("categories", {}).get(name)
        return terms if isinstance(terms, list) and terms else list(fallback)
    except (OSError, ValueError):
        return list(fallback)
