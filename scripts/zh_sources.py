"""brief 解析与出处核对:experiences / series_ending / 结构规划行,以及依赖 brief 的 finder。

brief 格式唯一真源是 SKILL.md 阶段一的 YAML front matter(D4);旧格式「一手真实细节」小节继续兼容。
不引入 yaml 依赖:只解析本 skill 用到的几种写法(行尾注释、0 缩进列表、行内列表、带引号的值)。
"""
from __future__ import annotations

import re

import zh_rules as R
import zh_text as T

_EXP_HEAD_RE = re.compile(r"^#{1,6}\s*(?:亲历|experiences|一手真实细节|一手细节|真实经历)", re.I)
_OUTLINE_HEAD_RE = re.compile(r"^#{1,6}\s*(?:结构规划|文章结构|结构|文章主线|大纲)(?:[\s(（:：].*)?$")
_HEAD_RE = re.compile(r"^[ \t]{0,3}(#{1,6})(?:[ \t]+|$)")
_FM_RE = re.compile(r"\A---[ \t]*\n(?:.*\n)*?---[ \t]*(?:\n|\Z)")
_ITEM_RE = re.compile(r"^[ \t]*-[ \t]+(.*)$")
_LIST_MARK_RE = re.compile(r"^[ \t]*(?:[-*+][ \t]+|\d+[.)、][ \t]*)")
_NONE = {"无", "none", "None", ""}
_PLACEHOLDER = re.compile(r"<[^>]*>|(?i:none|null|无|-)")   # 模板占位 <...> / 无 / none:视为未设置(series 同口径)
_FUNC_CHARS = set("的了是一个我你他她这那在就也都和有不把被还")
_COVER_STOP = {"自己", "时候", "之前", "以前", "当时", "上周", "前两", "两天", "月前", "年前", "天前"}
COVER_MIN_SHARED, COVER_MIN_RATIO = 3, 0.4
EMPTY_BRIEF = {"experiences": [], "dialogue": False, "faq": False, "endings": []}


def _value(v: str) -> str:
    """去行尾注释与外层引号;引号内的 # 保留。"""
    v = v.strip()
    if v and v[0] in "\"'" and v.find(v[0], 1) > 0:
        return v[1:v.find(v[0], 1)].strip()
    return "" if v.startswith("#") else re.sub(r"\s+#.*$", "", v).strip()


def _yaml_list(fm: str, key: str) -> list[str]:
    """front matter 里 key 的值:块列表(可 0 缩进、可夹注释行)、行内列表 [a, b] 或单值。"""
    m = re.search(rf"(?m)^{key}[ \t]*:[ \t]*(.*)$", fm)
    if not m:
        return []
    rest = m.group(1).strip()
    if rest.startswith("["):
        return [_value(x) for x in rest[1:rest.rfind("]")].split(",")]
    if _value(rest):
        return [_value(rest)]
    items = []
    for ln in fm[m.end():].split("\n")[1:]:
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        im = _ITEM_RE.match(ln)
        if not im:
            break
        items.append(_value(im.group(1)))
    return items


def _section_lines(body: str, head_re: re.Pattern, offset: int) -> list[tuple[int, str]]:
    """标题匹配 head_re 的小节内的非空行 (brief 行号, 去列表标记后的文本);遇到同级或更高级标题结束。"""
    out, level = [], None
    for i, ln in enumerate(body.split("\n"), offset + 1):
        h = _HEAD_RE.match(ln)
        if h:
            n = len(h.group(1))
            level = n if head_re.match(ln.strip()) else (level if level and n > level else None)
        elif level and ln.strip():
            out.append((i, _LIST_MARK_RE.sub("", ln).strip()))
    return out


def _split(brief: str) -> tuple[str, str, int]:
    b = brief.lstrip("\ufeff").replace("\r\n", "\n")
    fm = _FM_RE.match(b)
    return (fm.group(0), b[fm.end():], fm.group(0).count("\n")) if fm else ("", b, 0)


def parse_brief(brief: str | None) -> dict:
    """brief.md → experiences(front matter 或旧版亲历小节)、series_ending(endings)与 dialogue/faq 开关。"""
    if not brief:
        return dict(EMPTY_BRIEF)
    fm, body, offset = _split(brief)
    exps = _yaml_list(fm, "experiences") + [t for _, t in _section_lines(body, _EXP_HEAD_RE, offset)]
    # dialogue / faq 开关只认 front matter(正文里的同名字样不算,防止写稿者在 brief 正文里顺手关规则)
    flags = {k: bool(re.search(rf"(?mi)^\W*{k}\W*[:：]\s*(?:true|yes)", fm)) for k in ("dialogue", "faq")}
    return {"experiences": [e for e in exps if e not in _NONE and not template_only(e)], **flags, "endings": _endings(fm)}


def template_only(v: str) -> bool:
    """去掉 <...> 占位、分隔符和空白后什么都不剩:模板没填。"""
    return not re.sub(r"<[^>]*>|[|｜\s]", "", v)


def experience_lines(brief: str | None) -> list[tuple[int, str]]:
    """experiences 条目及其在 brief.md 里的行号:front matter 列表 + 旧版「一手真实细节」小节,去掉没填的占位。"""
    if not brief:
        return []
    fm, body, offset = _split(brief)
    out, inside = [], False
    for i, ln in enumerate(fm.split("\n"), 1):
        if re.match(r"^experiences[ \t]*:", ln):
            inside = True
            continue
        item = _ITEM_RE.match(ln) if inside else None
        if item:
            out.append((i, _value(item.group(1))))
        elif inside and ln.strip() and not ln.lstrip().startswith("#"):
            inside = False
    out += _section_lines(body, _EXP_HEAD_RE, offset)
    return [(n, t) for n, t in out if t not in _NONE and not unset(t) and not template_only(t)]


def brief_field(brief: str | None, key: str) -> list[str]:
    """front matter 里某个字段的值(列表或单值),去掉没填的占位。"""
    if not brief:
        return []
    fm, _, _ = _split(brief)
    return [v for v in _yaml_list(fm, key) if not unset(v) and not template_only(v)]


def _endings(fm: str) -> list[str]:
    """series_ending:列表逐段一条;单个字符串里的字面 \\n 也按段切开;空值与占位丢弃。"""
    parts = (p.strip() for e in _yaml_list(fm, "series_ending") for p in re.split(r"\\n|\n", e))
    return [p for p in parts if p and not unset(p)]


def unset(v: str | None) -> bool:
    """brief 字段值是否等于没填:空、无/none/null/-、整段是 <...> 模板占位。"""
    return not v or not v.strip() or bool(_PLACEHOLDER.fullmatch(v.strip()))


def outline_lines(brief: str | None) -> list[tuple[int, str]]:
    """「结构规划」小节的大纲行 (brief 行号, 文本)。"""
    if not brief:
        return []
    _, body, offset = _split(brief)
    return _section_lines(body, _OUTLINE_HEAD_RE, offset)


def outline_items(brief: str | None) -> list[dict]:
    """大纲行会被照搬成正文小标题:跑功能性小标题与否定对照,命中以 kind="brief" 列出(D4)。"""
    out = []
    for line, raw in outline_lines(brief):
        text = T.strip_markers(raw)
        found = []
        if R.H_LABEL.match(f"## {text}") or R.H_BARE.match(f"## {text}"):
            found.append(("functional_heading", "功能性小标题"))
        if T.spans(R.NEG_CONTRAST + R.TIGHT_CONTRAST, text, literal=True):
            found.append(("neg_contrast", "否定对照/翻案"))
        out += [{"id": rid, "label": label, "line": line, "kind": "brief", "excerpt": text, "count": 1, "cap": 0,
                 "scope": "position", "message": f"brief.md 结构规划 L{line}:{label}(大纲会被照搬进正文,先改 brief)"}
                for rid, label in found]
    return out


# ---------- 出处覆盖 ----------
def tokens(s: str) -> set[str]:
    toks = {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9_\-.]*", s)} | set(re.findall(r"\d{2,}", s))
    for run in re.findall(r"[一-鿿]+", s):
        toks |= {run[i:i + 2] for i in range(len(run) - 1)
                 if not set(run[i:i + 2]) & _FUNC_CHARS and run[i:i + 2] not in _COVER_STOP}
    return toks


def covered(window: str, lines: list[str]) -> bool:
    """命中窗口是否被 brief 某一行覆盖(共享 token ≥3 且占该行 ≥40%)。"""
    wt = tokens(window)
    for ln in lines:
        lt = tokens(ln)
        if lt and len(lt & wt) >= COVER_MIN_SHARED and len(lt & wt) / len(lt) >= COVER_MIN_RATIO:
            return True
    return False


# ---------- 依赖 brief 的 finder ----------
def regex_hits(pats, units: list, kinds=R.SCOPES, *, on: str = "_t") -> list[dict]:
    return [T.hit(u, u[on], (s, e)) for u in T.pick(units, kinds) for s, e, _ in T.spans(pats, u[on])]


def fake_reaction(units, ctx) -> list[dict]:
    """编造的反应;brief experiences 里有对应亲历的不报。"""
    return [h for h in regex_hits(R.FAKE_REACTION, units) if not covered(h["excerpt"], ctx["experiences"])]


def _sourced(hits: list[dict], window: str, ctx) -> list[dict]:
    if not ctx["experiences"]:
        return [{**h, "message": "待核对:未传 brief 或 brief 无 experiences"} for h in hits]
    return [] if covered(window, ctx["experiences"]) else [{**h, "message": "brief experiences 里找不到出处"} for h in hits]


def experience(units, ctx) -> list[dict]:
    """第一人称亲历(时间词/次数/时长/经历体)。按句核对 brief experiences;链接证明不了用户亲历,不豁免。"""
    out = []
    for u in T.pick(units):
        for sm in re.finditer(r"[^。！？!?\n]+[。！？!?]?", u["_t"]):
            m = next((m for p in R.EXPERIENCE for m in [p.search(sm.group(0))] if m), None)
            if m:
                span = (sm.start() + m.start(), sm.start() + m.end())
                out += _sourced([T.hit(u, u["_t"], span)], sm.group(0), ctx)
    return out


def quote_source(units, ctx) -> list[dict]:
    """无出处引语:同一句里有链接/issue/@ 才算有出处(不按整段);brief 覆盖按句核对。"""
    out = []
    for u in T.pick(units, ("para", "list", "digest")):
        src = T.sourced_sentences(u["_t"], u["raw"])
        for s, e, _ in T.spans(R.UNSOURCED_QUOTE, u["_t"]):
            idx = T.sentence_at(u["_t"], s)
            if not (idx < len(src) and src[idx]):
                out += _sourced([T.hit(u, u["_t"], (s, e))], _sentence(u["_t"], idx), ctx)
    return out


def _sentence(text: str, idx: int) -> str:
    sents = [m.group(0) for m in re.finditer(r"[^。！？\n]+[。！？]?", text)]
    return sents[idx] if idx < len(sents) else text
