#!/usr/bin/env python3
"""
AI 味检测器(反 AI 检测自检工具)

对一篇 Markdown 文章做启发式扫描,总分 0-100,越高越接近已知 AI 模式。
低分只说明没撞上已知模式,不等于"像真人";advisory 命中项仍需逐条处理。

计分维度(news 权重,provisional):burstiness 句长方差 10% / phrases 套话 35% / vocab 高频词 25% /
structural 教科书枚举 5% / punctuation 标点单调 10% / style 富文本装饰 15%;
另加 artifacts 确定性伪影罚分(news ×0.20,newspic ×0.30)。同形字是硬门;零宽/双向控制字符先剥离再打分,另计 artifacts。
句式层的 Claude 腔(否定对照、设问自答、金句收尾…)只出 advisory,不进总分、不改退出码(DR-3)。

用法:
    python3 ai_score.py article.md [--json] [--threshold 40] [--mode news|newspic]
    python3 ai_score.py article.md --advisory --brief brief.md --account main
    python3 ai_score.py article.md --log-template --save-lint    # 同目录生成 humanize_log.md / ai_lint.json
    python3 ai_score.py brief.md --newspic-brief                  # 贴图 brief:短文本打分,要点+短文本跑 lint

返回:exit 0 通过(分数 < 阈值且无硬门);exit 1 失败。
"""

import re
import sys
import json
import argparse
import statistics
from pathlib import Path

import humanize_log
import zh_chars
import zh_finders
import zh_tells
import zh_text as T

# 默认失败阈值：总分 >= 该值视为"AI 味过重"。
# check_ai_score()、CLI --threshold 默认值和 publish.py 均应引用此常量，保持一致。
DEFAULT_THRESHOLD: float = 45.0
WARN_BAND: float = 10.0          # 阈值以下 WARN_BAND 分以内记为 WARN


# ---------- 共享词表(单一真源) ----------
# 真源在仓库根 humanizer/lexicon.json,由 humanizer/sync.mjs 生成 vendored 副本 _humanizer_lexicon.json;
# 读不到副本时回退到内置兜底列表。只读,不修改。
_lexicon_category = T.lexicon


# ---------- 黑名单 ----------

# 句式正则(18 条;『让我们一起来/让我们共同/从某种意义上』不在 zh-set-phrase 里,必须保留)
AI_PHRASE_REGEX = [
    r"首先[,，].{0,8}其次[,，].{0,10}最后", r"首先[,，].{0,8}其次[,，].{0,10}再次", r"不仅.{0,10}而且",
    r"一方面.{0,15}另一方面", r"在.{1,15}的背景下", r"随着.{1,20}的发展", r"随着.{1,20}的不断", r"让我们一起来",
    r"让我们共同", r"从某种意义上(说|讲)", r"在.{1,10}时代", r"站在.{1,10}的角度", r"为.{1,10}提供了.{1,10}可能",
    r"打开了.{1,10}的大门", r"开启了.{1,10}的篇章", r"翻开了.{1,10}新的一页", r"具有(重要|深远|里程碑)的意义",
    r"产生了(深远|重大|巨大)的影响",
]
# 字面套话:真源 zh-set-phrase;兜底恰好是原硬编码的 14 个。<4 字的词条忽略,防止短词误报暴增。
_SET_PHRASE_FALLBACK = [
    "众所周知", "不可否认", "毋庸置疑", "综上所述", "总而言之", "总的来说", "由此可见",
    "不难发现", "显而易见", "值得一提的是", "归根结底", "无论如何", "在当今社会", "进入新时代",
]
MIN_SET_PHRASE_LEN = 4
SET_PHRASES = [t for t in _lexicon_category("zh-set-phrase", _SET_PHRASE_FALLBACK)
               if isinstance(t, str) and len(t) >= MIN_SET_PHRASE_LEN]
AI_PHRASES = AI_PHRASE_REGEX + [re.escape(t) for t in SET_PHRASES]
# 真人文本里常作句首话语标记的弱信号,引擎内降权(DR-2:处置留在各引擎,不改共享词表)
WEAK_SET_PHRASES = frozenset({"无论如何", "总的来说"})
PHRASE_HIT_PENALTY, PHRASE_WEAK_PENALTY = 15, 5

# AI 高频名词 / 形容词(整篇密集出现即扣分)。
# 真源见 humanizer/lexicon.json 的 zh-commercial 分类;下方是独立安装时的兜底。
_AI_VOCAB_FALLBACK = [
    "赋能", "打造", "聚焦", "深度融合", "生态", "闭环", "链路", "抓手",
    "价值链", "护城河", "方法论", "底层逻辑", "生态位", "结构化思维",
    "提升效率", "助力", "全链路", "一站式", "端到端", "量变到质变",
    "引领", "颠覆", "革命性", "前所未有", "核心竞争力", "范式", "新范式",
    "降本增效", "数字化转型", "智能化", "生态体系", "产业升级",
    "破局", "出圈", "破圈", "沉淀", "赋予", "深耕", "蓝图", "新篇章",
]
AI_VOCAB = _lexicon_category("zh-commercial", _AI_VOCAB_FALLBACK)


def _strip_markdown(md_text: str) -> str:
    """去掉 front matter/代码/表格/图片/URL 与标记,只留正文文字。标题文字保留(套话常在标题里)。"""
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", T.mask_markdown(md_text))
    # 行首空白只用 [ \t]:mask 后的代码/表格是大段空白,\s 跨行会退化成平方复杂度
    text = re.sub(r"(?m)^[ \t]*(?:#{1,6}[ \t]*|>[ \t]*|[-*+][ \t]+|\d+\.[ \t]+)", "", T.strip_markers(text))
    return re.sub(r"[ \t　]+", " ", text).strip()


_split_sentences = T.split_sentences


def _burst_sentences(md_text: str) -> list:
    """burstiness 输入:只取正文段与摘要,保留 ≥4 字且含汉字的句子(列表/标题/表格不算)。"""
    sents = (re.sub(r"\s+", " ", s) for u in T.text_units(md_text) if u["kind"] in ("para", "digest")
             for s in T.split_sentences(u["text"]))
    return [s for s in sents if len(s) >= 4 and T.han_count(s)]


# ---------- 各维度打分 ----------

def score_burstiness(sentences: list) -> tuple:
    """
    真人写作句长分布有"突发性"(burstiness)。
    计算句长的变异系数(CV = stdev / mean),CV 越大越像真人。
    转换为 0-100 的 AI 味分数(CV 越小分越高)。
    """
    if len(sentences) < 5:
        return 50.0, {"cv": None, "reason": "too_few_sentences"}
    lengths = [len(s) for s in sentences]
    mean = statistics.mean(lengths)
    stdev = statistics.stdev(lengths) if len(lengths) > 1 else 0
    cv = stdev / mean if mean else 0
    # CV 0.3 以下 = 非常平滑(AI 味 90),CV 0.8 以上 = 抖动大(AI 味 10)
    if cv <= 0.3:
        ai = 90
    elif cv >= 0.8:
        ai = 10
    else:
        ai = 90 - (cv - 0.3) * (80 / 0.5)
    return round(ai, 1), {
        "sentence_count": len(sentences),
        "cv_sentence_count": len(sentences),
        "mean_length": round(mean, 1),
        "stdev": round(stdev, 1),
        "cv": round(cv, 3),
    }


def score_phrases(text: str) -> tuple:
    """AI 套话命中率(按 span 去重;有归属的直接引语里的命中不计;弱信号词降权)。"""
    quoted = [(s, e) for s, e, attr in T.quote_spans(text) if attr]
    seen_spans = {}  # (start, end) -> matched text
    for pat in AI_PHRASES:
        for m in re.finditer(pat, text):
            span = (m.start(), m.end())
            # 只保留首次命中(不同 pattern 命中同一 span 算一次)
            if span not in seen_spans and not any(s <= span[0] and span[1] <= e for s, e in quoted):
                seen_spans[span] = m.group(0)
    # 再做一轮重叠消除:若 span A 完全被 span B 包含,则丢弃 A
    spans = sorted(seen_spans.keys(), key=lambda s: (s[0], -s[1]))
    kept = []
    for span in spans:
        contained = any(
            other != span and other[0] <= span[0] and other[1] >= span[1]
            for other in seen_spans.keys()
        )
        if not contained:
            kept.append(span)
    hits = [seen_spans[s] for s in kept]
    ai = min(100, sum(PHRASE_WEAK_PENALTY if h in WEAK_SET_PHRASES else PHRASE_HIT_PENALTY for h in hits))
    return round(float(ai), 1), {"hit_count": len(hits), "samples": hits[:8]}


def score_vocab(text: str) -> tuple:
    """AI 高频词密度。"""
    hits = {}
    for w in AI_VOCAB:
        c = text.count(w)
        if c > 0:
            hits[w] = c
    total = sum(hits.values())
    # 每 1000 字允许最多 2 个,再多按比例扣分
    char_count = max(1, len(text))
    density = total / (char_count / 1000)
    if density <= 2:
        ai = density * 15  # 0-30
    elif density <= 5:
        ai = 30 + (density - 2) * 15  # 30-75
    else:
        ai = min(100, 75 + (density - 5) * 5)
    return round(float(ai), 1), {
        "total_hits": total,
        "density_per_1k": round(density, 2),
        "top": sorted(hits.items(), key=lambda x: -x[1])[:10],
    }


def _enum_item(n: str) -> str:
    # 第X 必须紧跟标点(排除 第一次/第一个);X是 不强制标点(排除 一是一,二是二)
    return r"^[ \t　]*(?:第" + n + r"[，,、：:]|" + n + r"是(?![一二三四五六七八九十]))"


_ENUM_GAP = r"[^\n]*\n(?:[^\n]*\n){0,12}?"   # 不用 (?s).*:会指数级回溯
STRUCT_PATTERNS = [
    re.compile("(?m)" + _enum_item("一") + _ENUM_GAP + _enum_item("二") + _ENUM_GAP + _enum_item("三")),
    re.compile(r"第一[,，、].{0,80}第二[,，、].{0,80}第三"),
    re.compile(r"(?<![统唯单同专万])一是(?![一二三四五六七八九十])[^。\n]{0,60}二是[^。\n]{0,60}三是"),
]
STRUCT_HIT_POINTS = 35


def score_structural_perfection(text: str) -> tuple:
    """教科书式枚举(含跨段的 第一,/第二,/第三, 与 一是/二是/三是),重叠 span 合并计 1 次。"""
    hits, end = 0, -1
    for s, e in sorted(m.span() for p in STRUCT_PATTERNS for m in p.finditer(text)):
        hits += s >= end
        end = max(end, e)
    return round(float(min(100, hits * STRUCT_HIT_POINTS)), 1), {"hit_count": hits}


def score_punctuation_flatness(text: str, discount: float = 0) -> tuple:
    """标点单调度(破折号贡献封顶 1/3;discount 扣掉设问自答的问号、冒号揭晓的破折号)。"""
    chars = len(text)
    # 每 1000 字期望出现 5 次以上"人味标点";短文本用 200 字做下限避免过度敏感
    expected = max(chars, 200) / 1000 * 5
    flavor = min(text.count("——") * 3, expected / 3)
    flavor += text.count("…") * 2
    flavor += text.count("?") + text.count("？")
    flavor += (text.count("!") + text.count("！")) // 2  # 感叹号加分但上限低
    flavor += text.count("(") + text.count("（") + text.count(")") + text.count("）")
    flavor = max(0, flavor - discount)
    ratio = flavor / expected if expected else 0
    if ratio >= 1:
        ai = 10
    elif ratio >= 0.5:
        ai = 30
    elif ratio >= 0.2:
        ai = 60
    else:
        ai = 85
    return round(float(ai), 1), {
        "flavor_points": round(flavor, 1),
        "expected": round(expected, 1),
        "ratio": round(ratio, 2),
    }


_EMOJI_RE = re.compile(
    r"[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002190-\U000021FF\U00002B00-\U00002BFF]"
)
_SEP_LINE_RE = re.compile(r"(?m)^[ \t]*([*=+%&!@^_-])([ \t]*\1){2,}[ \t]*$")
MARK_FREE_DENSITY, MARK_RAMP_END, MARK_RAMP_MAX, MARK_TAIL_MAX = 3.0, 10.0, 60.0, 20.0
FULL_HL_FREE_PER_K, FULL_HL_POINTS, FULL_HL_MAX = 3.0, 8.0, 20.0


def score_style(md_text: str) -> tuple:
    """富文本装饰(DC-04):8 种行内标记按千字密度(** 按半处)、整句高亮密度、标题内标记、内联标题、emoji。"""
    raw = T.mask_blocks(md_text)
    lines = [ln for ln in raw.split("\n") if ln.strip()]
    inline_headers = len(re.findall(r"(?m)^[ \t]*(?:[-*+]|\d+\.)[ \t]+\*\*", raw))
    emoji_bullets = sum(1 for ln in lines if _EMOJI_RE.match(ln.strip()))
    emoji_total = len(_EMOJI_RE.findall(raw))
    t = _SEP_LINE_RE.sub("", T.mask_markdown(re.sub(r"<!--.*?-->", "", raw, flags=re.S)))
    t = re.sub(r"!?\[[^\]]*\]\([^)]*\)", "", t)
    seen, n = [], {"colored": 0, "bold": 0, "full": 0, "heading": 0}
    for m in (m for rx in T.MARK_RES for m in rx.finditer(t)):
        if not any(m.start() < e and s < m.end() for s, e in seen):   # 嵌套 **==x==** 算 1 处
            seen.append(m.span())
            n["bold" if m.group(0).startswith("**") else "colored"] += 1
            n["full"] += zh_finders.full_sentence(T.strip_markers(m.group(1)))
            n["heading"] += bool(re.match(r"#{1,3}\s", t[t.rfind("\n", 0, m.start()) + 1:]))
    kilo = max(T.han_count(t) + len(re.findall(r"[A-Za-z]+", t)), 1000) / 1000
    density = (n["colored"] + 0.5 * n["bold"]) / kilo
    ramp = MARK_RAMP_MAX * (density - MARK_FREE_DENSITY) / (MARK_RAMP_END - MARK_FREE_DENSITY)
    marker = 0 if density <= MARK_FREE_DENSITY else (ramp if density <= MARK_RAMP_END
                                                      else MARK_RAMP_MAX + min(MARK_TAIL_MAX, (density - MARK_RAMP_END) * 2))
    full = min(FULL_HL_MAX, max(0, n["full"] / kilo - FULL_HL_FREE_PER_K) * FULL_HL_POINTS)
    ai = marker + full + min(10.0, n["heading"] * 5) + min(30.0, inline_headers * 15)
    ai += min(20.0, emoji_bullets * 10) + min(10.0, emoji_total * 3)
    return round(min(100.0, ai), 1), {**n, "density_per_1k": round(density, 2), "inline_headers": inline_headers,
                                      "emoji_bullets": emoji_bullets, "emoji_total": emoji_total}


# ---------- 总评 ----------
# 权重全部 provisional:拿到真人基线(PR-06)前,不许为"让存量稿 FAIL"调权重。
# burstiness 在本语料上方向相反(AI 稿 CV 反而更大),降到 0.10,份额还给 phrases/vocab/style。
WEIGHTS_NEWS = {"burstiness": 0.10, "phrases": 0.35, "vocab": 0.25, "structural": 0.05, "punctuation": 0.10, "style": 0.15}
# 贴图短文本:burstiness/structural 不稳定归 0;style 不提高(真人贴图常用 emoji 打头)
WEIGHTS_NEWSPIC = {"burstiness": 0.0, "phrases": 0.45, "vocab": 0.35, "structural": 0.0, "punctuation": 0.10, "style": 0.10}
# artifacts 不进凸组合,按加法罚分计入,避免稀释词表信号。newspic 取 0.30:非词表理论上限 48.5 ≥ 阈值,gate 能失败。
ARTIFACT_PENALTY = {"news": 0.20, "newspic": 0.30}

# 向后兼容:现有代码从本模块 `from ai_score import WEIGHTS` 的地方仍然能读到长文权重
WEIGHTS = WEIGHTS_NEWS


def _weights_for(mode: str) -> dict:
    if mode == "newspic":
        return WEIGHTS_NEWSPIC
    return WEIGHTS_NEWS


HARD_FAIL_VERDICT = "🔴 FAIL (含同形字:形似拉丁的西里尔/希腊字母或康熙部首,硬门)"


def _verdict(total: float, threshold: float) -> str:
    """档位由阈值派生,与退出码一致(total 须是取整后的值)。"""
    if total >= threshold:
        return f"🔴 FAIL (≥ 阈值 {threshold:g},发布会被拦截)"
    if total >= threshold - WARN_BAND:
        return f"🟡 WARN (距阈值 {threshold:g} 不足 {WARN_BAND:g} 分,建议再改一轮)"
    return "🟢 PASS (低于阈值;低分不等于没有 AI 味,命中项仍需逐条看)"


def analyze(md_text: str, mode: str = "news", threshold: float = DEFAULT_THRESHOLD, *,
            brief_text=None, account=None, title=None, digest=None) -> dict:
    """对一段 Markdown 打分;返回各维度、advisory 清单(不计分)与 hard_fail(同形字,正文与外部标题/摘要都查)。"""
    ctx = {"brief_text": brief_text, "account": account, "title": title, "digest": digest}
    artifacts = zh_tells.score_artifacts(md_text, title=title, digest=digest)   # 含零宽字符计分,须在剥离前
    adversarial = [{**a, "where": w} for w, v in (("title", title), ("digest", digest)) if v
                   for a in zh_tells.find_adversarial_chars(v)] + zh_tells.find_adversarial_chars(md_text)
    md_text = zh_chars.strip_zero_width(md_text)[0]
    plain = _strip_markdown(md_text)
    scanned = zh_tells.scan(md_text, **ctx)   # lint 复用这次结果:规则只跑一遍
    by_id = scanned[0]
    discount = len(by_id["self_qa"]) + 3 * sum("—" in h.get("match", "") for h in by_id["colon_reveal"])
    scores = {
        "burstiness": score_burstiness(_burst_sentences(md_text)), "phrases": score_phrases(plain),
        "vocab": score_vocab(plain),
        "structural": score_structural_perfection(_strip_markdown(re.sub(r"(?m)^[ \t]*>.*$", "", md_text))),
        "punctuation": score_punctuation_flatness(plain, discount),
        "style": score_style(md_text),   # 在原始 markdown 上算,否则加粗/emoji 已被剥掉
        "artifacts": artifacts,
    }
    weights = _weights_for(mode)
    penalty = ARTIFACT_PENALTY.get(mode, ARTIFACT_PENALTY["news"])
    total = round(min(100.0, sum(scores[d][0] * w for d, w in weights.items()) + penalty * scores["artifacts"][0]), 1)
    return {
        "total_ai_score": total, "threshold": float(threshold), "mode": mode,
        "verdict": HARD_FAIL_VERDICT if adversarial else _verdict(total, threshold),
        "char_count": len(plain), "sentence_count": len(_split_sentences(plain)),
        "dimensions": {d: {"score": sc, "detail": det} for d, (sc, det) in scores.items()},
        "weights": weights, "artifact_penalty": penalty, "advisory": zh_tells.lint(md_text, **ctx, scanned=scanned),
        "rule_counts": {k: len(v) for k, v in by_id.items()},
        "hard_fail": "adversarial_chars" if adversarial else None, "adversarial": adversarial,
    }


def check_ai_score(md_content: str, threshold: float = DEFAULT_THRESHOLD, mode: str = "news", **ctx) -> tuple:
    """
    库入口(publish.py 的 gate)。ctx 透传 brief_text/account/title/digest。

    Returns (passed, report):passed = total_score < threshold 且无 hard_fail;report 含 total_score、mode、
    verdict、dimensions(各维度原始分,含 artifacts)、hit_phrases、hit_vocab、threshold、advisory、hard_fail。
    """
    full = analyze(md_content, mode=mode, threshold=threshold, **ctx)
    dims = full["dimensions"]
    report = {
        "total_score": full["total_ai_score"], "mode": full.get("mode", mode), "verdict": full["verdict"],
        "dimensions": {name: d["score"] for name, d in dims.items()},
        "hit_phrases": list(dims["phrases"]["detail"].get("samples", [])),
        "hit_vocab": [w for w, _ in dims["vocab"]["detail"].get("top", [])],
        "threshold": float(threshold), "advisory": full["advisory"], "hard_fail": full["hard_fail"],
        "artifacts": dims["artifacts"]["detail"]["hits"], "adversarial": full["adversarial"],
    }
    return _passed(full, threshold), report


def _passed(full: dict, threshold: float) -> bool:
    return full["total_ai_score"] < threshold and not full["hard_fail"]


def _print_advisory(items: list, artifacts: list = ()):
    """人读输出不显示上限数字(D3):density 按规则成组,position 逐条;artifacts 一并列出(3.5a 一条命令看全)。"""
    print(f"advisory: {len(items)} 条待处理(不计分;改掉,或在 humanize_log.md 写保留理由)")
    for rid in dict.fromkeys(a["id"] for a in items if a.get("scope") == "density"):
        group = [a for a in items if a["id"] == rid and a.get("scope") == "density"]
        print(f"  [{rid}] {group[0]['label']}:全文 {group[0]['count']} 处 → 整体减少这种写法;"
              f"确需保留就在 log 写一行(原文填 *)")
        for a in group:
            print(f"      L{a['line']} {a['excerpt']}")
    for a in (a for a in items if a.get("scope") != "density"):
        print(f"  [{a['id']}] L{a['line']} {a['excerpt']}  —— {a['message']}(逐条处理)")
    if artifacts:
        print(f"artifacts: {len(artifacts)} 条(计分伪影,直接改,不能保留)")
        for h in artifacts:
            print(f"  [{h['id']}] L{h['line']} {h['excerpt']}")


def _print_hard_fail(report: dict):
    """同形字硬门行(位置 + 码位);完整报告和 --advisory 都打印(E4)。"""
    if report.get("hard_fail"):
        print(f"硬门: {report['hard_fail']} → " + "; ".join(f"{a.get('where') or 'L' + str(a['line'])} {a['excerpt']}"
                                                           f"({a['codepoint']})" for a in report["adversarial"]))


def _pretty_print(report: dict):
    print("=" * 60)
    print(f" AI 味检测报告  —— {report['verdict']}")
    print("=" * 60)
    mode = report.get("mode", "news")
    print(f"模式: {mode}  (news=长文, newspic=贴图短文)")
    print(f"总分: {report['total_ai_score']} / 100  (越高越接近已知 AI 模式)")
    print(f"字数: {report['char_count']}  句数: {report['sentence_count']}")
    print("-" * 60)
    weights = report.get("weights", WEIGHTS)
    for name, d in report["dimensions"].items():
        w = report.get("artifact_penalty", 0) if name == "artifacts" else weights.get(name, 0)
        suffix = "  [跳过]" if w == 0 else ("  [加法罚分]" if name == "artifacts" else "")
        print(f"  [{name:13s}] 分数={d['score']:>5}  权重={int(w*100)}%{suffix}")
        det = d["detail"]
        if name == "phrases" and det.get("hit_count"):
            print(f"      命中 {det['hit_count']} 次 AI 套话:")
            for s in det.get("samples", []):
                print(f"        · {s}")
        elif name == "vocab" and det.get("total_hits"):
            top = det.get("top", [])
            if top:
                top_str = ", ".join(f"{w}×{c}" for w, c in top)
                print(f"      AI 词密度 {det['density_per_1k']}/千字: {top_str}")
        elif name == "burstiness" and det.get("cv") is not None:
            print(f"      句长均值 {det['mean_length']} 字,CV={det['cv']}")
        elif name == "structural" and det.get("hit_count"):
            print(f"      教科书枚举命中 {det['hit_count']} 次")
        elif name in ("style", "artifacts") and d["score"]:
            print(f"      {json.dumps({k: v for k, v in det.items() if k != 'hits'}, ensure_ascii=False)}")
            for h in det.get("hits", []):
                print(f"        · [{h['id']}] L{h['line']} {h['excerpt']}")
    _print_hard_fail(report)
    print("=" * 60)
    if report.get("advisory"):
        _print_advisory(report["advisory"])


def _newspic_parts(brief_md: str) -> tuple:
    """贴图 brief:返回 (短文本, 标题+要点 lint 结果, front matter 标题)。小节别名与 publish_from_brief 一致;要点按零容忍位置检查。"""
    from newspic_build import parse_brief, card_points  # 懒加载:newspic_build 顶层依赖 yaml/config
    parsed = parse_brief(brief_md)
    sections, title = parsed["sections"], str((parsed["frontmatter"] or {}).get("title") or "")
    extra = [{**a, "kind": "title", "message": f"标题:{a['message']}"} for a in zh_tells.lint("", title=title)
             if a["kind"] == "title"] if title.strip() else []
    extra += [{**a, "kind": "point", "message": f"要点 {i}:{a['message']}"}
              for i, p in enumerate(card_points(sections), 1) for a in zh_tells.lint("", title=p)]
    return (sections.get("短文本") or sections.get("短描述") or "").strip(), extra, title


def _title_hard_gate(full: dict, title: str):
    """贴图 brief 的 front matter 标题不进打分,这里单独过同形字硬门(与 publish._newspic_title_gate 同口径)。"""
    adv = [{**a, "where": "title"} for a in zh_tells.find_adversarial_chars(title)]
    if adv:
        full["adversarial"] = adv + full["adversarial"]
        full["hard_fail"] = "adversarial_chars"
        full["verdict"] = HARD_FAIL_VERDICT


def _write_side_files(args, full: dict):
    out_dir = Path(args.input).parent
    if args.save_lint:   # 不写 cap:文章目录里不留"每种写法能用几次"的配额表(E6)
        lint = {"counts": full["rule_counts"], "advisory": [{k: v for k, v in a.items() if k != "cap"} for a in full["advisory"]],
                "artifacts": full["dimensions"]["artifacts"]["detail"]["hits"],
                "hard_fail": full["hard_fail"], "adversarial": full["adversarial"]}
        (out_dir / "ai_lint.json").write_text(json.dumps(lint, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.log_template:
        log = out_dir / humanize_log.LOG_NAME
        old = log.read_text(encoding="utf-8") if log.exists() else None
        log.write_text(humanize_log.merge_template(full["advisory"], old), encoding="utf-8")


LOG_GAP_PRINT_MAX = 30     # --check-log 最多逐条列出的缺口数


def _check_log(input_path: str, md: str, full: dict) -> bool:
    """--check-log:与 publish 门禁同一套 humanize_log 覆盖检查(含出处核对),离线验证 3.5 的退出条件。"""
    gaps, log_path = humanize_log.check_article(input_path, full["advisory"], md)
    if not gaps:
        print(f"humanize_log 覆盖检查:通过({len(full['advisory'])} 条 advisory 均已改掉或有有效的「保留」行)")
        return True
    missing = "" if log_path.exists() else ",文件不存在,先用 --log-template 生成"
    print(f"humanize_log 覆盖检查:未通过({log_path}{missing})")
    for g in gaps[:LOG_GAP_PRINT_MAX]:
        excerpt = " ".join(str(g.get("excerpt", "")).split())
        print(f"  · [{g['id']}] L{g.get('line', '')} {excerpt} —— {g.get('message', '')}")
    return False


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI 味检测器")
    parser.add_argument("input", help="Markdown 文件路径")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help=f"失败阈值(默认 {DEFAULT_THRESHOLD})。总分 >= 阈值则 exit 1")
    parser.add_argument("--mode", choices=["news", "newspic"], default="news",
                        help="检测模式: news(长文,默认)/ newspic(贴图短文本)")
    parser.add_argument("--brief", help="brief.md 路径:用其 experiences 核对第一人称亲历与引语出处")
    parser.add_argument("--account", help="账号 key(如 main / tech):启用该账号的禁用口头禅检查")
    parser.add_argument("--title", help="标题(零容忍检查否定对照/价值宣告)")
    parser.add_argument("--digest", help="摘要(零容忍检查否定对照/价值宣告);缺省按 publish 同一口径从正文提取")
    parser.add_argument("--advisory", action="store_true",
                        help="只打印 advisory 清单、artifacts 和同形字硬门(退出码按总分和同形字硬门)")
    parser.add_argument("--log-template", action="store_true", help="在输入文件同目录生成/补全 humanize_log.md 骨架")
    parser.add_argument("--save-lint", action="store_true", help="在输入文件同目录写 ai_lint.json")
    parser.add_argument("--check-log", action="store_true",
                        help="按 publish 门禁同一口径核对同目录 humanize_log.md;有未覆盖条目则 exit 1")
    parser.add_argument("--newspic-brief", action="store_true", help="输入是贴图 brief.md:短文本按 newspic 打分,要点+短文本跑 lint")
    return parser


def main():
    args = _build_parser().parse_args()
    md = Path(args.input).read_text(encoding="utf-8")
    ctx = {"brief_text": Path(args.brief).read_text(encoding="utf-8") if args.brief else None,
           "account": args.account, "title": args.title, "digest": args.digest}
    extra, fm_title = [], ""
    if args.newspic_brief:
        md, extra, fm_title = _newspic_parts(md)
        args.mode = "newspic"
    elif args.digest is None:   # E5:默认摘要与 publish 发出去的那份完全一致;排版卡等不发布的稿显式传 --digest ""
        from article_meta import extract_digest_from_markdown
        ctx["digest"] = extract_digest_from_markdown(zh_chars.strip_zero_width(md)[0])
    full = analyze(md, mode=args.mode, threshold=args.threshold, **ctx)
    full["advisory"] = extra + full["advisory"]
    if fm_title and not args.title:
        _title_hard_gate(full, fm_title)
    _write_side_files(args, full)
    if args.json:
        print(json.dumps(full, ensure_ascii=False, indent=2))
    elif args.advisory:
        _print_advisory(full["advisory"], full["dimensions"]["artifacts"]["detail"]["hits"])
        _print_hard_fail(full)
    elif not args.check_log:
        _pretty_print(full)
    log_ok = _check_log(args.input, md, full) if args.check_log else True
    sys.exit(0 if _passed(full, args.threshold) and log_ok else 1)


if __name__ == "__main__":
    main()
