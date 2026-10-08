"""
AI 味门禁的接线路径:gate 查的标题/摘要必须是最终发布的那一份(F4),
没有文章路径时不能放行(F5),头条单独运行也走同一个 gate,零宽字符发布前清除(D2),
贴图标题过同形字硬门(F6),卡面要点 lint 只提示、写进 card_plan 的 warnings,不阻断。

检测规则本身在 test_zh_tells / test_ai_score;这里只守接线。网络与平台 API 全部打桩。
"""

from __future__ import annotations

import sys
import textwrap

import pytest

import ai_score
import publish
import toutiao_publish as tp

ZW = "\u200b"   # 零宽空格(源码里不放不可见字符)
LOG_HEADER = "| 规则 | 行 | 原文 | 处理 | 理由/出处 |\n|---|---|---|---|---|\n"
CONTRAST_DIGEST = "这不是一次小修,而是一次重构"
CONTRAST_MD = f"# 2.1 版本发布说明\n\n> {CONTRAST_DIGEST}\n\n## 改动\n\n2.1 版把项目级 hooks 的加载放到了用户级之后。升级后跑一遍 doctor 能看到来源。\n"


class _ReachedApi(BaseException):
    """门禁放行后走到了 API 步骤。继承 BaseException,免得被 except Exception 吞掉。"""


def _write(tmp_path, md, name="article.md"):
    path = tmp_path / name
    path.write_text(md, encoding="utf-8")
    return path


@pytest.fixture
def spy_score(monkeypatch):
    """包一层真实 check_ai_score,记录 gate 传进去的 title/digest。"""
    seen = []
    real = ai_score.check_ai_score

    def _spy(md, threshold=ai_score.DEFAULT_THRESHOLD, mode="news", **ctx):
        seen.append({"md": md, **ctx})
        return real(md, threshold, mode, **ctx)

    monkeypatch.setattr(ai_score, "check_ai_score", _spy)
    return seen


def _run_publish(monkeypatch, argv):
    monkeypatch.setattr(publish, "get_access_token", lambda: (_ for _ in ()).throw(_ReachedApi()))
    monkeypatch.setattr(sys, "argv", ["publish.py", *argv, "--author", "a", "--theme", "minimal-mono"])
    publish.main()


# ---------------------------------------------------------------------------
# F4:gate 查的就是要发布的标题/摘要
# ---------------------------------------------------------------------------

def test_digest_from_later_quote_is_gated(tmp_path, monkeypatch, capsys, spy_score, tmp_config_yaml, no_network):
    """发布用的摘要是全文第一个引用块(这里在 H2 之后),gate 必须拿它过零容忍 lint。"""
    md = "# 迁移记录\n\n迁移用了两周,主要时间花在核对 key 的过期策略上。\n\n## 配置\n\n> 这次升级不是修补，而是重写。\n\n配置文件改了三处。\n"
    with pytest.raises(SystemExit) as exc:
        _run_publish(monkeypatch, ["--input", str(_write(tmp_path, md))])
    assert exc.value.code == 1
    assert spy_score[0]["digest"] == publish.extract_digest_from_markdown(md) == "这次升级不是修补，而是重写。"
    assert "[neg_contrast] L0 这次升级不是修补，而是重写。" in capsys.readouterr().out


def test_title_fallback_without_h1_is_gated(tmp_path, monkeypatch, capsys, spy_score, tmp_config_yaml, no_network):
    """没有 H1 时发布用正文第一行当标题(不是 front matter 的 title),gate 查的也得是它。"""
    md = "---\ntitle: Redis 7.2 迁移记录\n---\n\n真正的瓶颈其实是缓存\n\n迁移用了两周,主要时间花在核对 key 的过期策略上。\n"
    with pytest.raises(SystemExit):
        _run_publish(monkeypatch, ["--input", str(_write(tmp_path, md))])
    assert spy_score[0]["title"] == publish.extract_title_from_markdown(md) == "真正的瓶颈其实是缓存"
    assert "[salience] L0 真正的瓶颈其实是缓存" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# F5:没有文章路径不能放行
# ---------------------------------------------------------------------------

def test_gate_without_md_path_fails_closed(capsys, no_network):
    with pytest.raises(SystemExit):
        publish.run_ai_score_gate(CONTRAST_MD)
    out = capsys.readouterr().out
    assert "未提供文章路径" in out and "缺文章路径" in out


def test_gate_without_md_path_passes_when_nothing_to_check(capsys, no_network):
    publish.run_ai_score_gate("# 标题\n\n2.1 版把项目级 hooks 的加载放到了用户级之后。\n")
    assert "结果: 通过" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 头条:单独运行也走同一个 gate
# ---------------------------------------------------------------------------

def test_toutiao_direct_gate_blocks_without_log(tmp_path, no_network):
    with pytest.raises(SystemExit) as exc:
        tp._load_and_gate(_write(tmp_path, CONTRAST_MD), None, False)
    assert exc.value.code == 1


def test_toutiao_direct_gate_passes_with_log(tmp_path, capsys, no_network):
    article = _write(tmp_path, CONTRAST_MD)
    row = f"| neg_contrast | 3 | {CONTRAST_DIGEST} | 保留 | 版本公告里的原话,照引 |\n"
    _write(tmp_path, LOG_HEADER + row, "humanize_log.md")
    path, content, title = tp._load_and_gate(article, None, False)
    assert (path, content, title) == (article, CONTRAST_MD, "2.1 版本发布说明")
    assert "结果: 通过" in capsys.readouterr().out


@pytest.mark.parametrize("manual, expected", [(None, "2.1 版本发布说明"), ("我自己定的标题", "我自己定的标题")])
def test_toutiao_gate_gets_final_title_and_path(tmp_path, monkeypatch, manual, expected):
    calls = []
    monkeypatch.setattr(publish, "run_ai_score_gate", lambda md, thr=None, **kw: calls.append(kw))
    article = _write(tmp_path, CONTRAST_MD)
    tp._load_and_gate(article, None, False, title=manual, account="tech")
    assert calls == [{"md_path": article, "title": expected, "account": "tech"}]


def test_toutiao_cli_runs_gate_before_upload(tmp_path, monkeypatch, no_network):
    """SKILL.md 写的独立入口:没有 humanize_log 也得被拦在上传之前。"""
    uploads = []
    monkeypatch.setattr(tp, "_run_cdp", lambda *a, **kw: uploads.append(a) or {"ok": True})
    monkeypatch.setattr(tp, "load_env", lambda: None)
    monkeypatch.setattr(sys, "argv", ["toutiao_publish.py", "--input", str(_write(tmp_path, CONTRAST_MD))])
    with pytest.raises(SystemExit) as exc:
        tp.main()
    assert exc.value.code == 1 and uploads == []


def test_publish_toutiao_only_delegates_gate_with_account(monkeypatch, tmp_config_yaml):
    captured = {}
    monkeypatch.setattr(tp, "run", lambda **kw: captured.update(kw) or {"success": True})
    args = publish._build_parser().parse_args(["--input", "a.md", "--platform", "toutiao"])
    publish._publish_to_toutiao(args, already_gated=False)
    assert captured["skip_ai_score"] is False and captured["account"] == "main"
    publish._publish_to_toutiao(args, already_gated=True)
    assert captured["skip_ai_score"] is True


# ---------------------------------------------------------------------------
# D2:零宽字符清除而不是拦截
# ---------------------------------------------------------------------------

def test_zero_width_stripped_before_convert_and_gate(tmp_path, monkeypatch, capsys, spy_score,
                                                     tmp_config_yaml, no_network):
    md = f"# 一次{ZW}普通的更新\n\n2.1 版把项目级{ZW} hooks 的加载放到了用户级之后。\n\n升{ZW}级后跑一遍 doctor。\n"
    published = []
    monkeypatch.setattr(publish, "get_access_token", lambda: "fake-token")
    monkeypatch.setattr(publish, "process_article_images", lambda m, tmp, base_dir=None: (m, {}, None))
    monkeypatch.setattr(publish, "publish_article", lambda **kw: published.append(kw) or {"media_id": "m-1"})
    cover = _write(tmp_path, "x", "cover.jpg")
    monkeypatch.setattr(sys, "argv", ["publish.py", "--input", str(_write(tmp_path, md)), "--cover", str(cover),
                                      "--author", "a", "--theme", "minimal-mono", "--temp-dir", str(tmp_path / "t")])
    publish.main()
    out = capsys.readouterr().out
    assert "已清除 3 个零宽字符" in out and "结果: 通过" in out
    assert ZW not in spy_score[0]["md"] and ZW not in published[0]["html_content"]
    assert published[0]["title"] == "一次普通的更新"


def test_toutiao_strips_zero_width_even_when_skipping_gate(tmp_path, capsys):
    _, content, title = tp._load_and_gate(_write(tmp_path, f"# 标题{ZW}在这\n\n正{ZW}文。\n"), None, True)
    assert ZW not in content and title == "标题在这"
    assert "已清除 2 个零宽字符" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# F6:贴图标题过同形字硬门
# ---------------------------------------------------------------------------

def _newspic_brief(tmp_path, title):
    brief = _write(tmp_path, textwrap.dedent(f"""\
        ---
        topic: "t"
        title: "{title}"
        ---

        # 要点

        1. 连按两次 Esc 可以把代码退回上一轮
        """), "brief.md")
    (tmp_path / "images").mkdir()
    for n in ("01.png", "02.png"):
        (tmp_path / "images" / n).write_bytes(b"\x89PNG")
    return brief


def test_newspic_title_homoglyph_blocks(tmp_path, monkeypatch, capsys, tmp_config_yaml, no_network):
    brief = _newspic_brief(tmp_path, "用ΑΙ升级后的第一周")
    monkeypatch.setattr(publish, "resolve_image_style", lambda **kw: {"style_name": "s"})
    monkeypatch.setattr(publish, "get_access_token", lambda: (_ for _ in ()).throw(_ReachedApi()))
    with pytest.raises(SystemExit) as exc:
        publish.publish_from_brief(brief, author="a")
    assert exc.value.code == 1
    assert "标题未通过硬门 adversarial_chars" in capsys.readouterr().out


def test_newspic_clean_title_passes(tmp_path, monkeypatch, tmp_config_yaml, no_network):
    brief = _newspic_brief(tmp_path, "升级后的第一周")
    monkeypatch.setattr(publish, "resolve_image_style", lambda **kw: {"style_name": "s"})
    monkeypatch.setattr(publish, "get_access_token", lambda: "fake-token")
    monkeypatch.setattr(publish, "publish_newspic", lambda **kw: {"media_id": "m-2", **kw})
    assert publish.publish_from_brief(brief, author="a")["title"] == "升级后的第一周"


# ---------------------------------------------------------------------------
# 贴图:卡面 lint 只提示(从 test_publish_gate 移来,与标题硬门放一起)
# ---------------------------------------------------------------------------

def test_card_lint_flags_contrast_point():
    import newspic_build
    hits = newspic_build.lint_card_text("这个命令厉害的地方不是撤销,而是让你敢试")
    assert [h["id"] for h in hits] == ["neg_contrast"]
    assert newspic_build.lint_card_text("连按两次 Esc 可以把代码退回上一轮") == []


def test_card_plan_writes_warnings(monkeypatch):
    import newspic_build
    style = {"style_name": "s", "prompt_template": {"newspic_card": "{card_main}|{card_sub}"}, "canvas": {}}
    monkeypatch.setattr(newspic_build, "resolve_image_style", lambda **kw: style)
    parsed = {"frontmatter": {"topic": "t"},
              "sections": {"要点": "1. 真正值钱的，是敢试\n2. 连按两次 Esc 可以把代码退回上一轮"}}
    cards = newspic_build.build_card_plan(parsed)["cards"]
    assert [w["id"] for w in cards[0]["warnings"]] == ["salience"]
    assert cards[1]["warnings"] == []


def test_newspic_card_advisory_only_prints(capsys):
    publish._print_card_advisory(["真正值钱的，是敢试", "连按两次 Esc 可以把代码退回上一轮"], "")
    out = capsys.readouterr().out   # 走到这里没有 SystemExit 即不阻断
    assert "[salience] 要点 1" in out


def test_publish_from_brief_card_advisory_does_not_block(tmp_path, monkeypatch, capsys, tmp_config_yaml, no_network):
    """整条贴图链路:要点命中卡面 lint 也照常建草稿。"""
    brief = tmp_path / "brief.md"
    brief.write_text(textwrap.dedent(
        """\
        ---
        topic: "t"
        ---

        # 要点

        1. 真正值钱的，是敢试
        2. 连按两次 Esc 可以把代码退回上一轮

        # 短文本

        2.1 版把项目级 hooks 放到用户级之后加载,冲突时项目级生效。升级后跑一遍 doctor 能看到来源。
        """), encoding="utf-8")
    (tmp_path / "images").mkdir()
    for n in ("01.png", "02.png"):
        (tmp_path / "images" / n).write_bytes(b"\x89PNG")
    monkeypatch.setattr(publish, "resolve_image_style", lambda **kw: {"style_name": "s"})
    monkeypatch.setattr(publish, "get_access_token", lambda: "fake-token")
    monkeypatch.setattr(publish, "publish_newspic", lambda **kw: {"media_id": "m-2"})
    result = publish.publish_from_brief(brief, author="a")
    assert result["media_id"] == "m-2"
    assert "[salience] 要点 1" in capsys.readouterr().out
