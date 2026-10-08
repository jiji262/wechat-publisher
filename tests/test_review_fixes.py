"""独立代码审查(Important 1-5 + 部分 Minor)的回归测试。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import humanize_log as H
import zh_sources as S
import zh_tells

ROOT = Path(__file__).resolve().parent.parent
BRIEF_NONE = "---\ntopic: x\nexperiences:\n  - 无\n---\n"
BRIEF_REAL = ("---\ntopic: x\nexperiences:\n"
              "  - \"2026-08-09 | 在本机跑 Codex 子代理流程 | 两天烧掉 27.8 亿 token\"\n---\n")


def _keep(item: dict, reason: str) -> str:
    return H.render_template([item]).replace("|  |  |", f"| 保留 | {reason} |")


# ---------- Important 1:亲历保留行的出处要能核对 ----------

EXP = {"id": "unsourced_experience", "line": 5, "excerpt": "去年我在老东家也踩过一样的坑", "scope": "position"}


def test_brief_experiences_reason_rejected_when_brief_has_none():
    log = _keep(EXP, "用户口述 brief experiences 可核对")
    assert H.uncovered([EXP], log, han=1000, brief_text=BRIEF_NONE)


def test_brief_line_reason_must_point_at_matching_line():
    item = {**EXP, "excerpt": "我在本机跑 Codex 子代理流程,两天烧掉 27.8 亿 token"}
    good = _keep(item, "见 brief L4 用户亲历")
    bad = _keep(item, "见 brief L2 用户亲历")          # L2 是 topic 行
    assert not H.uncovered([item], good, han=1000, brief_text=BRIEF_REAL)
    assert H.uncovered([item], bad, han=1000, brief_text=BRIEF_REAL)


def test_url_does_not_source_a_first_person_experience():
    log = _keep(EXP, "见 https://example.com/post 原文")
    assert H.uncovered([EXP], log, han=1000, brief_text=BRIEF_REAL)


def test_url_still_sources_a_quote():
    q = {"id": "unsourced_quote", "line": 7, "excerpt": "同事跟我说这个参数别动", "scope": "position"}
    assert not H.uncovered([q], _keep(q, "见 https://example.com/thread 原帖"), han=1000)


# ---------- Important 2:出处按句判定,不按整段 ----------

def _ids(md: str, brief: str | None = None) -> list[str]:
    return [a["id"] for a in zh_tells.lint(md, brief_text=brief)]


def test_fabricated_sentence_next_to_sourced_one_is_reported():
    md = ("# 标题\n\n我在本机跑 Codex 子代理流程,两天烧掉 27.8 亿 token。"
          "去年我在老东家也踩过一样的坑,改了三次才好。\n")
    assert "unsourced_experience" in _ids(md, BRIEF_REAL)


def test_url_in_paragraph_does_not_hide_first_person_experience():
    md = "# 标题\n\n官方文档见 https://example.com/docs 。去年我在老东家也踩过一样的坑,改了三次才好。\n"
    assert "unsourced_experience" in _ids(md, BRIEF_NONE)


# ---------- Important 3:高亮按位置判断 ----------

def test_highlighted_product_name_does_not_force_contrast():
    md = "# 标题\n\n这次 @@Claude Code@@ 更新后,问题不是 Claude Code 本身,而是插件的加载顺序。\n"
    forced = [a for a in zh_tells.lint(md) if a["id"] == "neg_contrast" and a.get("scope") == "position"]
    assert not forced


def test_highlighted_contrast_sentence_is_still_forced():
    md = "# 标题\n\n说到底,==问题不是模型本身,而是插件的加载顺序==。\n"
    forced = [a for a in zh_tells.lint(md) if a["id"] == "neg_contrast" and a.get("scope") == "position"]
    assert forced


# ---------- Important 4:导入失败时门禁拒发 ----------

def test_gate_fails_closed_when_ai_score_import_breaks(monkeypatch):
    import builtins
    import publish

    real_import = builtins.__import__

    def broken(name, *a, **k):
        if name == "ai_score":
            raise ImportError("simulated missing module")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", broken)
    with pytest.raises(SystemExit):
        publish.run_ai_score_gate("# 标题\n\n正文。\n", md_path=None)


# ---------- Important 5:--check-log 离线验证退出条件 ----------

def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "ai_score.py"), *args],
                          capture_output=True, text=True, timeout=60)


def test_check_log_fails_without_log_and_passes_when_clean(tmp_path):
    dirty = tmp_path / "a" / "article.md"
    dirty.parent.mkdir()
    dirty.write_text("# 标题\n\n> 摘要写一件具体的事。\n\n这不是还没做完,这是设计。那不是 bug,而是特性。"
                     "它不是慢,而是稳。这不是缺陷,这是取舍。\n", encoding="utf-8")
    assert _run([str(dirty), "--check-log"]).returncode == 1
    clean = tmp_path / "b" / "article.md"
    clean.parent.mkdir()
    clean.write_text("# 标题\n\n> 摘要写一件具体的事。\n\n周三下午服务重启了两次,日志里只有一行超时。\n", encoding="utf-8")
    assert _run([str(clean), "--check-log"]).returncode == 0


# ---------- Minor ----------

def test_template_placeholder_experience_is_unset():
    brief = '---\nexperiences:\n  - "<时间> | <动作> | <结果> | <用户说的当时反应,没有就省略这一栏>"\n---\n'
    assert S.parse_brief(brief)["experiences"] == []


def test_dialogue_flag_only_from_front_matter():
    brief = "---\ntopic: x\n---\n\n## 结构规划\n\ndialogue: true\n"
    assert S.parse_brief(brief)["dialogue"] is False


def test_account_flag_accepts_new_accounts(tmp_path):
    f = tmp_path / "article.md"
    f.write_text("# 标题\n\n周三下午服务重启了两次。\n", encoding="utf-8")
    assert _run([str(f), "--account", "food"]).returncode == 0


# ---------- 复核遗留:亲历出处只认 experiences,门槛对齐 covered,剔除题目通用词 ----------

FAKE = {"id": "unsourced_experience", "line": 9, "scope": "position",
        "excerpt": "去年我在老东家用 Claude Code 维护 AGENTS.md 时踩过一样的坑"}
BRIEF_TOPIC = ('---\ntopic: "Claude Code 终于读 AGENTS.md 了"\nkeywords: [Claude Code, AGENTS.md]\n'
               'experiences:\n  - 无\nmaterials:\n  - "Claude Code 2.1 开始读取 AGENTS.md | https://example.com/changelog"\n---\n')
BRIEF_OTHER = ('---\ntopic: "Claude Code 终于读 AGENTS.md 了"\nkeywords: [Claude Code, AGENTS.md]\nexperiences:\n'
               '  - "9 月 18 日 | 在公司 monorepo 升级 Claude Code | 发现 AGENTS.md 没被加载"\n---\n')


@pytest.mark.parametrize("brief,reason", [
    (BRIEF_TOPIC, "brief L2 话题行可核对"),
    (BRIEF_TOPIC, "brief materials 第一条可核对"),
    (BRIEF_TOPIC, "brief 第 7 行材料可核对"),
    (BRIEF_OTHER, "brief experiences 可核对"),
    (BRIEF_OTHER, "brief L5 用户亲历可核对"),
])
def test_fabricated_experience_cannot_borrow_other_brief_lines(brief, reason):
    assert H.uncovered([FAKE], _keep(FAKE, reason), han=1000, brief_text=brief)


def test_research_quote_source_is_matched_per_line():
    q = {"id": "unsourced_quote", "line": 3, "scope": "position", "excerpt": "我同事跟我说这个问题在 Windows 上更明显"}
    research = "## 反馈\nWindows 用户反馈加载失败的问题较多。\n"
    assert H.uncovered([q], _keep(q, "见 research.md 用户反馈"), han=1000, research_text=research)


def test_sentence_count_mismatch_falls_back_to_unsourced():
    import zh_text
    text = "我同事跟我说:“这里要改”。"
    raw = "`echo 好。` 见 https://example.com 我同事跟我说:“这里要改”。"   # 行内代码里的句号让句数对不上
    assert not any(zh_text.sourced_sentences(text, raw))


# ---------- 第二轮审查 Minor 1:analyze 只跑一遍检测规则,lint 复用 scan 结果 ----------

MD_SCAN = ("# 标题\n\n> 真正的卖点不是快,是便宜。\n\n这不是还没做完,这是设计。去年我在老东家也踩过一样的坑。\n\n"
           "## 小节\n\n他说“这个参数别动”。说到底,一切都是取舍。\n")
SCAN_CTX = {"brief_text": BRIEF_REAL, "account": "main", "title": "这不是升级,而是范式转移", "digest": "真正的卖点不是快,是便宜"}


def test_analyze_runs_rule_scan_once(monkeypatch):
    import ai_score
    calls, real = [], zh_tells.scan
    monkeypatch.setattr(zh_tells, "scan", lambda *a, **k: calls.append(1) or real(*a, **k))
    full = ai_score.analyze(MD_SCAN, **SCAN_CTX)
    assert len(calls) == 1
    monkeypatch.setattr(zh_tells, "scan", real)
    assert full["advisory"] and full["advisory"] == zh_tells.lint(MD_SCAN, **SCAN_CTX)


def test_lint_reuses_precomputed_scan():
    scanned = zh_tells.scan(MD_SCAN, **SCAN_CTX)
    assert zh_tells.lint(MD_SCAN, **SCAN_CTX, scanned=scanned) == zh_tells.lint(MD_SCAN, **SCAN_CTX)


def test_fidelity_scrub_keeps_fullwidth_period_after_url():
    """裸 URL 直接接全角句号时,句号不能被当成 URL 的一部分吞掉(否则句数错位、链接归属失效)。"""
    import fidelity_check as FC
    cleaned = FC._SCRUB.sub(lambda m: " " * len(m.group(0)), "见 https://example.com/pricing。后面还有一句。")
    assert cleaned.count("。") == 2
