"""zh_tells 的结构类 finder:节末/文末金句、行动号召、小标题模板、对仗、破折号、高亮、打引号、空短句、设问、口头禅。

依赖 brief 的 finder(亲历/引语/编造反应)在 zh_sources.py。每个 finder 返回命中列表,上限判定在 zh_tells.lint。
"""
from __future__ import annotations

import re
from collections import Counter

import zh_rules as R
import zh_text as T
from zh_sources import regex_hits
from zh_text import spans

_SENT_END = re.compile(r"[。！？!?]")
_CLAIM_END = re.compile(r"[。！!]\s*$")


def nonprose(s: str) -> bool:
    s = s.strip()
    return bool(R.IGNORABLE.search(s) or R.NONPROSE.match(s) or R.PURE_IMG.match(s) or s == "[CODE]")


def tail_block(blocks: list, loose: bool = False) -> tuple | None:
    """从末尾跳过分隔线/版尾/图片(loose 时再跳过链接行、括号旁白、行动号召);最后一块不是正文时返回 None。"""
    for line, text in reversed(blocks):
        s = text.strip()
        if R.IGNORABLE.search(s) or R.PURE_IMG.match(s) or (loose and (R.TAIL_SKIP.search(s) or R.CTA.search(s))):
            continue
        if R.NONPROSE.match(s) or s == "[CODE]" or (R.WRAPPED.fullmatch(s) and not _SENT_END.search(s)):
            return None
        return line, s
    return None


def _plain_short(t: str) -> bool:
    return not R.GOLDEN_BAN.search(t) and not R.APH_SIGNOFF.search(t)


def golden(p: str) -> str:
    """金句类型:neg(末句否定对照)/tail_wrapped/wrapped/short(整段短)/last_short(长段末句短);不是返回空串。"""
    t = T.strip_markers(p).strip()
    if not t or t[-1] in "：:，,":
        return ""
    sents = T.split_sentences(t) or [t]
    if T.spans(R.NEG_CONTRAST, sents[-1], literal=True):
        return "neg"
    if R.TAIL_WRAPPED.search(p) and T.han_count(sents[-1]) >= R.GOLDEN_HAN[0] + 2:
        return "tail_wrapped"
    if R.WRAPPED.fullmatch(p) and T.han_count(t) >= R.GOLDEN_HAN[0] + 2:
        return "wrapped"
    if t[-1] in "？?":
        return ""
    if R.GOLDEN_HAN[0] <= T.han_count(t) <= R.GOLDEN_HAN[1] and len(_SENT_END.findall(t)) <= 2 and _plain_short(t):
        return "short"
    lo, hi = R.LAST_SHORT_HAN
    return "last_short" if len(sents) >= 2 and lo <= T.han_count(sents[-1]) <= hi and _plain_short(sents[-1]) else ""


def _norm_end(s: str) -> str:
    return re.sub(r"[\W_]+", "", T.strip_markers(s))   # 去空白与标点后比较


def is_ending(block: str, endings: list[str]) -> bool:
    """块是否 brief 声明的固定结尾之一:互相包含且长度比 ≥ SERIES_ENDING_RATIO(endings 已归一、每条 ≥6 汉字)。"""
    b = _norm_end(block)
    return bool(b) and any((b in e or e in b) and min(len(b), len(e)) / max(len(b), len(e)) >= R.SERIES_ENDING_RATIO
                           for e in endings)


def sections(ctx) -> list[list]:
    """H2 小节的块序列(第 0 项是首个 H2 之前);brief 声明的系列固定结尾(endings,逐段匹配)整块剔除。"""
    if "_sections" not in ctx:
        endings = [e for e in map(_norm_end, ctx.get("endings", ())) if T.han_count(e) >= R.SERIES_ENDING_MIN_HAN]
        out: list[list] = [[]]
        for b in T.md_blocks(ctx["md"]):
            if b[1].startswith("## "):
                out.append([])
            elif not b[1].startswith("#") and not is_ending(b[1], endings):
                out[-1].append(b)
        ctx["_sections"] = out
    return ctx["_sections"]


def _aph_hit(tail: tuple, kind: str, *, end: bool) -> dict:
    """文末只有带格言特征的才强制列出:否定对照/整段高亮,或短句含判断标记(D5);last_short 只计数。"""
    plain = T.strip_markers(tail[1])
    last = (T.split_sentences(plain) or [plain])[-1]
    force = end and kind != "last_short" and (kind != "short" or bool(R.APH_MARK.search(last)))
    return {"line": tail[0], "kind": "para", "excerpt": re.sub(r"\s+", " ", plain)[-T.EXCERPT_MAX:], "force": force,
            "message": f"{'文末' if end else '节末'}金句({kind})"}


def aphorism_end(units, ctx) -> list[dict]:
    """H2 小节末段与全文末段的金句;图注写成判断句或标签(图注单独列出,不计入节末门槛)。"""
    secs = sections(ctx)
    last = tail_block([b for sec in secs for b in sec])
    out = []
    for tail in (tail_block(sec, loose=True) for sec in secs[1:] or secs):
        kind = golden(tail[1]) if tail else ""
        out += [_aph_hit(tail, kind, end=tail == last)] if kind else []
    for u in T.pick(units, ("caption",)):
        t = u["_t"]
        if R.CAPTION_LABEL.search(t) or (_CLAIM_END.search(t) and R.APH_MARK.search(t)):
            out.append({**T.hit(u, t, (0, len(t)), force=True, message="图注写成了判断句或总结标签:改成描述画面的短语"),
                        "uncounted": True})
    return out


def cta_end(units, ctx) -> list[dict]:
    """结尾行动号召:最后一个含正文的 H2 小节(无 H2 时为全文)末尾 CTA_TAIL_PARAS 段。"""
    secs = [[b for b in sec if not nonprose(b[1])] for sec in sections(ctx)]
    tail = next((sec for sec in reversed(secs) if sec), [])
    return [{"line": ln + text.count("\n", 0, m.start()), "kind": "para", "excerpt": T.excerpt(text, m.start(), m.end())}
            for ln, text in tail[-R.CTA_TAIL_PARAS:] for m in R.CTA.finditer(text)]


def couplet(units, ctx) -> list[dict]:
    """对仗回环:模板句式,以及后一分句整体复述前一分句。"""
    out = []
    for u in T.pick(units, R.SCOPES):
        t = u["_t"]
        found = [(s, e) for s, e, _ in spans(R.COUPLET, t)]
        cl = [m.span() for m in re.finditer(r"[^，,；;。！？!?：:\n]+", t)]
        for a, b in zip(cl, cl[1:]):
            x, y = t[a[0]:a[1]].strip(), t[b[0]:b[1]].strip()
            if T.han_count(x) >= R.COUPLET_MIN_HAN and x in y and x != y and not any(s < b[1] and a[0] < e for s, e in found):
                found.append((a[0], b[1]))
        out += [T.hit(u, t, span) for span in found]
    return out


def _ordinal_key(u: dict) -> tuple | None:
    """# 小标题(2/3 级)或整行粗体伪小标题的序数分组键 (级别, 前缀, 单位) 与序号。"""
    bold = R.BOLD_LINE.match(u["raw"].split("\n")[0]) if u["ek"] == "para" else None
    head = u["raw"].lstrip()
    level = len(head) - len(head.lstrip("#")) if u["ek"] == "heading" else ("b" if bold else 0)
    m = R.ORDINAL.match((bold.group(1) if bold else u["_t"]).strip())
    if m and level in (2, 3, "b") and m.group(3) not in R.ORDINAL_EXEMPT_UNITS:
        return (level, m.group(1), m.group(3)), m.group(2)
    return None


def heading_template(units, ctx) -> list[dict]:
    """小标题模板(N 个坑/情绪钩子词;钩子词在摘要里也查)与同组序数小标题序列(场景一/二/三、**坑一/坑二/坑三**)。"""
    out = [T.hit(u, u["_t"], m.span(), force=True)
           for u in T.pick(units, ("heading", "title", "caption", "digest")) for m in [R.HEADING_TEMPLATE.search(u["_t"])] if m]
    groups: dict = {}
    for u in T.pick(units, ("heading", "para")):
        key = _ordinal_key(u)
        if key:
            groups.setdefault(key[0], []).append((key[1], u))
    for items in groups.values():
        if len({o for o, _ in items}) >= R.ORDINAL_MIN:
            out += [T.hit(u, u["_t"], (0, len(u["_t"])), force=True, message="序数小标题序列") for _, u in items]
    return out


def dash_overuse(units, ctx) -> list[dict]:
    texts = [(u, R.DASH_ATTRIB.sub(lambda m: " " * len(m.group(0)), u["_t"])) for u in T.pick(units)]
    ctx["dash_pairs"] = sum(len(R.DASH_PAIR.findall(t)) for _, t in texts)   # 成对夹注算 1 处:上限按对数放宽
    return [T.hit(u, t, m.span()) for u, t in texts for m in R.DASH.finditer(t) if not R.DASH_LEAD_IN.match(t, m.end())]


def highlight(units, ctx) -> list[dict]:
    """整句高亮/加粗结论;小标题里的行内标记一律列出。"""
    out = []
    for u in T.pick(units, R.SCOPES):
        seen: list = []
        for m in (m for rx in T.MARK_RES for m in rx.finditer(u["_m"])):
            if any(m.start() < e and s < m.end() for s, e in seen):
                continue
            seen.append(m.span())
            head = u["ek"] in ("heading", "title")
            if head or full_sentence(T.strip_markers(m.group(1))):
                h = T.hit(u, u["_m"], m.span(), force=head, message="小标题里用了行内标记" if head else "")
                out.append({**h, "excerpt": T.strip_markers(h["excerpt"])})
    return out


def full_sentence(s: str) -> bool:
    return bool((re.search(r"[。！？!?；;…]", s) and len(s) >= 4) or T.han_count(s) >= 12
                or len(re.findall(r"[A-Za-z]+", s)) >= 8 or (re.search(r"[,，、:：]", s) and len(s) >= 6))


def empty_short(units, ctx) -> list[dict]:
    """空短句成段(≤12 汉字、无信息 token 的完整陈述句),以及只有数字没有主谓的单独成段。"""
    out = []
    for u in T.pick(units, ("para",)) if not ctx.get("dialogue") else []:
        for k, (raw, t) in enumerate(zip(u["raw"].split("\n"), u["_t"].split("\n"))):
            raw = re.sub(r"^\s*>\s?", "", raw)
            info = T.strip_markers(raw.replace("`", "")).strip()
            hit = {"line": u["line"] + k, "kind": "para", "excerpt": info}
            if R.SECTION_ORDINAL.match(info):
                continue
            if R.NUM_ONLY.match(info):
                out.append({**hit, "force": True, "message": "只有数字没有主谓,单独成段"})
            elif not R.SHORT_EXCLUDE.search(raw) and 1 <= T.han_count(t) <= R.SHORT_MAX_HAN and re.search(r"[。！!…]\s*$", t) \
                    and len(re.findall(r"[。！？!?；;…]", t)) <= R.SHORT_MAX_PUNCT \
                    and not R.INFO_TOKEN.search(R.GENERIC_EN.sub("", info)):
                out.append(hit)
    return out


def self_qa(units, ctx) -> list[dict]:
    """设问自答:同一行问完即答;或单独成段的短设问,下一段直接给答案。"""
    if ctx.get("faq"):
        return []
    out = regex_hits(R.SELF_QA, units)
    for u, nxt in zip(units, units[1:]):
        if u["ek"] == "para" == nxt["ek"] and R.SELF_QA_ALONE.match(u["_t"].strip()):
            out.append(T.hit(u, u["_t"], (0, len(u["_t"]))))
    return out


def _line_start(t: str, s: int) -> bool:
    """s 之前到行首只有空格/制表符(不切片整段,避免超长段落里逐条 O(n))。"""
    i = s
    while i > 0 and t[i - 1] in " \t":
        i -= 1
    return i == 0 or t[i - 1] == "\n"


def candor(units, ctx) -> list[dict]:
    """口头禅:段首装坦诚、账号禁用词、同一口头禅 >1 次一律列出。"""
    out = []
    for u in T.pick(units, R.SCOPES):
        t = u["_t"]
        found = [[m.start(), m.end(), name, False] for name, rx in R.TIC_PATTERNS.items() for m in rx.finditer(t)]
        for m in R.CANDOR[0].finditer(t):
            s = m.start() + (m.group(0)[0] in "。！？!?；;…”」）)")
            lead = _line_start(t, s)
            ov = [f for f in found if f[0] < m.end() and s < f[1]]
            if ov:
                ov[0][3] = ov[0][3] or lead
            else:
                found.append([s, m.end(), "candor", lead])
        out += [T.hit(u, t, (s, e), name=n, force=lead or n in ctx["banned"]) for s, e, n, lead in found]
    names = Counter(h["name"] for h in out)
    return [{**h, "force": h["force"] or (h["name"] != "candor" and names[h["name"]] > 1)} for h in out]
