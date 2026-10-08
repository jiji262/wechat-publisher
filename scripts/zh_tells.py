"""Claude 中文腔检测:lint() 只出 advisory(DR-3,不计分);score_artifacts() 确定性伪影计分;同形字硬门(D2)。
上限只在本文件定义,均为 provisional:拿到真人基线前,不许为"让存量稿 FAIL"调参。
finder 在 zh_finders / zh_sources,正则在 zh_rules,字符层在 zh_chars。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

import zh_chars as C
import zh_finders as F
import zh_rules as R
import zh_sources as S
import zh_markers as M
import zh_text as T
from zh_rules import INSTRUCTION_ECHO, SCOPES  # noqa: F401  INSTRUCTION_ECHO 对外导出(指令回声守卫)
from zh_text import spans

# ---------- advisory 上限(只在代码里,人读输出不显示,D3) ----------
NEG_CONTRAST_HAN_PER_HIT = 1500   # 否定对照:每 1500 汉字 1 处(真人周报 0.17-0.77 处/千字)
SALIENCE_HAN_PER_HIT = 5000
COLON_HAN_PER_HIT = 2500
COUPLET_HAN_PER_HIT = 2000
EMPTY_SHORT_CAP = 2               # 空短句 ≥3 段才列;只有数字没有主谓的单独成段一律列出
CANDOR_TOTAL_CAP = 2              # 口头禅合计;同一口头禅 >1 次、段首、账号禁用词一律列出
SINGLE_CAP = 1                    # staged / self_qa / strawman / restate
TRIAD_PER_K, TRIAD_MIN_CAP = 1.0, 2
HIGHLIGHT_PER_K = 3.0             # 整句高亮每千字免罚线(阮一峰周刊最高 2.09)
DASH_DENSITY_MAX, DASH_MIN_COUNT = 3.0, 4
SECTION_END_MIN, SECTION_END_RATIO = 3, 0.35
# ---------- artifacts:每处分值与类内封顶 ----------
ART = {"functional_heading": (35, 50), "functional_heading_bare": (10, 50), "instruction_echo": (20, 60),
       "reader_shout_bait": (20, 40), "spaced_dash": (5, 25), "halfwidth_drift": (25, 25), "soft_adversarial": (20, 20),
       "zero_width": (5, 20)}
ART_MAX = 100
HALF_DRIFT_MIN, HALF_DRIFT_RATIO = 6, 0.3

# 口头禅族(含"研究者动作"族,供 fingerprint 跨篇统计)
RESEARCH_TICS: tuple[str, ...] = ("我翻了", "我对照了", "我拉了", "我加总了", "我的判断是")   # 研究者动作族
TICS: tuple[str, ...] = tuple(R.TIC_PATTERNS) + RESEARCH_TICS
ACCOUNT_BANNED: dict[str, tuple] = {"main": ("讲真",), "tech": ("这事儿", "说实话")}
ZERO = ("title", "digest", "heading", "caption")

@dataclass(frozen=True)
class Rule:
    id: str
    label: str
    pats: tuple = ()
    finder: Callable | None = None
    cap: int | Callable = 0
    zero: tuple = ()               # 零容忍位置
    on: str = "_t"                 # "_t" 去标记文本;"_m" 保留行内标记
    heavy: bool = False            # 与行内标记重叠时无视上限
    literal: bool = False          # x、y 均为 ASCII 字面量时豁免
    force: re.Pattern | None = None
    unless: re.Pattern | None = None
    tight: tuple = ()              # 只在零容忍位置追加的紧凑模式
    body: tuple = ()               # 只在正文(非零容忍位置)追加、按密度计的模式

def _per(n: int) -> Callable:          # 每 n 汉字 1 处,至少 1
    return lambda c: max(1, c["han"] // n)

def _per_k(k: float, floor: int) -> Callable:
    return lambda c: max(floor, int(k * c["han"] / 1000))

_NO_STANCE = re.compile("|".join([re.escape(t) for t in T.lexicon("zh-no-stance")] + [R.NO_STANCE_LOCAL]))
RULES: list[Rule] = [
    Rule("neg_contrast", "否定对照/翻案", R.NEG_CONTRAST, cap=_per(NEG_CONTRAST_HAN_PER_HIT), zero=ZERO, heavy=True, literal=True,
         tight=R.TIGHT_CONTRAST, body=R.NEG_CONTRAST_BODY),
    Rule("neg_listing", "否定排队", R.NEG_LISTING, zero=ZERO, tight=R.TIGHT_LISTING),
    Rule("empty_short_para", "空短句成段", finder=F.empty_short, cap=EMPTY_SHORT_CAP),
    Rule("fake_reaction", "编造的反应", finder=S.fake_reaction),
    Rule("candor_tic", "装坦诚/口头禅", finder=F.candor, cap=CANDOR_TOTAL_CAP),
    Rule("perf_imperfect", "表演出来的不完美", R.PERF_IMPERFECT),
    Rule("salience", "价值宣告/自封最高级", R.SALIENCE, cap=_per(SALIENCE_HAN_PER_HIT), zero=ZERO, tight=R.SALIENCE_TIGHT),
    Rule("staged", "预告与元话语", R.STAGED, cap=SINGLE_CAP),
    Rule("colon_reveal", "冒号揭晓", R.COLON_REVEAL, cap=_per(COLON_HAN_PER_HIT), on="_m"),
    Rule("self_qa", "设问自答", finder=F.self_qa, cap=SINGLE_CAP, zero=ZERO),
    Rule("strawman", "替读者立靶", R.STRAWMAN, cap=SINGLE_CAP, zero=ZERO),
    Rule("restate", "复述路标", R.RESTATE, cap=SINGLE_CAP, force=R.RESTATE_ZERO),
    Rule("aphorism_end", "节末/文末金句", finder=F.aphorism_end,   # 节末金句 ≥3 处且 ≥35% 的 H2 小节才列出
         cap=lambda c: max(SECTION_END_MIN, -int(-SECTION_END_RATIO * c["n_h2"] // 1)) - 1),
    Rule("cta_end", "结尾行动号召模板", finder=F.cta_end),
    Rule("triad", "三连排比/凑三", R.TRIAD, cap=_per_k(TRIAD_PER_K, TRIAD_MIN_CAP), zero=ZERO, tight=R.DIGEST_PILE_TURN),
    Rule("couplet", "对仗回环", finder=F.couplet, cap=_per(COUPLET_HAN_PER_HIT), zero=ZERO),
    Rule("heading_template", "小标题模板", finder=F.heading_template),
    Rule("dash_overuse", "破折号过量", finder=F.dash_overuse,
         cap=lambda c: max(DASH_MIN_COUNT - 1, int(DASH_DENSITY_MAX * c["han"] / 1000)) + c.get("dash_pairs", 0)),
    Rule("highlight_sentence", "整句高亮/加粗结论", finder=F.highlight, cap=lambda c: int(HIGHLIGHT_PER_K * c["kilo"])),
    Rule("no_stance", "假平衡/安全中立", (_NO_STANCE,), unless=R.STANCE_CRIT),
    Rule("unsourced_experience", "无出处的亲历", finder=S.experience),
    Rule("unsourced_quote", "无出处的引语", finder=S.quote_source),
    Rule("hedge_stack", "限定词叠加", R.HEDGE),
    Rule("false_agency", "假行动者/拟人喻体", R.FALSE_AGENCY),
]
RULE_LABELS: dict[str, str] = {r.id: r.label for r in RULES}

def _prepare(md: str, title, digest, *, brief_text, account) -> tuple[list, dict]:
    md, title, digest = (C.strip_zero_width(x)[0] if x else x for x in (md, title, digest))  # 先剥零宽,防拆词绕过(D2)
    units = T.text_units(md, title, digest)
    for u in units:
        u["ek"] = "para" if u["kind"] == "quote" and u["section"] == 0 else u["kind"]  # 导语引用块算作者正文
        u["_t"], u["_m"] = T.blank_attributed(u["text"], u["raw"]), T.blank_attributed(u["marked"], u["raw"])
        u["_mr"] = M.marker_ranges(u["marked"])   # 标记内容区间(_t 坐标),每个单元只算一次
    body = [u for u in units if u["ek"] in SCOPES and u["kind"] != "caption"]
    han = sum(T.han_count(u["text"]) for u in body)
    words = sum(len(re.findall(r"[A-Za-z]+", u["text"])) for u in body)
    ctx = {"md": md, "han": han, "kilo": max(han + words, 1000) / 1000, "banned": ACCOUNT_BANNED.get(account or "", ()),
           "n_h2": sum(1 for u in units if u["kind"] == "heading" and u["raw"].lstrip().startswith("## "))}
    return units, {**ctx, **S.parse_brief(brief_text)}

def _regex_rule(rule: Rule, units: list[dict]) -> list[dict]:
    hits = []
    for u in T.pick(units, SCOPES):
        t = u[rule.on]
        pats = rule.pats + (rule.tight if u["ek"] in rule.zero else rule.body)
        for s, e, m in [] if rule.unless and rule.unless.search(t) else spans(pats, t, rule.literal):
            force = bool(rule.force and rule.force.search(m.group(0))) or (rule.heavy and M.in_marker((s, e), u["_mr"]))
            h = T.hit(u, t, (s, e), force=force)
            hits.append({**h, "excerpt": T.strip_markers(h["excerpt"])} if rule.on == "_m" else h)
    return hits

def scan(md: str, *, brief_text=None, account=None, title=None, digest=None) -> tuple[dict, dict]:
    """全部规则的全部命中(未按上限过滤),返回 (hits_by_id, ctx)。"""
    units, ctx = _prepare(md, title, digest, brief_text=brief_text, account=account)
    out = {}
    for rule in RULES:
        hits = rule.finder(units, ctx) if rule.finder else _regex_rule(rule, units)
        out[rule.id] = sorted(({**h, "force": bool(h.get("force")) or h["kind"] in rule.zero} for h in hits),
                              key=lambda h: h["line"])
    return out, ctx

def _items(rule: Rule, hits: list[dict], ctx: dict) -> list[dict]:
    """某规则需要处理的条目:计数超上限时全部列出(density,按规则处理),否则只列强制项(position,逐条处理)。"""
    cap = int(rule.cap(ctx) if callable(rule.cap) else rule.cap)
    n = sum(1 for h in hits if not h.get("uncounted"))    # 图注等单独列出的命中不计入密度
    out = []
    for h in (hits if n > cap else [h for h in hits if h["force"]]):
        scope = "position" if h["force"] or cap == 0 else "density"
        default = f"{rule.label}:全文 {n} 处" if scope == "density" else rule.label
        out.append({"id": rule.id, "label": rule.label, "line": h["line"], "kind": h["kind"], "excerpt": h["excerpt"],
                    "count": n, "cap": cap, "scope": scope, "message": h.get("message") or default})
    return out

def lint(md: str, *, brief_text: str | None = None, account: str | None = None,
         title: str | None = None, digest: str | None = None, scanned: tuple[dict, dict] | None = None) -> list[dict]:
    """advisory 清单。每条:{id,label,line,kind,excerpt,count,cap,scope,message};message 不含上限数字(D3)。
    brief 的结构规划行另以 kind="brief" 列在最前(行号指 brief.md)。
    scanned:调用方已用同一组参数跑过 scan() 时传入其返回值,不再重跑全部规则。"""
    by_id, ctx = scanned or scan(md, brief_text=brief_text, account=account, title=title, digest=digest)
    items = [i for rule in RULES for i in _items(rule, by_id[rule.id], ctx)]
    return S.outline_items(brief_text) + sorted(items, key=lambda i: (i["line"], i["id"]))

# ---------- artifacts / 对抗字符 ----------
_GUARDED = {"关注我", "我跟你讲", "我跟你说"}   # 这几条走 SHOUT_LOCAL 的带守卫写法(关注我国、我跟你说过)
_SHOUT = re.compile("|".join([re.escape(t) for t in T.lexicon("zh-reader-shout") + T.lexicon("zh-bait") if t not in _GUARDED]
                             + [R.SHOUT_LOCAL.pattern]), re.M)

def _heading_hits(md: str, title: str | None) -> list[dict]:
    lines = [(i, ln) for i, ln in enumerate(T.mask_blocks(md).split("\n"), 1)] + ([(0, f"# {title}")] if title else [])
    return [{"id": "functional_heading" if R.H_LABEL.match(ln) else "functional_heading_bare", "line": i, "excerpt": ln.strip()}
            for i, ln in lines if R.H_LABEL.match(ln) or R.H_BARE.match(ln)]

def score_artifacts(md: str, *, title: str | None = None, digest: str | None = None) -> tuple[float, dict]:
    """确定性伪影:功能性小标题、指令回声、喊话/诱导互动、空格破折号、半角漂移、零宽字符、软对抗字符。"""
    zero_width = C.zero_width_hits(md)
    md, title, digest = (C.strip_zero_width(x)[0] if x else x for x in (md, title, digest))
    hits = _heading_hits(md, title)
    for u in T.text_units(md, title, digest):
        t = T.blank_attributed(u["text"], u["raw"])
        if u["kind"] != "quote" or u["section"] == 0:
            hits += [{"id": rid, "line": T.hit(u, t, m.span())["line"], "excerpt": m.group(0)}
                     for rx, rid in ((R.ECHO_RE, "instruction_echo"), (_SHOUT, "reader_shout_bait")) for m in rx.finditer(t)]
    hits += C.typography(md, drift_min=HALF_DRIFT_MIN, drift_ratio=HALF_DRIFT_RATIO) + zero_width
    by_id: dict[str, float] = {}
    for h in hits:
        key = "functional_heading" if h["id"].startswith("functional_heading") else h["id"]
        by_id[key] = min(ART[h["id"]][1], by_id.get(key, 0) + ART[h["id"]][0])
    return float(min(ART_MAX, sum(by_id.values()))), {"hits": hits, "by_id": by_id}

def find_adversarial_chars(md: str) -> list[dict]:
    """硬门只认同形字(D2):混进拉丁词/紧邻汉字的形似西里尔/希腊字母、成批的康熙部首。零宽字符走 artifacts。
    先剥零宽再判(E4):「用+U+200B+ΑΙ」这种插零宽拆开邻接的写法照样拦;零宽集合不含换行,行号不变。"""
    return C.find_homoglyphs(C.strip_zero_width(md)[0])
