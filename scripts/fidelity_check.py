#!/usr/bin/env python3
"""保真核对(PR-05 + critic):初稿 vs 终稿,以及终稿数字/引语对 research.md、brief.md 的溯源。只出提示,永远 exit 0。

① 数字 / 反引号 / 拉丁专名 / 引号内文本四类集合在初稿与终稿间的增删(数字按数值比,2,768,000,000 与 27.68 亿相同);
② 终稿数字与引语在 research/brief 里找不到的(千分位、万/亿/k/M/B、% 归一;终稿可以是材料数字的四舍五入;
   引语只查有归属的直接引语和够长的引文,给概念打的短引号不查);
③ 单段改写率(1 - SequenceMatcher.ratio)>0.7;④ 总字数缩水 >15%、段落数变化大;⑤ 新增的第一人称亲历句。
    python3 scripts/fidelity_check.py article.draft.md article.md [--research research.md] [--brief brief.md] [--json]
未给 --research/--brief 时自动找终稿同目录的 research.md / brief.md。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path

import zh_text as T
from fingerprint import SIMILE, plain_text

try:  # 新增亲历句需要 zh_rules 的亲历正则与 humanize_log 的 brief 解析;缺失时跳过这一项
    import humanize_log as HL
    import zh_rules as R
except ImportError:  # pragma: no cover
    HL = R = None

SHRINK_MAX = 0.15            # 汉字缩水超过 15%:删过头(盲评里删 24% 的稿子已被判为说明书腔)
PARA_DELTA_MAX = 0.3         # 段落数变化超过 30%
REWRITE_MAX = 0.7            # 单段改写率上限
REWRITE_MIN_HAN = 20         # 短段改几个字改写率就很高,不比
SMALL_INT_MAX = 10           # ≤10 的裸整数多是序数/结构计数,不做溯源
ROUND_INT_DIGITS, ROUND_INT_ZEROS = 4, 3   # ≥4 位且末尾 ≥3 个 0 的整数视为约数(3000 可对上 2,987)
QUOTE_MIN_CHARS = 20         # 无归属的引号去标点空白后 ≥20 字才当引文溯源;更短的多是给概念打的引号
EXCERPT_MAX, RATE_DIGITS = 40, 2
MUL = {"万亿": 10 ** 12, "亿": 10 ** 8, "万": 10 ** 4, "千": 10 ** 3, "k": 10 ** 3, "K": 10 ** 3,
       "m": 10 ** 6, "M": 10 ** 6, "b": 10 ** 9, "B": 10 ** 9}
BODY_KINDS = ("para", "list", "quote", "digest")
LABELS = {"numbers": "数字", "code": "反引号", "latin": "专名", "quotes": "引语"}

_A = r"A-Za-z0-9_"
VERSION_RE = re.compile(rf"(?<![{_A}.\-/])\d+(?:\.\d+){{2,}}(?![{_A}.])")
_NUM = (r"(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?:\.(?P<frac>\d+))?(?:[ \t]*(?P<mul>万亿|亿|万|千)|(?P<en>[kKmMbB])(?![A-Za-z]))?")
_PCT = r"(?:[ \t]*(?P<pct>[%％]))?"
# 终稿侧:前面不能贴着字母/数字/点(排除 hash、GPT-4);后面的字母只允许纯单位(793MB),不允许再接数字(019fe48f)
NUM_STRICT = re.compile(rf"(?<![{_A}./])(?<![{_A}]-)" + _NUM + r"(?![A-Za-z_]*\d)" + _PCT)
NUM_LOOSE = re.compile(r"(?<![\d.])(?<!\d,)" + _NUM + _PCT)   # 材料侧从宽:时间戳、-28%、v0.1.11 里的数字都算
_DIGIT_RUN = re.compile(rf"(?<![{_A}.\-/])\d+(?:[-/]\d+)+(?![{_A}])")   # 纯数字的 2026-08-18、1-3 拆成独立数字
INLINE_CODE = re.compile(r"`([^`\n]+)`")
LATIN = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9]*(?:[-.+][A-Za-z0-9]+)*")
_SCRUB = re.compile(r"(?:https?|ftp)://[^\s)）\u3002\uff0c\uff1b\uff01\uff1f\u3001]+|\]\([^)\n]*\)")   # URL 不吞紧跟的全角标点,否则句数对不上
_NON_WORD = re.compile(r"[\W_]+")
_PARA = re.compile(r"(?:[^\n]|\n(?![ \t]*\n))+")   # 空行分段;_scrub/mask_blocks/INLINE_CODE 都等长替换,text 与 raw 同区间可切

def _line(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1

def _scrub(md: str) -> str:
    """去 front matter/注释/围栏代码与 URL、链接目标(等长空格,行号不变);表格和行内代码保留。"""
    return _SCRUB.sub(lambda m: " " * len(m.group(0)), T.mask_blocks(md))

def _num(m: re.Match) -> dict:
    digits, frac = m["int"].replace(",", ""), m["frac"] or ""
    mul = MUL.get(m["mul"] or m["en"] or "", 1)
    d = Decimal(digits + ("." + frac if frac else "")) * mul
    zeros = len(digits) - len(digits.rstrip("0"))
    approx = not frac and len(digits) >= ROUND_INT_DIGITS and zeros >= ROUND_INT_ZEROS
    unit = Decimal(1).scaleb(-len(frac)) if frac else Decimal(10) ** (zeros if approx else 0)
    pct = bool(m["pct"])
    return {"raw": m.group(0).strip(), "value": float(d), "pct": pct, "key": f"{d.normalize()}{'%' if pct else ''}",
            "small": not (frac or mul != 1 or pct) and d <= SMALL_INT_MAX, "_d": d, "_tol": unit * mul / 2}

def parse_numbers(text: str, loose: bool = False) -> list[dict]:
    """数字串归一为数值;三段以上的版本号(0.1.11)按字面比,value 为 None。loose 用于材料侧。"""
    vers = [{"raw": m.group(0), "value": None, "pct": False, "key": m.group(0), "small": False, "pos": m.start()}
            for m in VERSION_RE.finditer(text)]
    rest = _DIGIT_RUN.sub(lambda m: re.sub(r"[-/]", " ", m.group(0)), VERSION_RE.sub(lambda m: " " * len(m.group(0)), text))
    nums = vers + [{**_num(m), "pos": m.start()} for m in (NUM_LOOSE if loose else NUM_STRICT).finditer(rest)]
    return [{**n, "line": _line(text, n["pos"])} for n in sorted(nums, key=lambda n: n["pos"])]

def _public(d: dict) -> dict:
    return {k: v for k, v in d.items() if not k.startswith("_") and k not in ("pos", "small", "key")}

def unsourced_numbers(nums: list[dict], source: str) -> list[dict]:
    """终稿数字在材料里找不到的;终稿写成约数时允许材料更精确(27.8 亿 ← 2,776,100,000)。"""
    src = [s for s in parse_numbers(source, loose=True) if s["value"] is not None]
    out, seen = [], set()
    for n in (n for n in nums if not n["small"] and n["key"] not in seen):
        seen.add(n["key"])
        ok = n["raw"] in source if n["value"] is None else any(
            s["pct"] == n["pct"] and abs(s["_d"] - n["_d"]) <= n["_tol"] for s in src)
        out += [] if ok else [_public(n)]
    return out

def quotes(text: str, raw: str = "") -> list[dict]:
    """引号内文本(去行内标记;行内代码里的引号不算),按文本去重。
    attr:任一处有归属(zh_text 同口径:言说动词,或 raw 里同一句带链接/issue/@)。
    按段落对齐句子:别段句数错位不连累本段,单段内的平方开销也可忽略。"""
    text = INLINE_CODE.sub(lambda m: " " * len(m.group(0)), text)
    first: dict[str, dict] = {}
    for p in _PARA.finditer(text):
        a, b = p.span()
        for s, e, attr in T.quote_spans(text[a:b], raw[a:b]):
            q = first.setdefault(T.strip_markers(text[a + s + 1:a + e - 1]).strip(), {"line": _line(text, a + s), "attr": False})
            q["attr"] = q["attr"] or attr
    return [{"text": t, **q} for t, q in first.items() if t]

def _norm(s: str) -> str:
    return _NON_WORD.sub("", s).lower()

def _traceable(q: dict) -> bool:
    """要溯源的引语:有归属的直接引语,或够长的无归属引文;给概念打的短引号不算。"""
    return bool(q.get("attr")) or len(_norm(q["text"])) >= QUOTE_MIN_CHARS

def unsourced_quotes(qs: list[dict], source: str) -> list[dict]:
    """要溯源的引语在材料里找不到原文的(去标点与空白后比子串)。"""
    src = _norm(source)
    return [q for q in qs if _traceable(q) and _norm(q["text"]) not in src]

def _sets(text: str) -> dict[str, dict]:
    """四类集合:键用于比对,值用于展示。"""
    plain = INLINE_CODE.sub(lambda m: " " * len(m.group(0)), text)
    return {"numbers": {n["key"]: n["raw"] for n in parse_numbers(text)},
            "code": {c: c for c in (m.group(1).strip() for m in INLINE_CODE.finditer(text)) if c},
            "latin": {w: w for w in (m.group(0) for m in LATIN.finditer(plain)) if re.search(r"[A-Z]", w)},
            "quotes": {q: q for q in (T.strip_markers(m.group(0)[1:-1]).strip() for m in T.QUOTE_RE.finditer(plain)) if q}}

def _diff(a: dict, b: dict) -> dict:
    return {k: {"removed": [v for x, v in a[k].items() if x not in b[k]], "added": [v for x, v in b[k].items() if x not in a[k]]}
            for k in LABELS}

def _paras(md: str) -> list[dict]:
    return [{"line": u["line"], "kind": u["kind"], "text": plain_text(u["raw"])}
            for u in T.text_units(md) if u["kind"] in BODY_KINDS]

def _best_match(t: str, pool: list[str]) -> tuple[float, int]:
    best, idx = 0.0, 0
    for i, s in enumerate(pool):
        sm = SequenceMatcher(None, s, t, autojunk=False)
        r = sm.ratio() if sm.real_quick_ratio() > best and sm.quick_ratio() > best else 0.0
        best, idx = (r, i) if r > best else (best, idx)
    return best, idx

def rewrites(draft_paras: list[dict], final_paras: list[dict]) -> list[dict]:
    """终稿每段与初稿最接近段落的字级改写率;>0.7 提示重写过度(或整段新增)。"""
    pool = [re.sub(r"\s+", "", p["text"]) for p in draft_paras]
    out = []
    for p in final_paras:
        t = re.sub(r"\s+", "", p["text"])
        if not pool or t in pool or T.han_count(t) < REWRITE_MIN_HAN:
            continue
        best, i = _best_match(t, pool)
        if 1 - best > REWRITE_MAX:
            out.append({"line": p["line"], "rate": round(1 - best, RATE_DIGITS), "draft_line": draft_paras[i]["line"],
                        "excerpt": p["text"][:EXCERPT_MAX]})
    return out

def new_experience(draft_text: str, final_paras: list[dict], brief_text: str | None) -> list[dict]:
    """终稿新增的第一人称亲历句(初稿没有);brief experiences 能对上的不报。"""
    if R is None:
        return []
    exps, seen = HL.parse_brief(brief_text)["experiences"], re.sub(r"\s+", "", draft_text)
    hits = [(p["line"], s) for p in final_paras for s in T.split_sentences(p["text"]) if any(rx.search(s) for rx in R.EXPERIENCE)]
    return [{"line": ln, "excerpt": s[:EXCERPT_MAX]} for ln, s in hits
            if re.sub(r"\s+", "", s) not in seen and not HL.covered(s, exps)]

def _stats(dr: list[dict], fin: list[dict]) -> dict:
    out: dict[str, list[int]] = {"han": [], "paragraphs": [], "similes": []}
    for ps in (dr, fin):
        out["han"].append(sum(T.han_count(p["text"]) for p in ps))
        out["paragraphs"].append(sum(1 for p in ps if p["kind"] == "para"))
        out["similes"].append(len(SIMILE.findall("\n".join(p["text"] for p in ps))))
    return out

def _warnings(stats: dict) -> list[dict]:
    (dh, fh), (dp, fp) = stats["han"], stats["paragraphs"]
    out = []
    if dh and (dh - fh) / dh > SHRINK_MAX:
        out.append({"id": "shrink", "message": f"终稿比初稿少 {(dh - fh) / dh:.0%} 汉字:删过头,可能只剩干货:按 SKILL.md 阶段三「作者在场」从材料里补回态度、经过和对照"})
    if dp and abs(fp - dp) / dp > PARA_DELTA_MAX:
        out.append({"id": "paragraphs", "message": f"段落数 {dp} → {fp},变化大"})
    return out

def check(draft_md: str | None, final_md: str, *, sources: str | None = None, brief_text: str | None = None) -> dict:
    """核对结果;draft_md 为 None 时只做溯源,sources/brief 都没有时 unsourced 为 None。"""
    fin_text, fin_paras = _scrub(final_md), _paras(final_md)
    src = "\n".join(x for x in (sources, brief_text) if x)
    res = {"stats": {}, "diff": {}, "rewrites": [], "warnings": [], "new_experience": [],
           "unsourced": {"numbers": unsourced_numbers(parse_numbers(fin_text), src),
                         "quotes": unsourced_quotes(quotes(fin_text, T.mask_blocks(final_md)), src)} if src else None}
    if draft_md is None:
        return res
    dr_paras = _paras(draft_md)
    res["stats"] = _stats(dr_paras, fin_paras)
    res.update(diff=_diff(_sets(_scrub(draft_md)), _sets(fin_text)), rewrites=rewrites(dr_paras, fin_paras),
               warnings=_warnings(res["stats"]),
               new_experience=new_experience("\n".join(p["text"] for p in dr_paras), fin_paras, brief_text))
    return res

def run(draft: Path, final: Path, *, research: str | None = None, brief: str | None = None) -> dict:
    def pick(given: str | None, name: str) -> Path | None:
        p = Path(given) if given else final.parent / name
        return p if p.is_file() else None

    def read(p: Path | None) -> str | None:
        return p.read_text(encoding="utf-8") if p else None

    rp, bp = pick(research, "research.md"), pick(brief, "brief.md")
    res = check(read(draft if draft.is_file() else None), final.read_text(encoding="utf-8"), sources=read(rp), brief_text=read(bp))
    missing = [g for g in (research, brief) if g and not Path(g).is_file()]   # 显式指定却不存在:要说出来,不静默跳过
    return {"draft": str(draft) if draft.is_file() else None, "final": str(final),
            "sources": [str(p) for p in (rp, bp) if p], "missing": missing, **res}

def _items(res: dict) -> list[str]:
    out = [f"[{LABELS[k]}] {'初稿有、终稿没了' if op == 'removed' else '终稿新增'}:{'、'.join(v)}"
           for k, d in res["diff"].items() for op, v in d.items() if v]
    un = res["unsourced"] or {"numbers": [], "quotes": []}
    out += [f"[溯源·数字] L{n['line']} {n['raw']} 在 research/brief 里找不到" for n in un["numbers"]]
    out += [f"[溯源·引语] L{q['line']} “{q['text']}” 在 research/brief 里找不到原文" for q in un["quotes"]]
    out += [f"[改写] L{r['line']} 改写率 {r['rate']}(最接近初稿 L{r['draft_line']}):{r['excerpt']}" for r in res["rewrites"]]
    out += [f"[新增亲历] L{e['line']} {e['excerpt']}:对不上 brief experiences 就删" for e in res["new_experience"]]
    return out + [f"[提示] {w['message']}" for w in res["warnings"]]

def _render(res: dict) -> str:
    out = [f"fidelity_check:{res['draft'] or '(无初稿)'} → {res['final']}"]
    out += [f"溯源材料:{', '.join(res['sources'])}" if res["sources"] else "未找到 research.md / brief.md,跳过溯源"]
    out += [f"指定的溯源材料不存在:{m}(已跳过,检查路径)" for m in res["missing"]]
    if res["draft"] is None:
        out.append("初稿不存在,只做溯源检查(3.5a 应先 cp article.md article.draft.md)")
    else:
        (dh, fh), (dp, fp), (ds, fs) = res["stats"]["han"], res["stats"]["paragraphs"], res["stats"]["similes"]
        out.append(f"汉字 {dh} → {fh} | 段落 {dp} → {fp} | 类比 {ds} → {fs}")
    items = _items(res)
    return "\n".join(out + items + [f"共 {len(items)} 项待核对(逐条处理,在 humanize_log.md 末尾记一句处理结论)" if items else "未发现保真问题"])

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="初稿/终稿保真核对 + 数字引语溯源:只出提示,永远 exit 0")
    ap.add_argument("draft", help="初稿快照 article.draft.md")
    ap.add_argument("final", help="终稿 article.md")
    ap.add_argument("--research", help="缺省用终稿同目录 research.md")
    ap.add_argument("--brief", help="缺省用终稿同目录 brief.md")
    ap.add_argument("--json", action="store_true")
    try:
        a = ap.parse_args(argv)
        if not Path(a.final).is_file():
            raise FileNotFoundError(f"找不到终稿:{a.final}")
        res = run(Path(a.draft), Path(a.final), research=a.research, brief=a.brief)
    except SystemExit:
        return 0
    except (OSError, UnicodeDecodeError) as e:
        print(f"fidelity_check 未执行:{e}")
        return 0
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str) if a.json else _render(res))
    return 0

if __name__ == "__main__":
    sys.exit(main())
