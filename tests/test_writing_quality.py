"""自然写作回归：风格提示不挡发布，出处和字符硬门继续生效。"""
from __future__ import annotations

import pytest

import ai_score
import fidelity_check as fidelity
import humanize_log
import publish


@pytest.mark.parametrize("mode", ["news", "newspic"])
def test_extra_parentheses_do_not_improve_style_score(mode):
    text = "仪器已经完成校准。记录保存在本地。关闭电源后可以取出样品。"
    original = ai_score.analyze(text, mode=mode)
    decorated = ai_score.analyze(text + "（记录）", mode=mode)
    assert decorated["total_ai_score"] == original["total_ai_score"]


def test_sentence_length_variation_does_not_improve_style_score():
    text = "仪器已经完成校准。记录保存在本地。关闭电源后可以取出样品。"
    text += "取样时戴上手套。样品需要密封保存。"
    joined = text.replace("。", "，", 3)
    assert ai_score.analyze(text)["total_ai_score"] == ai_score.analyze(joined)["total_ai_score"]


def test_factual_contrast_can_publish_without_style_log(no_network):
    publish.run_ai_score_gate("# 这是权限问题，不是文件丢失\n\n查看目录访问权限。\n")


def test_style_threshold_does_not_block_publication(no_network):
    text = "赋能打造全新生态，聚焦闭环链路，助力数字化转型。"
    publish.run_ai_score_gate(text, threshold=0)


@pytest.mark.parametrize("text", ["我当场愣住了。", "我整个人都懵了。", "我上周试了这个工具。"])
def test_unverified_experience_still_blocks_publication(tmp_path, text, no_network):
    article = tmp_path / "article.md"
    article.write_text(text, encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        publish.run_ai_score_gate(text, md_path=article)
    assert exc.value.code == 1


def test_confirmed_reaction_is_allowed(tmp_path, no_network):
    text = "我当场愣住了。"
    (tmp_path / "brief.md").write_text(
        '---\nexperiences:\n  - "当场愣住了"\n---\n', encoding="utf-8"
    )
    publish.run_ai_score_gate(text, md_path=tmp_path / "article.md")


def test_many_reasoned_style_keeps_have_no_quota():
    hits = [{"id": "neg_contrast", "line": i, "kind": "heading", "scope": "position",
             "excerpt": f"这是第{i}处权限问题，不是文件丢失"} for i in range(8)]
    rows = humanize_log.render_template([]) + "".join(
        f"| neg_contrast | {h['line']} | {h['excerpt']} | 保留 | 这是排除相似故障的事实说明 |\n"
        for h in hits
    )
    assert humanize_log.uncovered(hits, rows, han=200) == []


def test_shortening_only_requests_fact_review_not_filler():
    draft = "请求此前长期超时。团队进一步调查并分析日志，确认连接池没有及时释放空闲连接。修复这个问题后，请求恢复正常。"
    final = "请求超时是连接池没有释放空闲连接所致。修复后请求恢复正常。"
    result = fidelity.check(draft, final)
    assert result["warnings"]
    messages = " ".join(w["message"] for w in result["warnings"])
    assert "核对" in messages
    assert not any(word in messages for word in ("删过头", "补回", "只剩干货"))


@pytest.mark.parametrize("mode", ["news", "newspic"])
def test_unsourced_quote_still_blocks_in_both_modes(tmp_path, mode, no_network):
    text = "同事说这次调用日志里全是重复请求。"
    article = tmp_path / "article.md"
    article.write_text(text, encoding="utf-8")
    with pytest.raises(SystemExit):
        publish.run_ai_score_gate(text, mode=mode, md_path=article)


def test_newspic_uses_the_actual_brief_path(tmp_path, no_network):
    brief = tmp_path / "custom-name.md"
    brief.write_text('---\nexperiences:\n  - "当场愣住了"\n---\n', encoding="utf-8")
    publish._newspic_short_text_gate("我当场愣住了。", None, "main", md_path=brief)


def test_newspic_cannot_publish_unverified_reaction(tmp_path, no_network):
    brief = tmp_path / "custom-name.md"
    brief.write_text('---\nexperiences: [无]\n---\n', encoding="utf-8")
    with pytest.raises(SystemExit):
        publish._newspic_short_text_gate("我当场愣住了。", None, "main", md_path=brief)


def test_newspic_style_threshold_is_advisory_only(no_network):
    publish._newspic_short_text_gate("这是权限问题，不是文件丢失。", 0, "main")


@pytest.mark.parametrize("md,kwargs", [
    ("正文。", {"title": "我当场愣住了。"}),
    ("# 标题\n\n## 我当场愣住了。\n\n正文。", {}),
    ("# 标题\n\n![我当场愣住了。](image.png)\n\n正文。", {}),
])
def test_unverified_reactions_in_metadata_still_block(tmp_path, md, kwargs, no_network):
    with pytest.raises(SystemExit):
        publish.run_ai_score_gate(md, md_path=tmp_path / "article.md", digest="正常摘要。", **kwargs)


def test_custom_newspic_log_command_runs_with_the_same_brief(tmp_path, no_network, capsys):
    import shlex
    import subprocess

    brief = tmp_path / "custom-name.md"
    brief.write_text('---\nexperiences: [无]\n---\n\n# 短文本\n\n我当场愣住了。\n', encoding="utf-8")
    with pytest.raises(SystemExit):
        publish._newspic_short_text_gate("我当场愣住了。", None, "main", md_path=brief)
    output = capsys.readouterr().out
    command = next(line.strip() for line in output.splitlines() if line.strip().startswith("python3 "))
    result = subprocess.run(shlex.split(command), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "unsourced_experience" in (tmp_path / "humanize_log.md").read_text(encoding="utf-8")
