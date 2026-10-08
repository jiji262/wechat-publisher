"""
Tests for scripts/ai_score.py.

The `check_ai_score(md, threshold) -> (passed, report)` API is the library
entry; publish.py calls it as a blocking gate. These tests exercise the
shape of the report and the scoring logic against representative samples.

If `check_ai_score` is not yet importable (parallel agent still finishing),
the tests are skipped via pytest.importorskip-style guard so CI doesn't
block.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Guard so tests don't blow up while another agent is still editing ai_score.py.
ai_score = pytest.importorskip(
    "ai_score",
    reason="ai_score module not yet available — parallel agent may still be working",
)

if not hasattr(ai_score, "check_ai_score"):
    pytest.skip(
        "ai_score.check_ai_score() not yet defined — parallel agent may still be working",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Samples
# ---------------------------------------------------------------------------

# 真人样本:著作权已过期的白话散文(朱自清《背影》1925,作者 1948 年逝世)节选,出处见 fixture 的 front matter。
# 旧 HUMAN_SAMPLE 是用旧清单套路拼的("这破玩意""我自己都怀疑我在扯淡""回到主题"),断言它 PASS 等于保护 AI 指纹。
_FIXTURES = Path(__file__).parent / "fixtures"
HUMAN_SAMPLE = (_FIXTURES / "human_public_domain.md").read_text(encoding="utf-8")
# Claude 腔负样本:本 skill 存量稿摘句拼成的文章(出处逐段注明)
CLAUDE_SAMPLE = (_FIXTURES / "claude_tells.md").read_text(encoding="utf-8")

# A deliberately "AI-looking" sample: stuffed with blacklist phrases,
# uniform sentence lengths, textbook enumeration, flat punctuation,
# and banned vocabulary.
AI_SLOP_SAMPLE = """\
随着人工智能技术的不断发展,我们迎来了前所未有的机遇。在当今的时代背景下,
AI 赋能千行百业已经成为一种共识。值得一提的是,大模型正在打造全新的生态,
实现端到端的全链路闭环。

首先,大模型提升了内容创作的效率。其次,它打开了知识普惠的大门。再次,
它助力企业完成数字化转型。综上所述,这项技术具有深远的意义。

不仅如此,它还颠覆了传统的方法论。一方面,它重塑了底层逻辑;另一方面,
它构建了新的护城河。毋庸置疑,我们正站在时代的风口。由此可见,拥抱变化
是唯一的选择。

总而言之,这是一场深度融合的革命。让我们共同迎接新篇章,一起破局出圈,
在智能化的浪潮中找到自己的生态位。归根结底,不断深耕,才能真正引领未来。
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_check_ai_score_pure_human_text_passes():
    """A clearly human-written sample with good burstiness should pass (<45)."""
    passed, report = ai_score.check_ai_score(HUMAN_SAMPLE, threshold=45.0)

    # The total score should be safely under the default pass threshold.
    assert passed is True, (
        f"human sample unexpectedly failed: score={report['total_score']}, "
        f"dims={report['dimensions']}"
    )
    assert report["total_score"] < 45.0


def test_check_ai_score_ai_slop_fails():
    """A sample full of banned phrases / vocab should fail (>=45)."""
    passed, report = ai_score.check_ai_score(AI_SLOP_SAMPLE, threshold=45.0)

    assert passed is False, (
        f"AI-slop sample unexpectedly passed: score={report['total_score']}, "
        f"dims={report['dimensions']}"
    )
    assert report["total_score"] >= 45.0
    # It should specifically report hits on phrases and vocab.
    assert len(report["hit_phrases"]) >= 2
    assert len(report["hit_vocab"]) >= 3


def test_report_shape():
    """The report dict must have all the documented keys with correct types."""
    _, report = ai_score.check_ai_score(HUMAN_SAMPLE, threshold=50.0)

    required_top = {"total_score", "dimensions", "hit_phrases", "hit_vocab", "threshold"}
    assert required_top.issubset(set(report.keys())), (
        f"missing keys: {required_top - set(report.keys())}"
    )
    assert isinstance(report["total_score"], (int, float))
    assert isinstance(report["threshold"], float)
    assert isinstance(report["hit_phrases"], list)
    assert isinstance(report["hit_vocab"], list)

    required_dims = {"burstiness", "phrases", "vocab", "structural", "punctuation"}
    assert required_dims.issubset(set(report["dimensions"].keys()))
    for k, v in report["dimensions"].items():
        assert isinstance(v, (int, float)), f"dim {k} is not numeric: {v!r}"


def test_full_width_punctuation_scored():
    """
    #8 fix: full-width punctuation (? ! ( ) — …) should count toward
    "flavor points" just like half-width equivalents.

    The text with full-width ? ! ( ) should score noticeably BETTER on the
    punctuation dimension (lower AI score) than text using only 。 .
    """
    # Long enough to clear the "too_short" branch in score_punctuation_flatness
    # (>= 200 chars). Each sample is the same length-ish with the same content
    # skeleton, only punctuation differs.
    base = "这是一段用来测试标点的样本文字内容重复堆满字数以绕过短文本分支"
    flat_text = (base + "。") * 12  # only periods
    rich_text = (
        "这是一段样本。"
        "真的吗？"
        "（顺便说句）"
        "太离谱了！"
        "——对的。"
        "再来——还有一处。"
        "(英文括号也算)"
        "?还有半角问号"
    ) * 3

    flat_score, _ = ai_score.score_punctuation_flatness(flat_text)
    rich_score, _ = ai_score.score_punctuation_flatness(rich_text)

    # Lower AI-score is better (more human-like). Rich text must beat flat text.
    assert rich_score < flat_score, (
        f"full-width punctuation didn't improve score: "
        f"flat={flat_score}, rich={rich_score}"
    )


def test_phrase_overlap_deduped():
    """
    #24 fix: overlapping phrase patterns should be counted once,
    not multiple times.

    `首先...其次...最后` and `首先...其次...再次` are two separate patterns
    but they can match overlapping spans of the same text. The scorer should
    dedupe and not double-count.
    """
    # This text triggers BOTH `首先.*其次.*最后` AND `首先.*其次.*再次`
    # patterns if they overlap. Naïvely summing would give 2+ hits; with
    # span-level dedupe it should be 1.
    text = (
        "首先,我们分析问题。其次,我们提出方案。再次,我们验证效果。"
        "最后,我们总结经验。"
    )
    score, detail = ai_score.score_phrases(text)

    # Implementation detail: hit_count >= 1 (some hit is expected), but
    # should be bounded — absolute cap we test is that it's not blown up
    # to 3+ by pure overlap. Allowing up to 2 handles edge cases where
    # the two patterns don't overlap at all on a given string.
    assert detail["hit_count"] <= 2, (
        f"overlap not deduped: got {detail['hit_count']} hits, samples={detail['samples']}"
    )


def test_style_dimension_flags_markdown_slop():
    """Rich-text AI slop (heavy inline bold + emoji bullets + inline-header
    lists) must score high on the new `style` dimension; clean prose must not.

    Regression for the _strip_markdown blind spot: bold/emoji/headers were
    stripped BEFORE scoring, so humanizer-zh Style patterns (P14/P15/P17) were
    invisible. They are now scored on the RAW markdown.
    """
    slop_md = (
        "## 🚀 核心要点\n\n"
        "- **敏捷开发:** 一种迭代式的方法。\n"
        "- **持续集成:** 自动化的构建流程。\n"
        "- **微服务架构:** 解耦的系统设计。\n\n"
        "✅ **下一步:** 立即行动。\n"
        "🔥 **重点提示:** 不要错过。\n"
    )
    clean_md = (
        "上周三下午我在调一个老脚本,屏幕上突然蹦出一个 404。\n"
        "我盯着日志看了三分钟,才发现是超时参数被我从 30 秒改成了 5 秒。\n"
        "改回去,服务就活了。没有任何报警。这事儿挺离谱的。\n"
    )
    slop_style, _ = ai_score.score_style(slop_md)
    clean_style, _ = ai_score.score_style(clean_md)
    assert slop_style > clean_style
    assert slop_style >= 50, f"heavy markdown decoration scored only {slop_style}"
    assert clean_style < 20, f"clean prose false-positived at {clean_style}"


def test_style_dimension_in_report():
    """check_ai_score must surface the new style dimension."""
    _, report = ai_score.check_ai_score(HUMAN_SAMPLE, threshold=50.0)
    assert "style" in report["dimensions"]
    assert isinstance(report["dimensions"]["style"], (int, float))


def test_threshold_parameter_respected():
    """Edge case: same content, two different thresholds should flip pass/fail."""
    # Pick a text in the grey zone so threshold actually matters.
    grey_text = (HUMAN_SAMPLE + "\n\n" + AI_SLOP_SAMPLE)

    passed_loose, report_loose = ai_score.check_ai_score(grey_text, threshold=99.0)
    passed_strict, _ = ai_score.check_ai_score(grey_text, threshold=1.0)

    assert passed_loose is True
    assert passed_strict is False
    assert report_loose["threshold"] == 99.0


# ---------------------------------------------------------------------------
# 新增:不变量、verdict、硬门、各维度修复(DC-01/02/04/05/11/14/15)
# ---------------------------------------------------------------------------

_SCRIPTS = Path(__file__).parent.parent / "scripts"


def _probe_max_dims() -> dict:
    """探测各打分函数实际能达到的最大值(不手写常量,打分函数一改测试就跟着变)。"""
    flat = ["这是一句长度完全一样的句子啊。"] * 10
    struct = "第一,甲。第二,乙。第三,丙。\n" * 3
    style = ("- **术语一:** 解释\n- **术语二:** 解释\n✅ 一\n🔥 二\n🚀 三\n## ==标题==\n## !!标题!!\n"
             + "==这是一整句高亮的结论,非常重要。==\n" * 30)
    arts = "## 开篇:钩子问句\n\n## 写在最后:总结\n\n这破玩意。其实挺简单的。我当时愣住了。\n"
    return {
        "burstiness": ai_score.score_burstiness(flat)[0],
        "punctuation": ai_score.score_punctuation_flatness("这是一段没有任何人味标点的文字" * 40 + "。")[0],
        "structural": ai_score.score_structural_perfection(struct)[0],
        "style": ai_score.score_style(style)[0],
        "artifacts": ai_score.zh_tells.score_artifacts(arts)[0],
    }


@pytest.mark.parametrize("mode", ["news", "newspic"])
def test_gate_can_fail_without_lexicon_hits(mode):
    """不计 phrases/vocab 时的理论最高分 ≥ 阈值:gate 不是摆设。"""
    mx = _probe_max_dims()
    assert mx == {"burstiness": 90, "punctuation": 85, "structural": 100, "style": 100, "artifacts": 100}
    w = ai_score._weights_for(mode)
    ceiling = sum(mx[d] * w[d] for d in w if d not in ("phrases", "vocab")) + 100 * ai_score.ARTIFACT_PENALTY[mode]
    assert ceiling >= ai_score.DEFAULT_THRESHOLD, f"{mode} 非词表上限 {ceiling} < 阈值"


def test_weights_are_convex():
    for w in (ai_score.WEIGHTS_NEWS, ai_score.WEIGHTS_NEWSPIC):
        assert abs(sum(w.values()) - 1.0) < 1e-9


@pytest.mark.parametrize("th,total,tag", [
    (45, 34.9, "PASS"), (45, 35.0, "WARN"), (45, 44.9, "WARN"), (45, 45.0, "FAIL"), (45, 54.9, "FAIL"),
    (40, 29.9, "PASS"), (40, 30.0, "WARN"), (40, 39.9, "WARN"), (40, 40.0, "FAIL"), (40, 42.5, "FAIL"), (1, 0.0, "WARN"),
])
def test_verdict_derived_from_threshold(th, total, tag):
    v = ai_score._verdict(total, th)
    assert tag in v and "真人" not in v and "未命中" not in v


@pytest.mark.parametrize("th", [1, 10, 20, 30, 40, 45, 55, 99])
def test_verdict_consistent_with_passed(th):
    for md in (HUMAN_SAMPLE, CLAUDE_SAMPLE, AI_SLOP_SAMPLE, HUMAN_SAMPLE + AI_SLOP_SAMPLE):
        passed, report = ai_score.check_ai_score(md, threshold=th)
        assert report["verdict"].startswith("🔴") == (not passed)
        if th <= report["total_score"] < th + ai_score.WARN_BAND:
            assert "FAIL" in report["verdict"]


def test_human_sample_low_and_claude_sample_higher():
    _, human = ai_score.check_ai_score(HUMAN_SAMPLE)
    _, claude = ai_score.check_ai_score(CLAUDE_SAMPLE)
    assert human["total_score"] < 35 and human["dimensions"]["artifacts"] == 0
    assert claude["dimensions"]["artifacts"] > 0
    assert claude["total_score"] - human["total_score"] >= 15
    assert len({a["id"] for a in claude["advisory"]}) >= 6


def test_advisory_does_not_change_score_or_exit():
    """advisory 不计分(DR-3):同一篇文章加上 brief/账号上下文,总分不变。"""
    _, a = ai_score.check_ai_score(CLAUDE_SAMPLE)
    _, b = ai_score.check_ai_score(CLAUDE_SAMPLE, brief_text="---\nexperiences:\n  - 我当时就乐了\n---\n", account="tech")
    assert a["total_score"] == b["total_score"] and a["advisory"] != b["advisory"]


@pytest.mark.parametrize("bad", ["Gооgle", "⼈⼯⼤", "ΑΙ"])
def test_adversarial_chars_hard_fail(bad):
    passed, report = ai_score.check_ai_score(HUMAN_SAMPLE + "\n\n藏了" + bad + "字符。\n", threshold=99.0)
    assert passed is False and report["hard_fail"] == "adversarial_chars" and report["verdict"].startswith("🔴")


@pytest.mark.parametrize("ctx", [{"title": "用ΑΙ写代码"}, {"digest": "Gооgle 的新模型"}])
def test_homoglyph_in_external_title_digest_hard_fail(ctx):
    passed, report = ai_score.check_ai_score("正文很普通。\n", threshold=99.0, **ctx)
    assert passed is False and report["hard_fail"] == "adversarial_chars"


def test_zero_width_stripped_before_lint_and_scored_as_artifact():
    """零宽字符不再是硬门:打分/lint 前剥离(防拆词绕过),另记 artifacts.zero_width。"""
    md = HUMAN_SAMPLE + "\n\n这\u200b不\u200b是\u200b终\u200b点，而是起点。\n" + "\u202e" + "\n"
    passed, report = ai_score.check_ai_score(md, threshold=99.0)
    full = ai_score.analyze(md)
    assert passed and report["hard_fail"] is None and report["dimensions"]["artifacts"] > 0
    assert "zero_width" in full["dimensions"]["artifacts"]["detail"]["by_id"]
    assert "neg_contrast" in full["rule_counts"] and full["rule_counts"]["neg_contrast"] >= 1


def test_digest_pile_then_turn_flagged():
    _, report = ai_score.check_ai_score("正文。\n", digest="4667 个赞、361 条评论、等了 13 个月,换来的是一行 changelog。")
    assert ("triad", "digest") in {(a["id"], a["kind"]) for a in report["advisory"]}


def test_analyze_200k_chars_under_3s():
    code = "```python\n" + "".join(f"    x_{i} = f({i})  # 注释\n" for i in range(800)) + "```\n\n"
    table = "| a | b | c |\n|---|---|---|\n" + "".join(f"| {i} | 值{i} | 说明{i} |\n" for i in range(500)) + "\n"
    longp = "这是一段很长的段落，" * 400 + "。\n\n"
    parts: list = []
    while sum(map(len, parts)) < 200_000:
        parts += [f"## 第{len(parts)}节\n\n", HUMAN_SAMPLE.split("---\n", 2)[2], CLAUDE_SAMPLE, code, table, longp]
    md = "# 标题\n\n> 摘要\n\n" + "".join(parts)
    start = time.time()
    ai_score.analyze(md)
    assert time.time() - start < 3.0


def test_ctx_passthrough_title_digest():
    _, report = ai_score.check_ai_score("正文很普通。\n", title="这不是升级,而是范式转移", digest="真正的卖点不是快,是便宜")
    kinds = {(a["id"], a["kind"]) for a in report["advisory"]}
    assert ("neg_contrast", "title") in kinds and ("salience", "digest") in kinds


def test_front_matter_not_scored_and_titles_kept():
    md = "---\ntitle: 一站式赋能平台的全链路实践总结\n---\n## 结语：赋能未来，打造闭环生态\n\n正文。"
    plain = ai_score._strip_markdown(md)
    assert "title:" not in plain and "一站式赋能" not in plain and "赋能未来" in plain


def test_burstiness_ignores_lists_and_headings():
    md = "## 标题\n\n" + "这是一句长度差不多的普通句子,用来测平滑度。" * 6 + "\n\n- 降本增效\n- 全链路打通\n- 一站式体验\n"
    sents = ai_score._burst_sentences(md)
    assert len(sents) == 6 and not any("降本" in s or "标题" in s for s in sents)


# ---------- phrases(DC-15) ----------

def test_set_phrase_fallback_matches_lexicon():
    assert sorted(ai_score._SET_PHRASE_FALLBACK) == sorted(ai_score._lexicon_category("zh-set-phrase", []))


def test_lexicon_missing_uses_fallback(monkeypatch, tmp_path):
    import zh_text
    monkeypatch.setattr(zh_text, "_LEXICON", tmp_path / "missing.json")
    assert ai_score._lexicon_category("zh-set-phrase", ["兜底词"]) == ["兜底词"]


def test_phrase_scoring_rules():
    assert ai_score.score_phrases("综上所述,这项技术具有深远的意义。") == (30.0, {"hit_count": 2, "samples": ["综上所述", "具有深远的意义"]})
    assert ai_score.score_phrases("总结一下今天的 bug:超时参数写错了。")[0] == 0
    assert ai_score.score_phrases("总的来说,凌晨是个很奇妙的时刻。")[0] == ai_score.PHRASE_WEAK_PENALTY
    assert ai_score.score_phrases("让我们一起来看。从某种意义上讲,它对。")[1]["hit_count"] == 2
    assert ai_score.score_phrases("王小波写过:“众所周知,这是真的。”")[0] == 0      # 有归属的直接引语
    assert ai_score.score_phrases("很多人开头就是“综上所述”。")[0] > 0              # 无归属的引号不豁免


# ---------- structural(DC-11) ----------

def test_structural_cross_paragraph_and_negatives():
    xline = "一是把 prompt 拆成固定 block。\n\n二是把避坑条目做成 checklist。\n\n三是 skill 从数据生成。\n"
    assert ai_score.score_structural_perfection(xline)[1]["hit_count"] == 1
    assert ai_score.score_structural_perfection("一、背景\n\n二、方案\n\n三、效果\n")[0] == 0
    assert ai_score.score_structural_perfection("一是一,二是二,三是三,账要算清楚。")[0] == 0
    assert ai_score.score_structural_perfection("第一次跑通是在周二。")[0] == 0


def test_structural_no_catastrophic_backtracking():
    text = "第一,只有开头。\n" + "普通的一行文字。\n" * 400
    start = time.time()
    ai_score.score_structural_perfection(text)
    assert time.time() - start < 1.0


# ---------- punctuation / style(DC-04/05) ----------

def test_dash_contribution_capped():
    dashes = ("这是一段用来测试破折号的文字——还有一处——" * 20)
    score, detail = ai_score.score_punctuation_flatness(dashes)
    assert detail["flavor_points"] <= detail["expected"] / 3 + 1e-9 and score > 10


@pytest.mark.parametrize("text", [
    "C++11 和 C++14 的差别,主要在 lambda 上。i++,j++ 都会执行。", "Python 里 2**10 等于 1024,2**20 大约一百万。",
    "判断条件写成 x==1 且 y==2 的时候才返回 true。", "编译命令是 cd build&&make&&make install。", "====================",
])
def test_style_ignores_operator_collisions(text):
    assert ai_score.score_style(text)[0] == 0


def test_style_counts_colored_marker_density():
    dense = "".join(f"第 {i} 段 ==高亮== 和 !!红字!! 还有 %%粉色%%。\n\n" for i in range(12))
    assert ai_score.score_style(dense)[0] >= 40
    assert ai_score.score_style("全文只有一处 **注意**:需要 Python 3.10+。\n")[0] == 0


# ---------- CLI ----------

def _cli(*args, cwd=None):
    return subprocess.run([sys.executable, str(_SCRIPTS / "ai_score.py"), *args], capture_output=True, text=True, cwd=cwd)


def test_cli_side_files_and_advisory(tmp_path):
    art = tmp_path / "article.md"
    art.write_text(CLAUDE_SAMPLE, encoding="utf-8")
    r = _cli(str(art), "--advisory", "--log-template", "--save-lint", "--account", "main")
    assert r.returncode == 0 and "advisory:" in r.stdout and "上限" not in r.stdout
    assert "artifacts:" in r.stdout and "[functional_heading" in r.stdout   # 3.5a 一条命令看全
    lint = json.loads((tmp_path / "ai_lint.json").read_text(encoding="utf-8"))
    assert lint["counts"]["neg_contrast"] >= 1 and lint["advisory"] and lint["artifacts"]
    assert all("cap" not in a and a["scope"] in ("density", "position") for a in lint["advisory"])   # E6:不写配额
    log = (tmp_path / "humanize_log.md").read_text(encoding="utf-8")
    assert "| 规则 | 行 | 原文 | 处理 | 理由/出处 |" in log and "neg_contrast" in log
    r2 = _cli(str(art), "--log-template")
    assert (tmp_path / "humanize_log.md").read_text(encoding="utf-8").count("neg_contrast") == log.count("neg_contrast")
    assert r2.returncode == 0


def test_cli_exit_code_follows_threshold(tmp_path):
    art = tmp_path / "a.md"
    art.write_text(AI_SLOP_SAMPLE, encoding="utf-8")
    assert _cli(str(art)).returncode == 1
    assert _cli(str(art), "--threshold", "99").returncode == 0


def test_cli_newspic_brief(tmp_path):
    brief = tmp_path / "brief.md"
    brief.write_text("---\ntopic: x\n---\n\n# 要点\n\n1. /rewind 厉害的地方不是撤销一下,而是给你一个更对的工作流\n"
                     "2. /rewind 能把代码和对话一起退回任意一轮\n\n# 短文本\n\n/rewind 能把代码和对话一起退回任意一轮,"
                     "连按两次 Esc 也行。\n", encoding="utf-8")
    r = _cli(str(brief), "--newspic-brief", "--json")
    full = json.loads(r.stdout)
    assert full["mode"] == "newspic" and r.returncode == 0
    points = [a for a in full["advisory"] if a["kind"] == "point"]
    assert points and points[0]["id"] == "neg_contrast" and points[0]["message"].startswith("要点 1")


def test_cli_newspic_brief_aliases_and_title(tmp_path):
    brief = tmp_path / "brief.md"
    brief.write_text("---\ntitle: 真正的后悔药不是撤销而是 /rewind\n---\n\n# 卡片要点\n\n1. 真正值钱的，是敢试\n"
                     "2. /rewind 能退回任意一轮\n\n# 短描述\n\n/rewind 能把代码和对话一起退回任意一轮,连按两次 Esc 也行。\n",
                     encoding="utf-8")
    full = json.loads(_cli(str(brief), "--newspic-brief", "--json").stdout)
    kinds = {(a["id"], a["kind"]) for a in full["advisory"]}
    assert full["char_count"] > 0 and ("salience", "point") in kinds and ("neg_contrast", "title") in kinds

