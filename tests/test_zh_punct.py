"""中文标点全角化:转换与残留检查共用一套判定,宁可漏转,不可错改。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import zh_punct as P


@pytest.mark.parametrize("src, want", [
    ("先看时间线,再看账单。", "先看时间线，再看账单。"),
    ("落差:skill 说不继承", "落差：skill 说不继承"),
    ("前者便宜;后者稳。", "前者便宜；后者稳。"),
    ("是不是缓存没生效?", "是不是缓存没生效？"),
    ("配额打满了!", "配额打满了！"),
    ("在 Codex(pro 套餐)里", "在 Codex（pro 套餐）里"),
    ("平均 100 轮(18,450 ÷ 184)", "平均 100 轮（18,450 ÷ 184）"),
    ("调用 (foo) 之后", "调用（foo）之后"),
    ("Codex , 但是没提示", "Codex，但是没提示"),
    ("**结论**:先验证", "**结论**：先验证"),
    ("## 落差:skill 说不继承,Codex 实际 fork 了", "## 落差：skill 说不继承，Codex 实际 fork 了"),
    ("| 主线程 | 1,431 次,占 8% |", "| 主线程 | 1,431 次，占 8% |"),
    ("![时间线:读 skill 到配额打满](images/01-a,b.png)", "![时间线：读 skill 到配额打满](images/01-a,b.png)"),
    ("[文档,第 3 节](https://x.dev/a?b=1,2)", "[文档，第 3 节](https://x.dev/a?b=1,2)"),
])
def test_converts_chinese_context(src, want):
    assert P.to_fullwidth(src) == want


@pytest.mark.parametrize("text", [
    "输入 2,768M,", "时间 11:27 开始", "尺寸 2.35:1 的封面",
    "原文是 with approvals, permission checks, and sandboxing off 这一句",
    "调用 foo(bar) 返回", "运行 `a,b:c;d?e!(f)` 看结果",
    "见 https://example.com/a?b=1&c=(2) 原帖",
    "负面数字用 !!下降 30%!! 标红", "如图![示意](images/01.png)",
    "Project(RuntimeEvents[0..k], policy)",
    "---\ntitle: a,b\nnote: 中文:前置\n---\n正文。\n",
    "```\n中文,代码块里不动:\n```\n",
])
def test_leaves_protected_or_latin_context_alone(text):
    assert P.to_fullwidth(text) == text
    assert P.halfwidth_left(text) == []


def test_ascii_quotes_around_chinese_become_curly():
    assert P.to_fullwidth('点名的"危险实现"就是这个') == "点名的“危险实现”就是这个"


def test_unbalanced_ascii_quote_is_left_alone():
    text = '他说"先别删,'
    assert P.to_fullwidth(text) == '他说"先别删，'


def test_idempotent_and_leaves_no_residual():
    text = '# 标题:一\n\n> 摘要,两句?\n\n正文(含 `x,y`)!"引语"\n\n![图注:短语](images/01.png)\n'
    once = P.to_fullwidth(text)
    assert P.to_fullwidth(once) == once
    assert P.halfwidth_left(once) == []


def test_residual_lists_line_and_excerpt():
    left = P.halfwidth_left("第一行没问题。\n第二行,有半角。\n")
    assert [(r["line"], r["excerpt"]) for r in left] == [(2, "第二行,有半角。")]


def test_cli_writes_in_place_and_reports(tmp_path):
    article = tmp_path / "article.md"
    article.write_text("先看,再改。\n", encoding="utf-8")
    script = Path(P.__file__)
    check = subprocess.run([sys.executable, str(script), str(article)], capture_output=True, text=True)
    assert check.returncode == 1 and "L1" in check.stdout
    fix = subprocess.run([sys.executable, str(script), str(article), "--write"], capture_output=True, text=True)
    assert fix.returncode == 0, fix.stderr
    assert article.read_text(encoding="utf-8") == "先看，再改。\n"


def test_quote_after_colon_converts_in_one_call():
    text = '写得明明白白:"implementer + 2 reviewers"、"Review loops"。'
    assert P.to_fullwidth(text) == "写得明明白白：“implementer + 2 reviewers”、“Review loops”。"


def test_table_cell_padding_is_kept():
    assert P.to_fullwidth('| ponytail | "最懒工程师"提示词 |') == "| ponytail | “最懒工程师”提示词 |"


def test_gate_blocks_halfwidth_body_with_fix_command(tmp_path, capsys, no_network):
    import publish
    article = tmp_path / "article.md"
    text = "# 迁移记录\n\n迁移用了两周,主要时间花在核对上。\n"
    article.write_text(text, encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        publish.run_ai_score_gate(text, md_path=article)
    out = capsys.readouterr().out
    assert exc.value.code == 1
    assert "L3" in out and "zh_punct.py" in out and "--write" in out


def test_gate_blocks_halfwidth_manual_title(tmp_path, capsys, no_network):
    import publish
    text = "# 迁移记录\n\n迁移用了两周，主要时间花在核对上。\n"
    with pytest.raises(SystemExit):
        publish.run_ai_score_gate(text, md_path=tmp_path / "article.md", title="迁移记录:两周")
    assert "标题" in capsys.readouterr().out


def test_gate_passes_fullwidth_text(tmp_path, no_network):
    import publish
    text = "# 迁移记录\n\n迁移用了两周，主要时间花在核对上。\n"
    publish.run_ai_score_gate(text, md_path=tmp_path / "article.md", title="迁移记录", digest="两周，核对为主")
