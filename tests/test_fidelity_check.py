"""fidelity_check.py:初稿/终稿保真核对 + 终稿数字与引语溯源(PR-05 + critic)。全部用 tmp_path,不依赖 mp-articles。"""
from __future__ import annotations

import json

import pytest

import fidelity_check as FC


def _vals(text):
    return [(n["value"], n["pct"]) for n in FC.parse_numbers(text)]


# ---------- 数字归一 ----------
def test_parse_numbers_normalization():
    assert _vals("输入 3,416,000,000 token") == [(3416000000, False)]
    assert _vals("34.2 亿") == [(3.42e9, False)]
    assert _vals("输出 640 万") == [(6.4e6, False)]
    assert _vals("中位 47k，总计 3,416M") == [(47000, False), (3.416e9, False)]
    assert _vals("命中率 96.4%") == [(96.4, True)]
    assert _vals("文件 518MB") == [(518, False)]


def test_parse_numbers_skips_hashes_and_keeps_versions():
    assert _vals("session `03ab7c2e-5814-2096`") == []
    nums = FC.parse_numbers("发了 0.1.11 版本")
    assert [n["raw"] for n in nums] == ["0.1.11"] and nums[0]["value"] is None


def test_sourcing_allows_rounding_only_from_more_precise_source():
    src = "总输入 3,416,000,000 token,另一处写 3,426,300,000"
    found = FC.unsourced_numbers(FC.parse_numbers("34.2 亿和 34.3 亿,还有 3,416M"), src)
    assert found == []
    assert [n["raw"] for n in FC.unsourced_numbers(FC.parse_numbers("约 34.9 亿"), src)] == ["34.9 亿"]


def test_source_side_reads_dates_timestamps_and_signs():
    src = "v0.4.7  2025-03-12T09:41:37Z;中位墙钟时间 **-31%**"
    found = FC.unsourced_numbers(FC.parse_numbers("3 月 12 日发了 0.4.7,时间降了 31%,还有 2025-03-26"), src)
    assert [n["raw"] for n in found] == ["26"]
    assert FC.unsourced_numbers(FC.parse_numbers("有 247 次"), "613/2058 次超 120k,247 次超 180k") == []


def test_small_ints_exempt_and_percent_needs_percent():
    src = "156 个请求里有 73 个重试"
    found = FC.unsourced_numbers(FC.parse_numbers("3 个坑,占 73%,比例 418:1"), src)
    assert [n["raw"] for n in found] == ["73%", "418"]


# ---------- 引语溯源 ----------
def test_unsourced_quotes():
    src = "Lindqvist:\"我们一开始就决定零件全部自己做,这是公司做过最对的一个决定 —— 比融资还对\""
    final = "他说“这是公司做过最对的一个决定”。还有人说“模型不会说谎”。"
    found = FC.unsourced_quotes(FC.quotes(final), src)
    assert [q["text"] for q in found] == ["模型不会说谎"]


def test_short_unattributed_scare_quotes_not_traced():
    """给概念打的短引号不溯源;有归属的直接引语、够长的无归属引文照查(第二轮审查 Minor 2)。"""
    final = ("Mozilla 选了“谁都不得罪”这条路。这是“策略”不是“配置”。\n"
             "维护者回复说“先用环境变量顶一下”。\n"
             "回复内容是“你可以先用环境变量或者配置文件顶一下，下个版本再看”。\n")
    found = FC.unsourced_quotes(FC.quotes(final), "无关材料")
    assert [q["text"] for q in found] == ["先用环境变量顶一下", "你可以先用环境变量或者配置文件顶一下，下个版本再看"]


def test_quote_with_link_in_same_sentence_is_traced():
    """引号所在句带链接也算有归属(zh_text 同口径):短也要溯源;去掉链接就是短概念引号,不报。"""
    linked = "官方原话是 \"too cheap to meter\",见 https://example.com/pricing 。\n"
    assert [q["text"] for q in FC.check(None, linked, sources="无关材料")["unsourced"]["quotes"]] == ["too cheap to meter"]
    bare = "官方原话是 \"too cheap to meter\"。\n"
    assert FC.check(None, bare, sources="无关材料")["unsourced"]["quotes"] == []


@pytest.mark.parametrize("tail", ["详见 https://a.com/b。后面还有一句。\n", "命令是 `echo 好。` 就行。\n"])
def test_linked_quote_traced_when_other_paragraph_misaligns(tail):
    """别的段落句数错位(URL 吞句号、行内代码里有句号)不能让本段带链接的短引语漏查(fix2b Minor 2)。"""
    md = "官方原话是 \"too cheap to meter\",见 https://example.com/pricing 。\n\n" + tail
    found = FC.check(None, md, sources="研究材料里没有这句英文。")["unsourced"]["quotes"]
    assert [(q["text"], q["line"], q["attr"]) for q in found] == [("too cheap to meter", 1, True)]


def test_quote_spans_called_per_paragraph(monkeypatch):
    """归属按段落算(单段内平方开销可忽略);_sets 只要文本集合,不算归属(fix2b nit)。"""
    seen = []
    real = FC.T.quote_spans
    monkeypatch.setattr(FC.T, "quote_spans", lambda t, r="": seen.append(len(t)) or real(t, r))
    md = "他说“第一段”。\n\n她说“第二段”。\n"
    assert [q["text"] for q in FC.quotes(md, md)] == ["第一段", "第二段"]
    assert seen and max(seen) < len(md)
    seen.clear()
    assert FC._sets(md)["quotes"] == {"第一段": "第一段", "第二段": "第二段"} and seen == []


def test_cli_hint_points_at_log_end(tmp_path, capsys):
    (tmp_path / "article.md").write_text("一共 5,317 次。\n", encoding="utf-8")
    (tmp_path / "research.md").write_text("总请求 26,904 次。\n", encoding="utf-8")
    FC.main([str(tmp_path / "nope.md"), str(tmp_path / "article.md")])
    out = capsys.readouterr().out
    assert "在 humanize_log.md 末尾记一句处理结论" in out and "3.5d" not in out


def test_quotes_strip_markers_and_skip_inline_code():
    qs = FC.quotes("他写“**这一层现在是代码了**”。命令是 `echo \"hi there\"`。又说“好”,再说“这一层现在是代码了”。")
    assert [q["text"] for q in qs] == ["这一层现在是代码了", "好"]
    assert qs[0]["line"] == 1


# ---------- 初稿/终稿四类集合 ----------
def test_diff_sets():
    draft = "可能提升 30%，用 `foo` 和 Codex。他说“好用”。\n"
    final = "提升 35%，用 `bar` 和 Claude。\n"
    d = FC.check(draft, final)["diff"]
    assert d["numbers"]["removed"] == ["30%"] and d["numbers"]["added"] == ["35%"]
    assert d["code"] == {"removed": ["foo"], "added": ["bar"]}
    assert d["latin"] == {"removed": ["Codex"], "added": ["Claude"]}
    assert d["quotes"]["removed"] == ["好用"]


def test_numbers_same_value_not_reported():
    d = FC.check("一共 3,416,000,000 次。\n", "一共 34.16 亿次。\n")["diff"]
    assert d["numbers"] == {"removed": [], "added": []}


# ---------- 改写率 / 缩水 / 段落数 ----------
P1 = "前台一共接了一千二百多个电话，占总量的百分之六左右，剩下的全是自动外呼在重复播放同一段录音。"
P2 = "录音文件都存在本地，所以这些外呼大部分是重放而不是新录，话费单才会看起来这么夸张又这么便宜。"


def test_rewrite_flagged_only_for_heavy_rewrite():
    light = P1.replace("左右", "上下")
    heavy = "说到底，这件事讲的是一套系统在不知不觉中替你做了选择，而你直到月底对账那天才发现哪里不对。"
    res = FC.check(f"{P1}\n\n{P2}\n", f"{light}\n\n{heavy}\n")
    assert len(res["rewrites"]) == 1 and res["rewrites"][0]["line"] == 3
    assert res["rewrites"][0]["rate"] > FC.REWRITE_MAX


def test_shrink_and_paragraph_change_warn():
    draft = "\n\n".join([P1, P2] * 5) + "\n"
    final = "\n\n".join([P1, P2]) + "\n"
    ids = [w["id"] for w in FC.check(draft, final)["warnings"]]
    assert "shrink" in ids and "paragraphs" in ids
    assert FC.check(draft, draft)["warnings"] == []


def test_stats_report_similes():
    stats = FC.check("这就像地铁线路。\n\n好比一台老冰箱。\n", "这就像地铁线路。\n")["stats"]
    assert stats["similes"] == [2, 1]


# ---------- 新增亲历 ----------
def test_new_experience_sentence_listed_unless_in_brief():
    draft = f"{P1}\n"
    final = f"{P1}\n\n上周我试了一下这个命令，结果跑了整整一下午。\n"
    assert len(FC.check(draft, final)["new_experience"]) == 1
    brief = "---\nexperiences:\n  - \"上周 | 试了这个命令 | 跑了整整一下午\"\n---\n"
    assert FC.check(draft, final, brief_text=brief)["new_experience"] == []


# ---------- CLI ----------
def test_cli_autodetects_sources_and_exits_0(tmp_path, capsys):
    (tmp_path / "article.draft.md").write_text(f"{P1}\n", encoding="utf-8")
    (tmp_path / "article.md").write_text("一共 26,904 次请求，另有 5,317 次。\n", encoding="utf-8")
    (tmp_path / "research.md").write_text("总请求 26,904 次。\n", encoding="utf-8")
    code = FC.main([str(tmp_path / "article.draft.md"), str(tmp_path / "article.md"), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert any(s.endswith("research.md") for s in out["sources"])
    assert [n["raw"] for n in out["unsourced"]["numbers"]] == ["5,317"]


def test_cli_missing_draft_still_checks_sources(tmp_path, capsys):
    (tmp_path / "article.md").write_text("一共 5,317 次。\n", encoding="utf-8")
    code = FC.main([str(tmp_path / "nope.md"), str(tmp_path / "article.md")])
    out = capsys.readouterr().out
    assert code == 0 and "初稿" in out


def test_cli_missing_final_exit0(tmp_path, capsys):
    assert FC.main([str(tmp_path / "a.md"), str(tmp_path / "b.md")]) == 0


def test_cli_reports_missing_explicit_research(tmp_path, capsys):
    """显式传的 --research 不存在:说出来,不静默跳过(放错目录时最常见)。"""
    (tmp_path / "article.md").write_text("一共 5,317 次。\n", encoding="utf-8")
    missing = tmp_path / "other" / "research.md"
    assert FC.main([str(tmp_path / "a.md"), str(tmp_path / "article.md"), "--research", str(missing)]) == 0
    assert f"指定的溯源材料不存在:{missing}" in capsys.readouterr().out
    assert FC.run(tmp_path / "a.md", tmp_path / "article.md")["missing"] == []


def test_shrink_threshold_catches_moderate_cut():
    """较大删减提示核对事实，不从字数变化推断文风。"""
    paras = [P1, P2] * 5
    draft = "\n\n".join(paras) + "\n"
    final = "\n\n".join(paras[:8]) + "\n"          # 删掉 2/10 段
    ids = [w["id"] for w in FC.check(draft, final)["warnings"]]
    assert "shrink" in ids
