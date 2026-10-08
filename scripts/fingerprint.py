#!/usr/bin/env python3
"""跨篇指纹(DC-13 修订版 + critic):同账号最近几篇的标题/摘要/开头/结尾/小标题/口头禅族/喻体重复。只出 advisory,
永远 exit 0(DR-3),不进总分与 publish gate。TICS 等词表直接从 zh_tells / zh_rules 导入,缺口补进真源;不给 article 时只列最近 N 篇特征。
    python3 scripts/fingerprint.py [article.md] [--account main|tech|all] [--last 5] [--root mp-articles] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import zh_rules as R
import zh_sources
import zh_tells
import zh_text as T
from fingerprint_render import render

ROOT = Path(__file__).resolve().parent.parent / "mp-articles"
DEFAULT_ACCOUNT, DEFAULT_LAST = "main", 5
LATEST = "99999999"                      # 目录名不带日期的当前稿视为最新
MIN_HISTORY, STREAK, RECENT_ANY = 2, 3, 3  # 历史 <2 篇只出特征;连续 3 篇(含当前)同形状才报;cta/金句结尾看最近 3 篇
TIC_WINDOW, TIC_MIN_DF = 5, 3            # 标记族:当前篇出现,且(最近 5 篇 + 当前)文档频率 ≥3
HEAD_KEY_MIN_HIST = 2                    # 小标题印章:最近 5 篇里至少 2 篇也有
CTA_SECTION_PARAS = 6                    # 最后一个 H2 小节里最多看 6 个正文段
H2_SIM_ALERT = 0.5                       # 修订 spec 实测 AI 两两 ≤0.10、真人固定栏目 0.35-0.46:只报近乎照搬
SHAPE_SHARE, SHAPE_MIN, SHORT_HEAD_HAN = 0.5, 2, 8
APHORISM_MAX_HAN, PUNCHLINE_HAN, PUNCHLINE_MAX_SENT = 24, (4, 24), 2
NUMBER_PILE_MIN, SAMPLE_MAX = 3, 3
BOILER_MAX_HAN = 40                      # 版尾套话只在短段里认,避免"在看""点赞"误删正文段
TIC_FAMILIES = ("candor_tic", "fake_reaction", "perf_imperfect", "cta_end", "salience", "staged")
NEUTRAL_SHAPES = ("short", "phrase", "mixed", "none")

_c = re.compile
_DATE = _c(r"(\d{4})-?(\d{2})-?(\d{2})")
BOILER = _c(r"^[（(]?(全文)?完[）)]?$|^(以上|END|-?\s*完\s*-?)[。.]?$|阅读原文|点赞|在看|关注(我|公众号)|二维码|版权声明|转载请"
            r"|^(?:下(?:周|期|次|篇)见|就这样吧?|共勉|感谢阅读|谢谢阅读)[。！!]?$")
CTA = _c(r"(?:如果|要是|假如)你?(?:今天|现在|这周)?只(?:做|打算做|想做|能做)一件事|(?:今天|现在|这周|明天|回头)[^。！？\n]{0,6}"
         r"(?:花|抽|留)(?:上|出)?\s*[一两三五十\d]+\s*分钟[^。！？\n]{0,12}(?:做|试|跑|翻|看|确认|检查|数)")
ENGAGE = _c(r"评论区(?:聊聊|见|告诉我|说说|留言|交流)|欢迎(?:在)?(?:评论区|留言)|你(?:会|打算)?(?:怎么)?选[？?]")
APHORISM = _c(r"(?:会|在)(?:变|过时|换|走).{0,10}不会|不是.{1,10}[，,]?是|才是|而是|比.{1,10}(?:更|管用|靠谱)")
APH_BAN = _c(r"[\dA-Za-z@“”\"「」『』]")
_COLON = r"(?<!\d)[：:]|[：:](?!\d)"     # 排除 10:30 这类时间
# 开头第一句:按顺序取第一个命中;数字开头排除日期电头,scene 句里必须有「我」
OPENING = (("number", _c(r"^\s*(?:`[^`]+`|\d(?!\d{1,3}\s*年|\d?\s*月\s*\d{1,2}\s*日))")), ("quote", _c(r"^\s*[“「\"『]")),
           ("question", _c(r"[？?]\s*$")),
           ("scene", _c(r"^(?=.*我)(?:上?周[一二三四五六日末]|上周|上个月|前两天|前几天|前阵子|那天|昨晚|昨天|凌晨|去年"
                        r"|今天(?:早上|凌晨|下午|晚上))|我.{0,6}(?:上周|那天|昨晚|前两天|前几天)")),
           ("staged", _c(r"^\s*(?:先看|先说|先甩|先摆|直接上)")))
TITLE_SHAPES = (("colon", _c(_COLON)), ("question", _c(r"[？?]")), ("comma_turn", _c(r"[一-鿿A-Za-z0-9][，,]\s*[一-鿿A-Za-z0-9]")))
DIGEST_SHAPES = (("number_pile", _c(r"(?:\d+(?:[.,]\d+)*(?:\D+|$)){%d}" % NUMBER_PILE_MIN)), ("turn", _c(r"但|却|然而|可是|换来的是|结果")),
                 ("question", _c(r"[？?]")))
H_SHAPES = (("question", _c(r"[？?]")), ("colon", _c(_COLON + "|——")), ("comma", _c(r"[，,]")), ("data", _c(r"\d")))
FUNC_OPEN = _c(r"^(?:开篇|引言|前言|导语|写在前面)(?:的话)?(?:[：:\s]|$)")
FUNC_CLOSE = _c(r"^(?:写在最后|写在后面|结语|结尾|尾声|总结|收尾|收个尾|最后(?:说两句|聊聊|的话|一点)?)(?:的话)?(?:[：:\s]|$)")
TPL_RX = _c(r"[一二两三四五六七八九十几\d]+\s*(个|条|层|点|件|大)[^，,：:\n]{0,4}?(坑|原因|放大器|关键|要点|误区|问题|教训|真相|细节)")
SIMILE = _c(r"(?<![好不想图影偶肖画录头镜])(?:就像|像是|好比|如同|犹如|仿佛|好似|像)(?:一[个位只台张条把块座家间种场本份]|个)?"
            r"(?P<v>(?![这那是我你他她它在])[一-鿿]{2,6}?)(?=一样|似的|那样|般|[，,。！？；：:、\s]|$)")
_IMG, _LINK = _c(r"!\[[^\]\n]*\]\([^)\n]*\)"), _c(r"\[([^\]\n]*)\]\([^)\n]*\)")
_FIELD = r"(?m)^[ \t]*(?:[-*][ \t]+)?(?:\*\*)?{k}(?:\*\*)?[ \t]*[:：][ \t]*(.+?)[ \t]*$"

# ---------- 单项分类 ----------
def date_key(name: str) -> str:
    return "".join(m.groups()) if (m := _DATE.match(name)) else ""

def opening_class(s: str) -> str:
    """首个正文段第一句:number/quote/question/scene/staged/other。"""
    return next((k for k, rx in OPENING if rx.search(s.strip())), "other")

def title_shape(title: str) -> list[str]:
    """标题形状:冒号揭晓/设问、问句、逗号反转(两段式)。"""
    return [k for k, rx in TITLE_SHAPES if rx.search(title)]

def digest_shape(digest: str) -> list[str]:
    """摘要形状:否定对照、价值宣告、数字堆叠、转折、问句。"""
    d = digest.strip()
    tags = ["neg_contrast"] if d and T.spans(R.NEG_CONTRAST + R.TIGHT_CONTRAST, d, literal=True) else []
    tags += ["salience"] if d and any(p.search(d) for p in R.SALIENCE) else []
    return tags + [k for k, rx in DIGEST_SHAPES if d and rx.search(d)]

def _is_func(h: str) -> bool:
    return bool(FUNC_OPEN.match(h.strip()) or FUNC_CLOSE.match(h.strip()))

def heading_keys(h2s: list[str]) -> list[str]:
    """小标题印章:开场族/收尾族(同义轮换归一)、N<量词><名词> 模板;其余命中 zh_rules.HEADING_TEMPLATE(钩子词表真源)的按族记。"""
    keys: set[str] = set()
    for h in (x.strip() for x in h2s):
        keys |= {k for k, rx in (("func:open", FUNC_OPEN), ("func:close", FUNC_CLOSE)) if rx.match(h)}
        tpl = {f"tpl:{m.group(1)}{m.group(2)}" for m in TPL_RX.finditer(h)}
        keys |= tpl or ({"tpl:heading_template"} if R.HEADING_TEMPLATE.search(h) else set())
    return sorted(keys)

def _is_short_head(h: str) -> bool:
    return T.han_count(h) <= SHORT_HEAD_HAN and not re.search(r"[A-Za-z]{3,}", h)

def heading_shape(h2s: list[str]) -> str:
    """非功能性 H2 的主导形状(占比 ≥50% 且 ≥2 个),否则 mixed。"""
    shapes = [next((k for k, rx in H_SHAPES if rx.search(h)), "short" if _is_short_head(h) else "phrase")
              for h in h2s if not _is_func(h)]
    top = max(sorted(set(shapes)), key=shapes.count) if shapes else "none"
    return top if not shapes or (shapes.count(top) >= SHAPE_MIN and shapes.count(top) / len(shapes) >= SHAPE_SHARE) else "mixed"

def h2_similarity(a: list[str], b: list[str]) -> float:
    """两组小标题的汉字二元组 Jaccard(专名、代码、数字不计入)。"""
    x, y = ({r[i:i + 2] for h in g for r in re.findall(r"[一-鿿]+", h) for i in range(len(r) - 1)} for g in (a, b))
    return len(x & y) / len(x | y) if x and y else 0.0

def _last_class(p: dict) -> str:
    """末段类别:engage/link_or_cmd/question/aphorism/punchline/other(punchline、engage 只记特征的来源见 DC-13)。"""
    t, han = p["text"], T.han_count(p["text"])
    checks = (("engage", ENGAGE.search(t)), ("link_or_cmd", re.search(r"https?://|`|github\.com", p["raw"])),
              ("question", re.search(r"[？?][)）]?\s*$", t)),
              ("aphorism", han <= APHORISM_MAX_HAN and not APH_BAN.search(t) and APHORISM.search(t)),
              ("punchline", PUNCHLINE_HAN[0] <= han <= PUNCHLINE_HAN[1] and len(T.split_sentences(t)) <= PUNCHLINE_MAX_SENT))
    return next((k for k, ok in checks if ok), "other")

def ending_tags(paras: list[dict]) -> list[str]:
    """结尾多标签:cta(最后一个 H2 小节最多 6 段内)+ 末段类别。"""
    if not paras:
        return []
    tail = [p for p in paras if p["section"] == paras[-1]["section"]][-CTA_SECTION_PARAS:]
    return (["cta"] if any(CTA.search(p["text"]) for p in tail) else []) + [_last_class(paras[-1])]

# ---------- 单篇特征 ----------
def plain_text(raw: str) -> str:
    return T.strip_markers(re.sub(r"(?m)^[ \t]*>[ \t]?", "", _LINK.sub(r"\1", _IMG.sub("", raw)))).strip()

def _prose(units: list[dict]) -> list[dict]:
    """正文段:只取 prose 段(标题/导语/引用/列表/表格/代码/图片已由 text_units 分开),去掉版尾套话。"""
    paras = [{"line": u["line"], "section": u["section"], "text": plain_text(u["raw"]), "raw": u["raw"]}
             for u in units if u["kind"] == "para"]
    return [p for p in paras if p["text"] and not (T.han_count(p["text"]) <= BOILER_MAX_HAN and BOILER.search(p["text"]))]

def _field(text: str, key: str, cut: bool) -> str | None:
    m = re.search(_FIELD.format(k=key), text)
    v = (re.split(r"[（(]", m.group(1), maxsplit=1)[0] if cut else m.group(1)) if m else ""
    return v.strip().strip("`\"' ") or None

def _meta(md: str, brief: Path) -> dict:
    """字段先看文章 front matter,再看同目录 brief.md(YAML 与 `- **key**:` 两种写法)。"""
    norm = T.normalize(md)
    texts = [norm[: len(norm) - len(T.strip_front_matter(norm))]] + ([brief.read_text(encoding="utf-8")] if brief.is_file() else [])
    keys = {"article_structure": True, "opening_hook": True, "series": True, "digest": False}
    return {k: next((v for t in texts for v in [_field(t, k, cut)] if v), None) for k, cut in keys.items()}

def _tic_features(md: str) -> dict:
    """标记族命中(按族计文档频率,不按字面)+ zh_tells 各规则命中计数(只写进 JSON)。"""
    by_id, _ = zh_tells.scan(md)
    tics = {f: list(dict.fromkeys(h.get("match") or h["excerpt"] for h in by_id[f])) for f in TIC_FAMILIES if by_id.get(f)}
    tics["echo"] = [h["excerpt"] for h in zh_tells.score_artifacts(md)[1]["hits"] if h["id"] == "instruction_echo"]
    body = T.mask_blocks(md)
    tics["research_act"] = [t for t in zh_tells.RESEARCH_TICS if t in body]  # 研究者动作族
    return {"tics": {k: v[:SAMPLE_MAX] for k, v in tics.items() if v}, "adv": {k: len(v) for k, v in by_id.items() if v}}

def features(path: Path) -> dict:
    md = path.read_text(encoding="utf-8")
    units, meta = T.text_units(md), _meta(md, path.parent / "brief.md")
    paras = _prose(units)
    h2 = [u["text"].strip() for u in units if u["kind"] == "heading" and u["raw"].lstrip().startswith("## ")]
    title = next((u["text"].strip() for u in units if u["kind"] == "title"), "")
    digest = meta["digest"] or next((plain_text(u["raw"]) for u in units if u["kind"] == "digest"), "")
    first = T.split_sentences(paras[0]["text"]) if paras else []
    return {"name": path.parent.name, "path": str(path), "date": date_key(path.parent.name), "title": title,
            "title_shape": title_shape(title), "digest": digest, "digest_shape": digest_shape(digest),
            "structure": meta["article_structure"], "hook": meta["opening_hook"],
            "series": None if zh_sources.unset(meta["series"]) else meta["series"],   # 无/none/<…> 占位 = 不是栏目
            "opening": opening_class(first[0]) if first else "other", "ending": ending_tags(paras),
            "h2": h2, "heading_keys": heading_keys(h2), "heading_shape": heading_shape(h2),
            "similes": list(dict.fromkeys(m["v"] for m in SIMILE.finditer("\n".join(p["text"] for p in paras)))),
            **_tic_features(md)}

# ---------- 历史窗口 ----------
def _sort_key(p: Path) -> tuple[str, str]:
    return date_key(p.parent.name), p.parent.name

def list_articles(root: Path, account: str) -> list[Path]:
    """按目录名里的日期(YYYY-MM-DD 与 YYYYMMDD 归一)排序,同一天按目录名。"""
    dirs = ([d for d in root.iterdir() if d.is_dir()] if account == "all" else [root / account]) if root.is_dir() else []
    return sorted((p for d in dirs if d.is_dir() for p in d.glob("*/article.md")), key=_sort_key)

def history_for(article: Path, root: Path, account: str, *, last: int = DEFAULT_LAST) -> list[Path]:
    cur = article.resolve()
    key = (date_key(cur.parent.name) or LATEST, cur.parent.name)
    hist = [p for p in list_articles(root, account) if p.resolve() != cur and _sort_key(p) < key]
    return hist[-last:] if last > 0 else []

# ---------- advisory ----------
def _tags(v) -> set:
    return set(v) if isinstance(v, (list, dict)) else ({v} if v else set())

def _adv(aid: str, message: str, docs: list[dict]) -> dict:
    return {"id": aid, "message": message, "articles": [d["name"] for d in docs]}

def _same_series(cur: dict, h: dict) -> bool:
    return bool(cur["series"]) and h["series"] == cur["series"]

# (字段, advisory id, 中文名, 不报的标签, 同 series 是否豁免);cta/金句结尾另用"最近 3 篇任一篇"的更宽条件
STREAK_FIELDS = (("hook", "opening_streak", "开头钩子", (), True), ("opening", "opening_streak", "开头类型", ("other",), True),
                 ("title_shape", "title_shape_streak", "标题形状", (), True),
                 ("digest_shape", "digest_shape_streak", "摘要形状", (), True),
                 ("heading_shape", "heading_shape_streak", "小标题形状", NEUTRAL_SHAPES, True),
                 ("ending", "ending_streak", "结尾类别", ("other", "cta", "aphorism"), False))

def _streaks(cur: dict, hist: list[dict]) -> list[dict]:
    prev, out = hist[-(STREAK - 1):], []
    for field, aid, label, neutral, exempt in STREAK_FIELDS:
        common = set() if exempt and any(_same_series(cur, h) for h in prev) else _tags(cur[field]) - set(neutral)
        for h in prev:
            common &= _tags(h[field])
        out += [_adv(aid, f"{label} {t} 连续 {STREAK} 篇相同", prev) for t in sorted(common)]
    return out

def _repeat(cur: dict, window: list[dict], spec: tuple) -> list[dict]:
    """spec=(字段, advisory id, 中文名, 至少几篇也有, 只看这些标签);aid 可带 {tag}。"""
    (field, aid, label, least, only), out = spec, []
    for tag in sorted(t for t in _tags(cur[field]) if not only or t in only):
        docs = [h for h in window if tag in _tags(h[field])]
        cur_eg = f"(当前:{'/'.join(cur[field][tag])})" if isinstance(cur[field], dict) else ""
        msg = f"{label} {tag}{cur_eg}:最近 {len(window)} 篇里 {len(docs)} 篇也有"
        out += [_adv(aid.format(tag=tag), msg, docs)] if len(docs) >= least else []
    return out

def _h2_similar(cur: dict, window: list[dict]) -> list[dict]:
    content = [h for h in cur["h2"] if not _is_func(h)]
    sims = [(h2_similarity(content, [x for x in h["h2"] if not _is_func(x)]), h) for h in window]
    score, doc = max(sims, key=lambda s: s[0], default=(0, None))
    return [_adv("h2_similar", f"小标题组与 {doc['name']} 的字二元组 Jaccard {score:.2f}", [doc])] if score >= H2_SIM_ALERT else []

def _combo(cur: dict, recent: list[dict]) -> list[dict]:
    combo = (cur["structure"], cur["hook"])
    docs = [h for h in recent if all(combo) and (h["structure"], h["hook"]) == combo]
    return [_adv("combo_repeat", f"结构+钩子组合 {combo[0]}/{combo[1]} 与最近 {RECENT_ANY} 篇重复", docs)] if docs else []

def advisories(cur: dict, hist: list[dict]) -> list[dict]:
    if len(hist) < MIN_HISTORY:
        return []
    recent, window = hist[-RECENT_ANY:], hist[-TIC_WINDOW:]
    free = [h for h in window if not _same_series(cur, h)]   # 同 series 栏目之间不比小标题
    reps = ((recent, ("ending", "ending_{tag}", "结尾", 1, ("cta", "aphorism"))),
            (window, ("tics", "tic_family", "口头禅族", TIC_MIN_DF - 1, ())),
            (free, ("heading_keys", "heading_key", "小标题印章", HEAD_KEY_MIN_HIST, ())),
            (window, ("similes", "simile_repeat", "喻体", 1, ())))
    repeats = [a for w, spec in reps for a in _repeat(cur, w, spec)]
    return _streaks(cur, hist) + repeats + _h2_similar(cur, free) + _combo(cur, recent)

# ---------- 入口 ----------
def run(article: Path | None, account: str, root: Path, *, last: int = DEFAULT_LAST) -> dict:
    hist = history_for(article, root, account, last=last) if article else (list_articles(root, account)[-last:] if last > 0 else [])
    notes: list[str] = []
    cur = features(article) if article else None
    hist_f: list[dict] = []
    for p in hist:   # 坏稿(编码错/读不了)只跳过这一篇并警告;当前篇读失败仍交给 main 报「未执行」
        try:
            hist_f.append(features(p))
        except (OSError, UnicodeDecodeError) as e:
            notes.append(f"警告:跳过历史稿 {p}:{e}")
    notes += [f"找不到 {root / account}"] if account != "all" and not (root / account).is_dir() else []
    notes += [f"历史篇少于 {MIN_HISTORY} 篇,只输出特征"] if cur and len(hist_f) < MIN_HISTORY else []
    return {"account": account, "root": str(root), "current": cur, "history": hist_f,
            "advisories": advisories(cur, hist_f) if cur else [], "notes": notes}

def _infer_account(article: Path | None, root: Path) -> str:
    acct = article.resolve().parent.parent.name if article else ""
    return acct if acct and (root / acct).is_dir() else DEFAULT_ACCOUNT

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="跨篇指纹:只出 advisory,永远 exit 0")
    ap.add_argument("article", nargs="?", help="当前文章;不给时只列最近 N 篇特征")
    ap.add_argument("--account", help="main | tech | all;缺省按文章路径推断,否则 main")
    ap.add_argument("--last", type=int, default=DEFAULT_LAST)
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--json", action="store_true")
    try:
        a = ap.parse_args(argv)
        root, article = Path(a.root), Path(a.article) if a.article else None
        if article and not article.is_file():
            raise FileNotFoundError(f"找不到文章:{article}")
        res = run(article, a.account or _infer_account(article, root), root, last=a.last)
    except SystemExit:
        return 0
    except (OSError, UnicodeDecodeError) as e:
        print(f"fingerprint 未执行:{e}")
        return 0
    print(json.dumps(res, ensure_ascii=False, indent=2) if a.json else render(res))
    return 0

if __name__ == "__main__":
    sys.exit(main())
