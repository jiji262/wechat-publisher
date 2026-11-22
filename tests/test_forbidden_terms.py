"""禁用词硬门:词表来自本机配置,发布各链路和生图 prompt 都拦,--skip-ai-score 也拦。

夹具词 acmecorp 是虚构的,不对应任何真实词表。
"""
from __future__ import annotations

import sys
import textwrap

import pytest

import api
import config
import forbidden_terms
import generate_image
import multi_publish
import publish
import toutiao_publish as tp

TERM = "acmecorp"


class _ReachedApi(BaseException):
    """禁用词检查放行后走到了 API 步骤。"""


@pytest.fixture
def terms(monkeypatch):
    monkeypatch.setattr(forbidden_terms, "load_terms", lambda: [TERM])


def _no_leak(text):
    assert TERM not in text.casefold()


def _blocked_here(capsys):
    out = capsys.readouterr().out
    assert "禁用词:" in out
    _no_leak(out)


def _article(tmp_path, body="失败后按条件重试。", title="重试机制"):
    path = tmp_path / "article.md"
    path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 匹配
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("line", [
    "这家 AcmeCorp 的方案",
    "全角写法 ＡＣＭＥＣＯＲＰ 也算",
    "零宽拆开 acme​corp 也算",
    "`/Users/acmecorp/codes/demo`",
    "![acmecorp 的架构](images/01.png)",
    "![架构](/Users/acmecorp/images/01.png)",
    "见 https://acmecorp.example.com/docs",
])
def test_term_found_in_any_context(line):
    hits = forbidden_terms.find_terms(f"开头一行\n{line}\n", [TERM])
    assert [h["line"] for h in hits] == [2]
    _no_leak(hits[0]["excerpt"])


def test_code_fence_is_not_exempt():
    md = "正文\n\n```bash\ncd /Users/AcmeCorp/project\n```\n"
    assert [h["line"] for h in forbidden_terms.find_terms(md, [TERM])] == [4]


def test_long_line_excerpt_is_masked_and_trimmed():
    line = "前" * 50 + TERM + "后" * 50 + TERM
    hits = forbidden_terms.find_terms(line, [TERM])
    _no_leak(hits[0]["excerpt"])
    assert forbidden_terms.MASK in hits[0]["excerpt"] and len(hits[0]["excerpt"]) < len(line)


def test_empty_term_list_passes():
    assert forbidden_terms.check({"正文": f"{TERM} 出现了"}, []) == []
    forbidden_terms.abort_if_found({"正文": f"{TERM} 出现了"}, [])


def test_abort_prints_masked_location(capsys):
    with pytest.raises(SystemExit) as exc:
        forbidden_terms.abort_if_found({"标题": f"关于 {TERM}", "正文": f"第一行\n{TERM} 第二行"}, [TERM])
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "标题(第 1 项)" in out and "正文 L2(第 1 项)" in out
    _no_leak(out)


def test_cli_exit_codes(tmp_path, terms, capsys):
    (tmp_path / TERM).mkdir()
    clean, dirty = tmp_path / "clean.md", tmp_path / TERM / "dirty.md"   # 目录名含禁用词也不回显
    clean.write_text("没有问题\n", encoding="utf-8")
    dirty.write_text(f"路径 /Users/{TERM}/x\n", encoding="utf-8")
    assert forbidden_terms.main([str(clean)]) == 0
    assert forbidden_terms.main([str(dirty)]) == 1
    _no_leak(capsys.readouterr().out)


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("yaml_value, expected", [
    ("", []),
    (f"forbidden_terms: [{TERM}, ' other ']", [TERM, "other"]),
    (f"forbidden_terms: '{TERM}, other'", [TERM, "other"]),
    ("forbidden_terms: []", []),
])
def test_config_forbidden_terms(write_config_yaml, yaml_value, expected):
    write_config_yaml(f"default: main\n{yaml_value}\n")
    assert config.get_forbidden_terms() == expected


def test_config_forbidden_terms_wrong_type_fails_closed(write_config_yaml):
    write_config_yaml("forbidden_terms: {a: 1}\n")
    with pytest.raises(config.ConfigError):
        config.get_forbidden_terms()


def test_config_terms_reach_the_gate(write_config_yaml, real_forbidden_terms):
    write_config_yaml(f"forbidden_terms: [{TERM.upper()}]\n")
    with pytest.raises(SystemExit):
        forbidden_terms.abort_if_found({"正文": f"x {TERM} y"})


# ---------------------------------------------------------------------------
# 发布链路:都在 API 之前拦,--skip-ai-score 不放行
# ---------------------------------------------------------------------------

def _publish_md(monkeypatch, article, *extra):
    monkeypatch.setattr(publish, "get_access_token", lambda: (_ for _ in ()).throw(_ReachedApi()))
    monkeypatch.setattr(sys, "argv", ["publish.py", "--input", str(article), "--theme", "minimal-mono",
                                      "--skip-ai-score", *extra])
    publish.main()


@pytest.mark.parametrize("kind", ["body", "title", "digest", "author"])
def test_markdown_publish_blocks_before_api(tmp_path, monkeypatch, capsys, tmp_config_yaml, no_network,
                                            terms, kind):
    article = _article(tmp_path, body=f"本机路径 `/Users/{TERM}/x`" if kind == "body" else "正文。")
    extra = {"title": ["--title", f"{TERM} 的重试"], "digest": ["--digest", f"{TERM} 摘要"],
             "author": ["--author", f"{TERM} 团队"]}.get(kind, [])
    with pytest.raises(SystemExit) as exc:
        _publish_md(monkeypatch, article, *extra)
    assert exc.value.code == 1
    _blocked_here(capsys)


def test_markdown_author_from_config_is_checked(tmp_path, monkeypatch, capsys, write_config_yaml, no_network,
                                                terms):
    write_config_yaml("default: main\naccounts:\n  main:\n    app_id: wx1\n    app_secret: s\n"
                      f"    author: '{TERM}'\n")
    with pytest.raises(SystemExit):
        _publish_md(monkeypatch, _article(tmp_path))
    _blocked_here(capsys)


def test_clean_markdown_reaches_api(tmp_path, monkeypatch, tmp_config_yaml, no_network, terms):
    with pytest.raises(_ReachedApi):
        _publish_md(monkeypatch, _article(tmp_path), "--author", "a")


def _newspic_brief(tmp_path, short_text):
    brief = tmp_path / "brief.md"
    brief.write_text(textwrap.dedent(f"""\
        ---
        topic: "t"
        title: "升级后的第一周"
        ---

        # 要点

        1. 连按两次 Esc 可以把代码退回上一轮

        # 短文本

        {short_text}
        """), encoding="utf-8")
    return brief


def test_newspic_blocks_even_when_skipping_gate(tmp_path, monkeypatch, capsys, tmp_config_yaml, no_network,
                                                terms):
    monkeypatch.setattr(publish, "resolve_image_style", lambda **kw: {"style_name": "s"})
    monkeypatch.setattr(publish, "get_access_token", lambda: (_ for _ in ()).throw(_ReachedApi()))
    with pytest.raises(SystemExit) as exc:
        publish.publish_from_brief(_newspic_brief(tmp_path, f"来自 {TERM}"), author="a", skip_ai_score=True)
    assert exc.value.code == 1
    _blocked_here(capsys)


def test_html_publish_blocks(tmp_path, monkeypatch, capsys, tmp_config_yaml, no_network, terms):
    html = tmp_path / "a.html"
    html.write_text(f"<p>{TERM}</p>", encoding="utf-8")
    monkeypatch.setattr(publish, "publish_article", lambda **kw: (_ for _ in ()).throw(_ReachedApi()))
    with pytest.raises(SystemExit):
        publish.publish_from_html(html, "标题", str(tmp_path / "c.jpg"), author="a")
    _blocked_here(capsys)


def test_api_publish_article_blocks_before_upload(monkeypatch, capsys, terms):
    monkeypatch.setattr(api, "get_config", lambda name=None: {"author": "a", "account_name": "m"})
    monkeypatch.setattr(api, "upload_thumb_image", lambda p: (_ for _ in ()).throw(_ReachedApi()))
    with pytest.raises(SystemExit):
        api.publish_article("标题", f"<p>{TERM}</p>", "c.jpg")
    _blocked_here(capsys)


def test_api_publish_newspic_blocks_before_upload(monkeypatch, capsys, terms):
    monkeypatch.setattr(api, "get_config", lambda name=None: {"author": f"{TERM}", "account_name": "m"})
    monkeypatch.setattr(api, "upload_newspic_image", lambda p: (_ for _ in ()).throw(_ReachedApi()))
    with pytest.raises(SystemExit):
        api.publish_newspic("标题", "短文本", ["a.png"])
    _blocked_here(capsys)


def test_api_clean_article_reaches_upload(monkeypatch, terms):
    monkeypatch.setattr(api, "get_config", lambda name=None: {"author": "a", "account_name": "m"})
    monkeypatch.setattr(api, "upload_thumb_image", lambda p: (_ for _ in ()).throw(_ReachedApi()))
    with pytest.raises(_ReachedApi):
        api.publish_article("标题", "<p>正文</p>", "c.jpg")


def test_toutiao_blocks_even_when_skipping_gate(tmp_path, capsys, terms):
    with pytest.raises(SystemExit):
        tp._load_and_gate(_article(tmp_path, body=f"{TERM} 正文"), None, True)
    _blocked_here(capsys)


def test_multi_publish_blocks_before_sync(tmp_path, monkeypatch, capsys, terms):
    monkeypatch.setattr(multi_publish, "check_prerequisites", lambda verbose=False: (True, []))
    monkeypatch.setattr(multi_publish, "sync_to_platforms", lambda *a, **k: (_ for _ in ()).throw(_ReachedApi()))
    with pytest.raises(SystemExit):
        multi_publish.run(_article(tmp_path, body=f"{TERM} 正文"), ["zhihu"])
    _blocked_here(capsys)


# ---------------------------------------------------------------------------
# 生图 prompt
# ---------------------------------------------------------------------------

def test_image_prompt_blocks_before_backend(tmp_path, monkeypatch, capsys, terms):
    monkeypatch.setattr(generate_image.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(_ReachedApi()))
    with pytest.raises(SystemExit):
        generate_image.main(["--prompt", f"画 {TERM} 的标志", "--image", str(tmp_path / "o.png")])
    _blocked_here(capsys)


def test_image_promptfile_blocks_before_backend(tmp_path, monkeypatch, capsys, terms):
    prompt = tmp_path / "p.md"
    prompt.write_text(f"路径 /Users/{TERM}/x\n", encoding="utf-8")
    monkeypatch.setattr(generate_image.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(_ReachedApi()))
    with pytest.raises(SystemExit):
        generate_image.main(["--promptfiles", str(prompt), "--image", str(tmp_path / "o.png")])
    _blocked_here(capsys)


def test_clean_image_prompt_reaches_backend(tmp_path, monkeypatch, terms):
    monkeypatch.setattr(generate_image.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(_ReachedApi()))
    with pytest.raises(_ReachedApi):
        generate_image.main(["--prompt", "画一张时序图", "--image", str(tmp_path / "o.png"),
                             "--generator", "baoyu-image-gen"])
