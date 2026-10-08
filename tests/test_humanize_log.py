"""humanize_log:log 骨架、解析、按规则覆盖(density/position)、防糊弄、保留上限,以及 brief 解析与出处覆盖。"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import humanize_log as HL

ADV = [
    {"id": "neg_contrast", "label": "否定对照/翻案", "line": 32, "kind": "para", "excerpt": "这不是还没做完,这是设计。",
     "count": 3, "cap": 1, "scope": "density", "message": "否定对照/翻案:全文 3 处"},
    {"id": "neg_contrast", "label": "否定对照/翻案", "line": 40, "kind": "para", "excerpt": "它不是工具,而是同事。",
     "count": 3, "cap": 1, "scope": "density", "message": "否定对照/翻案:全文 3 处"},
    {"id": "fake_reaction", "label": "编造的反应", "line": 24, "kind": "para", "excerpt": "这个开头我看了三遍。",
     "count": 1, "cap": 0, "scope": "position", "message": "编造的反应"},
]
REASON = "引用 brief 第 3 行原话"


def _log(rows):
    return HL.render_template([]) + "".join(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} |\n" for r in rows)


def _gap_ids(advisory, log, han=None):
    return [u["id"] for u in HL.uncovered(advisory, log, han=han)]


def test_template_one_row_per_density_rule_and_per_position_hit():
    text = HL.render_template(ADV)
    assert "| 规则 | 行 | 原文 | 处理 | 理由/出处 |" in text and "上限" not in text
    rows = HL.parse_log(text)
    assert [(r["id"], r["line"], r["excerpt"]) for r in rows] == [
        ("neg_contrast", "全文 3 处", "*"), ("fake_reaction", "24", "这个开头我看了三遍。")]
    assert all(r["action"] == "" and r["reason"] == "" for r in rows)


def test_pipe_in_excerpt_escaped():
    text = HL.render_template([{**ADV[2], "excerpt": "a|b"}])
    assert HL.parse_log(text)[0]["excerpt"] == "a|b"


def test_uncovered_without_log_returns_all():
    assert _gap_ids(ADV, "") == ["neg_contrast", "neg_contrast", "fake_reaction"]


@pytest.mark.parametrize("density_excerpt", ["*", "它不是工具, 而是同事"])
def test_one_density_row_covers_rule(density_excerpt):
    log = _log([("neg_contrast", "全文 3 处", density_excerpt, "保留", REASON),
                ("fake_reaction", 24, "这个开头我看了 三遍。", "保留", "brief experiences 第 1 条")])
    assert HL.uncovered(ADV, log) == []


@pytest.mark.parametrize("row", [
    ("fake_reaction", 24, "遍", "保留", REASON),                       # 单字原文糊弄
    ("fake_reaction", 24, "这个开头我看了三遍。", "不保留", REASON),
    ("fake_reaction", 24, "这个开头我看了三遍。", "未保留", REASON),
    ("fake_reaction", 24, "这个开头我看了三遍。", "改", REASON),          # 删/改了但 lint 仍报 → 未覆盖
    ("fake_reaction", 24, "这个开头我看了三遍。", "保留", "-"),
    ("fake_reaction", 24, "这个开头我看了三遍。", "保留", "无"),
    ("fake_reaction", 24, "这个开头我看了三遍。", "保留", "N/A N/A"),
    ("fake_reaction", 24, "这个开头我看了三遍。", "保留", "有出处"),     # 理由太短
    ("salience", 24, "这个开头我看了三遍。", "保留", REASON),            # id 不对
])
def test_position_row_cannot_be_gamed(row):
    assert _gap_ids([ADV[2]], _log([row])) == ["fake_reaction"]


def test_keep_overflow_scales_with_length_and_skips_unsourced():
    many = [{**ADV[2], "line": i, "excerpt": f"第{i}句我看了三遍。"} for i in range(5)]
    log = _log([("fake_reaction", i, f"第{i}句我看了三遍。", "保留", REASON) for i in range(5)])
    over = HL.uncovered(many, log, han=1500)
    assert [u["id"] for u in over] == ["_keep_overflow"] and over[0]["cap"] == HL.KEEP_MIN
    assert HL.uncovered(many, log, han=6000) == []
    src = [{**m, "id": "unsourced_quote"} for m in many]
    src_log = log.replace("fake_reaction", "unsourced_quote").replace(REASON, "见 https://example.com/thread 原帖")
    assert HL.uncovered(src, src_log, han=1500) == []


def _salience(words):
    return [{**ADV[2], "id": "salience", "line": i, "excerpt": f"真正的{w}"} for i, w in enumerate(words)]


def test_joined_excerpt_covers_only_one_position_hit():
    """E2:一条 position 保留行最多覆盖一条命中;拼接原文只顶一条,其余仍未覆盖。"""
    hits = _salience(["难点", "关键", "瓶颈", "代价"])
    joined = _log([("salience", 3, "".join(h["excerpt"] for h in hits), "保留", REASON)])
    assert _gap_ids(hits, joined, han=300) == ["salience"] * 3
    honest = _log([("salience", h["line"], h["excerpt"], "保留", REASON) for h in hits])
    assert _gap_ids(hits, honest, han=300) == ["_keep_overflow"]


def test_duplicate_hits_need_one_row_each():
    hits = [{**ADV[2], "line": 3}, {**ADV[2], "line": 9}]
    one = _log([("fake_reaction", 3, ADV[2]["excerpt"], "保留", REASON)])
    assert _gap_ids(hits, one) == ["fake_reaction"]
    assert _gap_ids(hits, one + "| fake_reaction | 9 | 这个开头我看了三遍。 | 保留 | 引用 brief 第 4 行原话 |\n") == []


def test_greedy_prefers_closest_row():
    hits = _salience(["难点", "难点在缓存"])
    log = _log([("salience", 1, "真正的难点在缓存", "保留", REASON), ("salience", 0, "真正的难点", "保留", REASON)])
    assert _gap_ids(hits, log) == []


UNSOURCED = {**ADV[2], "id": "unsourced_experience", "excerpt": "我上周数了一遍自己的调用日志。"}
QUOTE = {**ADV[2], "id": "unsourced_quote", "excerpt": "同事说调用日志里全是重复请求"}
BRIEF = ('---\ntopic: x\nexperiences:\n  - "上周 | 数了一遍自己的调用日志 | 发现重复请求"\n'
         'materials:\n  - "调用日志里的重复请求 | logs/2026-08.jsonl"\n---\n')
RESEARCH = "## 访谈\n同事说调用日志里全是重复请求,一天上千条。\n"


def _covered(item, reason, **ctx):
    log = _log([(item["id"], 5, item["excerpt"], "保留", reason)])
    return HL.uncovered([item], log, han=1000, **ctx) == []


@pytest.mark.parametrize("reason,ok", [
    ("作者本人的真实经历", False), ("用户口头说过这件事", False), ("brief 里写过这个", False), ("briefing 会上提过", False),
    ("brief L4 用户提供", True), ("brief 第 4 行原话", True), ("见 brief experiences 第 1 条", True),
    ("brief L2 用户提供", False),            # 指向 topic 行,和命中对不上
    ("brief L12 用户提供", False),           # 行号越界
    ("https://example.com/post 原文", False),  # 链接证明不了是用户亲历
    ("research.md 里的访谈记录", False), ("issue #6235 的讨论", False), ("@someone 在推上说的", False),
])
def test_unsourced_experience_keep_needs_matching_brief_line(reason, ok):
    """亲历只认 brief:指向的行 / experiences 条目必须存在且和命中原文对得上。"""
    assert _covered(UNSOURCED, reason, brief_text=BRIEF, research_text=RESEARCH) is ok


def test_unsourced_experience_brief_reason_fails_without_brief():
    assert not _covered(UNSOURCED, "brief L4 用户提供")


@pytest.mark.parametrize("reason,ok", [
    ("https://example.com/post 原文", True), ("issue #6235 的讨论", True), ("@someone 在推上说的", True),
    ("research.md 里的访谈记录", True), ("brief materials 第 1 条", True), ("同事私下说的", False),
])
def test_unsourced_quote_keep_sources(reason, ok):
    assert _covered(QUOTE, reason, brief_text=BRIEF, research_text=RESEARCH) is ok


def test_research_reason_needs_matching_research_text():
    assert not _covered(QUOTE, "research.md 里的访谈记录", research_text="## 无关内容\n天气不错。\n")


def test_merge_template_appends_row_for_duplicate_hit():
    hits = [{**ADV[2], "line": 3}, {**ADV[2], "line": 9}]
    existing = _log([("fake_reaction", 3, ADV[2]["excerpt"], "保留", REASON)])
    assert [r["line"] for r in HL.parse_log(HL.merge_template(hits, existing))] == ["3", "9"]


def test_merge_template_appends_only_new_rows():
    existing = _log([("neg_contrast", "全文 3 处", "*", "保留", REASON)])
    rows = HL.parse_log(HL.merge_template(ADV, existing))
    assert [r["id"] for r in rows] == ["neg_contrast", "fake_reaction"] and rows[0]["reason"] == REASON
    assert HL.merge_template(ADV, None) == HL.render_template(ADV)


# ---------- brief ----------

def test_parse_brief_front_matter_and_section():
    brief = ("---\ntopic: x\nexperiences:\n  - 上周数了一遍调用日志\n  - 无\ndialogue: true\n---\n\n"
             "## 一手真实细节\n\n- 账单 27.8 亿 token\n\n## 结构规划\n\n- 开篇\n")
    b = HL.parse_brief(brief)
    assert b["experiences"] == ["上周数了一遍调用日志", "账单 27.8 亿 token"]
    assert b["dialogue"] is True and b["faq"] is False
    assert HL.parse_brief(None) == {"experiences": [], "dialogue": False, "faq": False, "endings": []}


@pytest.mark.parametrize("fm", [
    "experiences:   # 注释\n  - 上周迁了 Redis\n", "experiences:\n- 上周迁了 Redis\n", 'experiences: ["上周迁了 Redis"]\n',
    "# 只收亲历\nexperiences:\n  # 一条一行\n  - \"上周迁了 Redis\"   # 行尾注释\n",
])
def test_parse_brief_yaml_variants(fm):
    b = HL.parse_brief(f"---\n{fm}materials:   # 来源\n  - 文档 | https://x.y\n---\n")
    assert b["experiences"] == ["上周迁了 Redis"]


def test_parse_brief_matches_skill_md_template():
    """防 SKILL.md 阶段一模板与解析器再漂移:直接取 SKILL.md 里含 experiences 的 yaml 块,填上示例值。"""
    skill = (Path(__file__).parent.parent / "SKILL.md").read_text(encoding="utf-8")
    block = next(b for b in re.findall(r"```yaml\n(.*?)```", skill, re.S) if "experiences:" in b)
    filled = re.sub(r"<[^>\n]*>", "示例", block)
    exps = HL.parse_brief(filled)["experiences"]
    assert exps and all("示例" in e for e in exps) and not any("http" in e or "来源" in e for e in exps)


def test_parse_brief_series_ending():
    assert HL.parse_brief("---\nseries_ending: \"下期见\"   # 固定结尾\n---\n")["endings"] == ["下期见"]


def test_covered_requires_shared_tokens():
    lines = ["上周数了一遍自己的调用日志,184 个子代理"]
    assert HL.covered("我上周数了一遍自己的调用日志。", lines)
    assert not HL.covered("我去年在一家创业公司做过推荐系统。", lines)
    assert not HL.covered("任何句子", [])
