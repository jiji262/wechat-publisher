"""只给写作 pass 传当前材料与已确认的声音输入，不带发布和禁词规则。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import writing_context

OUTLINE = "- 失败后先看重试条件 | 夹具材料 | 时序图：失败到重试"


@pytest.fixture
def workspace(tmp_path):
    references = tmp_path / "references"
    references.mkdir()
    (references / "writing-guide.md").write_text(
        "# 写作\n\n## 共用原则\n围绕读者问题组织。\n\n## 技术文章\n每节推进一条论断。\n\n"
        "## main\n解释设计给读者省了哪一步。\n\n## tech\n写出复现条件。\n", encoding="utf-8"
    )
    article_dir = tmp_path / "mp-articles" / "main" / "test"
    article_dir.mkdir(parents=True)
    brief = article_dir / "brief.md"
    brief.write_text(
        '---\naccount: main\ntopic: 纸桥更新\nfocus: 失败后怎样继续\nstance: 推荐文字PDF\n'
        'experiences: [无]\nmaterials:\n  - "可以跳过失败项 | 夹具"\n'
        'article_structure: playbook\nopening_hook: hard-number\n---\n'
        f'## 结构规划\n{OUTLINE}\n\n## 审校记录\n不该传给独立写作者的审校批注。\n', encoding="utf-8"
    )
    return tmp_path, brief


def test_missing_samples_are_explicit_not_filled_from_generated_articles(workspace):
    root, brief = workspace
    (brief.parent / "article.md").write_text("旧AI稿不能成为作者样本。", encoding="utf-8")
    result = writing_context.build_context(brief, root=root)
    assert result["voice"]["status"] == "editorial"
    assert result["voice"]["samples"] is None
    assert "解释设计" in result["voice"]["guidance"]
    serialized = json.dumps(result, ensure_ascii=False)
    assert "旧AI稿" not in serialized
    assert "审校批注" not in serialized
    assert "写出复现条件" not in serialized


def test_author_samples_and_edits_are_supplied_verbatim(workspace):
    root, brief = workspace
    voice_dir = root / "assets" / "voices" / "main"
    voice_dir.mkdir(parents=True)
    sample = "测试用声音夹具，不是真人原作。句子长一点也行，理由要说清楚。"
    (voice_dir / "samples.md").write_text(sample, encoding="utf-8")
    edits = "测试修改对照：原句 → 用户确认的改法。"
    (brief.parent.parent / "edits.md").write_text(edits, encoding="utf-8")
    result = writing_context.build_context(brief, root=root)
    assert result["voice"]["status"] == "samples"
    assert result["voice"]["samples"] == sample
    assert result["voice"]["edits"] == edits


def test_materials_experiences_and_research_remain_data(workspace):
    root, brief = workspace
    (brief.parent / "research.md").write_text("测试来源原文：失败后能跳过。", encoding="utf-8")
    result = writing_context.build_context(brief, root=root)
    assert result["materials"] == ["可以跳过失败项 | 夹具"]
    assert result["experiences"] == []
    assert result["research"] == "测试来源原文：失败后能跳过。"
    assert result["structure_hint"] == {"article_structure": "playbook", "opening_hook": "hard-number"}


@pytest.mark.parametrize("account", ["../tech", "", "unconfigured"])
def test_invalid_account_cannot_select_other_paths(workspace, account):
    root, brief = workspace
    with pytest.raises(ValueError):
        writing_context.build_context(brief, root=root, account=account)


def test_cli_does_not_create_voice_or_article_files(workspace):
    _, brief = workspace
    before = sorted(p.relative_to(brief.parent) for p in brief.parent.rglob("*"))
    result = subprocess.run(
        [sys.executable, str(Path(writing_context.__file__)), str(brief)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["account"] == "main"
    assert sorted(p.relative_to(brief.parent) for p in brief.parent.rglob("*")) == before


def test_outline_carries_only_the_structure_plan(workspace):
    root, brief = workspace
    result = writing_context.build_context(brief, root=root)
    assert result["outline"] == OUTLINE
    assert "审校批注" not in json.dumps(result, ensure_ascii=False)


def test_brief_without_structure_plan_still_builds(workspace):
    root, brief = workspace
    text = brief.read_text(encoding="utf-8")
    brief.write_text(text[: text.index("## 结构规划")], encoding="utf-8")
    assert writing_context.build_context(brief, root=root)["outline"] is None


def test_technical_writing_principles_are_supplied(workspace):
    root, brief = workspace
    assert writing_context.build_context(brief, root=root)["technical_writing"] == "每节推进一条论断。"


def test_repo_guide_has_every_section_the_writer_needs():
    guide = (writing_context.ROOT / "references" / "writing-guide.md").read_text(encoding="utf-8")
    for name in ("共用原则", "技术文章", "main", "tech"):
        assert writing_context._section(guide, name)


def test_instructions_point_writer_at_outline_and_image_slots():
    assert "outline" in writing_context.INSTRUCTIONS
    assert "images/" in writing_context.INSTRUCTIONS


def test_instructions_ask_for_fullwidth_punctuation():
    assert "全角标点" in writing_context.INSTRUCTIONS


def test_instructions_point_writer_at_structure_guides():
    assert "structure_guide" in writing_context.INSTRUCTIONS
    assert "opening_guide" in writing_context.INSTRUCTIONS


def test_structure_and_opening_guides_are_extracted(workspace):
    root, brief = workspace
    (root / "references" / "article-structures.md").write_text(
        "#### 文章结构库\n\n"
        "| `article_structure` | 适合题材 | 可选要素 |\n|---|---|---|\n"
        "| `playbook` 行动清单 | 方法论 | 适用人群、最短路径 |\n\n"
        "#### 开头钩子库\n\n"
        "| `opening_hook` | 写法 | 避免 |\n|---|---|---|\n"
        "| `hard-number` | 第一屏出现数字 | 数字单独成段 |\n",
        encoding="utf-8",
    )
    result = writing_context.build_context(brief, root=root)
    assert result["structure_guide"] == {"name": "playbook", "fits": "方法论", "elements": "适用人群、最短路径"}
    assert result["opening_guide"] == {"name": "hard-number", "how": "第一屏出现数字", "avoid": "数字单独成段"}


def test_missing_structure_library_returns_none(workspace):
    root, brief = workspace
    result = writing_context.build_context(brief, root=root)
    assert result["structure_guide"] is None
    assert result["opening_guide"] is None


def test_repo_structure_library_parses_teardown_and_hard_number():
    guide = (writing_context.ROOT / "references" / "article-structures.md").read_text(encoding="utf-8")
    teardown = writing_context._table_guide(guide, "文章结构库", "teardown", ("fits", "elements"))
    assert teardown and "整体结构" in teardown["elements"]
    hook = writing_context._table_guide(guide, "开头钩子库", "hard-number", ("how", "avoid"))
    assert hook and "数字" in hook["how"]
