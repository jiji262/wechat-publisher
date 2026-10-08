"""第二修复轮(FIX2 E4/E5/E6/E9)的接线:零宽不能拆开同形字、摘要口径唯一、输出不暴露配额、--html 警告。

规则本身在 test_zh_tells / test_ai_score;这里只守 ai_score / publish / toutiao / newspic_build 的接线。网络全部打桩。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import ai_score
import article_meta
import newspic_build
import publish
import toutiao_publish as tp
import zh_tells as Z

ZW = "\u200b"   # 零宽空格(源码里不放不可见字符)
SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
CLEAN = "# 迁移记录\n\n迁移用了两周,主要时间花在核对 key 的过期策略上。\n"
SPLIT = f"用{ZW}ΑΙ{ZW}迁移 Redis"          # 汉字 + 零宽 + 希腊字母 Α Ι + 零宽


class _Stop(BaseException):
    """打桩函数走到这里就停,不进入后续上传步骤。"""


def _cli(*args):
    return subprocess.run([sys.executable, str(SCRIPTS / "ai_score.py"), *args], capture_output=True, text=True)


# ---------- E4:先剥零宽再判同形字 ----------

def test_zero_width_cannot_split_homoglyph():
    assert Z.find_adversarial_chars(SPLIT)
    for ctx in ({"title": SPLIT}, {"digest": SPLIT}):
        assert ai_score.check_ai_score(CLEAN, threshold=99.0, **ctx)[1]["hard_fail"] == "adversarial_chars"
    assert ai_score.check_ai_score(CLEAN + SPLIT + "。\n", threshold=99.0)[1]["hard_fail"] == "adversarial_chars"


def test_gate_blocks_zero_width_split_title(tmp_path, capsys, no_network):
    md = tmp_path / "article.md"
    md.write_text(CLEAN, encoding="utf-8")
    with pytest.raises(SystemExit):
        publish.run_ai_score_gate(CLEAN, md_path=md, title=SPLIT)
    out = capsys.readouterr().out
    assert "未通过硬门 adversarial_chars" in out and "title ΑΙ" in out     # 位置直接打出来,不用再跑 ai_score.py


def test_publish_strips_zero_width_from_cli_title_digest(tmp_path, monkeypatch, no_network):
    seen = []

    def _gate(md, threshold=None, **kw):
        seen.append(kw)
        raise _Stop

    monkeypatch.setattr(publish, "run_ai_score_gate", _gate)
    md = tmp_path / "article.md"
    md.write_text(CLEAN, encoding="utf-8")
    with pytest.raises(_Stop):
        publish.publish_from_markdown(md, title=f"标{ZW}题", digest=f"摘{ZW}要")
    assert (seen[0]["title"], seen[0]["digest"]) == ("标题", "摘要")


def test_toutiao_title_strips_zero_width():
    assert tp._resolve_title(CLEAN, f"手动{ZW}标题") == "手动标题"


def test_cli_advisory_prints_hard_gate(tmp_path):
    art = tmp_path / "a.md"
    art.write_text(CLEAN, encoding="utf-8")
    r = _cli(str(art), "--advisory", "--title", "ΑΙ工具")
    assert r.returncode == 1 and "硬门: adversarial_chars" in r.stdout and "title ΑΙ" in r.stdout


def test_cli_newspic_brief_checks_front_matter_title(tmp_path):
    brief = tmp_path / "brief.md"
    brief.write_text("---\ntitle: 用ΑΙ写代码的三个月\n---\n\n# 要点\n\n1. 第一条要点\n\n# 短文本\n\n"
                     "三个月里写了两万行,删了一万行。\n", encoding="utf-8")
    r = _cli(str(brief), "--newspic-brief", "--json")
    full = json.loads(r.stdout)
    assert r.returncode == 1 and full["hard_fail"] == "adversarial_chars"
    assert any(a.get("where") == "title" for a in full["adversarial"])
    adv = _cli(str(brief), "--newspic-brief", "--advisory")
    assert adv.returncode == 1 and "硬门: adversarial_chars" in adv.stdout


# ---------- E5:摘要口径唯一 ----------

def test_publish_uses_shared_extractors():
    assert publish.extract_digest_from_markdown is article_meta.extract_digest_from_markdown
    assert publish.extract_title_from_markdown is article_meta.extract_title_from_markdown


def test_cli_default_digest_matches_publish(tmp_path):
    """没有紧跟 H1 的引用块时,发布摘要取全文第一个引用块;3.5a 不带 --digest 也要按它查(R-03)。"""
    md = ("# 迁移记录\n\n迁移用了两周,主要时间花在核对 key 的过期策略上。\n\n"
          "> 这不是建议，而是警告。来源 https://docs.example.com\n")
    art = tmp_path / "article.md"
    art.write_text(md, encoding="utf-8")
    full = json.loads(_cli(str(art), "--json").stdout)
    assert ("neg_contrast", "digest", 0) in {(a["id"], a["kind"], a["line"]) for a in full["advisory"]}


def test_cli_default_digest_not_double_counted(tmp_path):
    md = "# 迁移记录\n\n> 这次更新不是修补，而是重写。\n> 第二行补充说明。\n\n正文写了具体的迁移步骤。\n"
    art = tmp_path / "article.md"
    art.write_text(md, encoding="utf-8")
    full = json.loads(_cli(str(art), "--json").stdout)
    assert [(a["id"], a["line"]) for a in full["advisory"] if a["kind"] == "digest"] == [("neg_contrast", 3)]


def test_cli_card_lint_with_empty_digest_not_double_counted(tmp_path):
    """排版卡文字逐行写成 `## 行` 跑 lint:显式 `--digest ""` 不合成摘要,命中不在 L0 重复报。"""
    art = tmp_path / "card.md"
    art.write_text("## 真正的问题不是快,而是稳\n## 这次我们重写了缓存层\n## 它不是工具,而是同事\n", encoding="utf-8")
    full = json.loads(_cli(str(art), "--json", "--digest", "").stdout)
    assert [(a["id"], a["line"]) for a in full["advisory"]] == [("neg_contrast", 1), ("salience", 1), ("neg_contrast", 3)]


@pytest.mark.parametrize("md", [
    "- 它不是工具,而是同事\n- 这次我们重写了缓存层\n",
    "| 项 | 说明 |\n|---|---|\n| 它不是工具,而是同事 | 这次我们重写了缓存层 |\n",
    "## 真正的问题不是快,而是稳\n## 它不是工具,而是同事\n",
])
def test_cli_default_digest_matches_publish_without_body(tmp_path, md):
    """纯列表/纯表格/纯标题稿:CLI 默认摘要与 publish 发出去的那份同口径,--check-log 与发布门禁结论一致(fix2b Minor 1)。"""
    art = tmp_path / "article.md"
    art.write_text(md, encoding="utf-8")
    full = json.loads(_cli(str(art), "--json").stdout)
    want = ai_score.analyze(md, digest=article_meta.extract_digest_from_markdown(md))["advisory"]
    assert full["advisory"] == want


def test_cli_check_log_blocks_pure_list_like_publish(tmp_path):
    art = tmp_path / "article.md"
    art.write_text("- 它不是工具,而是同事\n- 这次我们重写了缓存层\n", encoding="utf-8")
    assert _cli(str(art), "--check-log").returncode == 1


def test_cli_default_digest_kept_for_plain_paragraphs(tmp_path):
    """有正文段落、没有引用块时照旧取前 120 字作默认摘要(与 publish 一致)。"""
    art = tmp_path / "article.md"
    art.write_text("# 迁移记录\n\n这次更新不是修补，而是重写。正文写了具体的迁移步骤。\n", encoding="utf-8")
    full = json.loads(_cli(str(art), "--json").stdout)
    assert ("neg_contrast", "digest", 0) in {(a["id"], a["kind"], a["line"]) for a in full["advisory"]}


# ---------- E6:输出不暴露配额 ----------

def test_lint_json_has_no_cap(tmp_path):
    art = tmp_path / "article.md"
    art.write_text("这不是还没做完,这是设计。\n\n它不是工具,而是同事。\n", encoding="utf-8")
    _cli(str(art), "--advisory", "--save-lint")
    lint = json.loads((tmp_path / "ai_lint.json").read_text(encoding="utf-8"))
    assert lint["advisory"] and not any("cap" in a for a in lint["advisory"])


def test_report_does_not_print_expected_punctuation(tmp_path):
    art = tmp_path / "article.md"
    art.write_text(CLEAN, encoding="utf-8")
    assert "期望" not in _cli(str(art)).stdout


def test_card_warning_has_no_ignore_exception():
    warns = newspic_build.lint_card_text("真正的关键是 PreToolUse:不是提醒，是拦截")
    assert warns and not any("忽略" in w["message"] or "事实澄清" in w["message"] for w in warns)


# ---------- E9:--html 跳过门禁要醒目警告,并清零宽 ----------

def test_html_mode_warns_and_strips_zero_width(tmp_path, monkeypatch, capsys, tmp_config_yaml, no_network):
    sent = []
    monkeypatch.setattr(publish, "publish_article", lambda **kw: sent.append(kw) or {"media_id": "x"})
    html = tmp_path / "article.html"
    html.write_text(f"<p>正文{ZW}一段</p>", encoding="utf-8")
    cover = tmp_path / "c.png"
    cover.write_bytes(b"x")
    monkeypatch.setattr(sys, "argv", ["publish.py", "--html", str(html), "--cover", str(cover),
                                      "--title", f"标{ZW}题", "--digest", f"摘{ZW}要", "--author", "a"])
    publish.main()
    out = capsys.readouterr().out
    assert "--html 不做 AI 味检测" in out
    assert (sent[0]["title"], sent[0]["digest"], sent[0]["html_content"]) == ("标题", "摘要", "<p>正文一段</p>")
