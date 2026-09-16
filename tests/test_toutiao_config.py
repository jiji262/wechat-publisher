"""
头条配置接线的测试。

这个文件专门守一件事:`integrations.toutiao` 写在 yaml 里要真的生效。
之前这段 reader 是对的,但没人调 `load_env()`,用户配了 profile_dir 却永远走
硬编码默认路径 —— 配了个寂寞且零提示。测试就是防这个回归。
"""

from __future__ import annotations

import textwrap

import pytest

import config


_YAML = textwrap.dedent("""\
    default: main
    accounts:
      main:
        name: "Test"
        app_id: "wx_fake"
        app_secret: "fake"
    integrations:
      toutiao:
        profile_dir: "~/tt-profile"
        chrome_path: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        login_timeout_ms: 90000
    """)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("TOUTIAO_PROFILE_DIR", "TOUTIAO_CHROME_PATH", "TOUTIAO_LOGIN_TIMEOUT_MS"):
        monkeypatch.delenv(k, raising=False)


def test_toutiao_config_reaches_environment(write_config_yaml, monkeypatch):
    import os
    write_config_yaml(_YAML)
    config.load_env()
    assert os.environ["TOUTIAO_PROFILE_DIR"] == os.path.expanduser("~/tt-profile")
    assert os.environ["TOUTIAO_CHROME_PATH"].endswith("Google Chrome")
    assert os.environ["TOUTIAO_LOGIN_TIMEOUT_MS"] == "90000"


def test_tilde_is_expanded_because_bun_side_does_not_expand_it(write_config_yaml):
    import os
    write_config_yaml(_YAML)
    config.load_env()
    assert "~" not in os.environ["TOUTIAO_PROFILE_DIR"]


def test_existing_env_wins(write_config_yaml, monkeypatch):
    """_set_env_if_present 用的是 setdefault —— 显式设过的环境变量不该被 yaml 覆盖。"""
    import os
    monkeypatch.setenv("TOUTIAO_PROFILE_DIR", "/explicit/override")
    write_config_yaml(_YAML)
    config.load_env()
    assert os.environ["TOUTIAO_PROFILE_DIR"] == "/explicit/override"


def test_missing_toutiao_section_is_harmless(write_config_yaml):
    import os
    write_config_yaml(textwrap.dedent("""\
        default: main
        accounts:
          main:
            name: "Test"
            app_id: "wx_fake"
            app_secret: "fake"
        """))
    config.load_env()
    assert os.environ.get("TOUTIAO_PROFILE_DIR") is None


def test_run_loads_env_before_touching_browser(write_config_yaml, monkeypatch, tmp_path):
    """run() 必须自己调 load_env —— publish.py 那条路径不会替它调。"""
    import os
    import toutiao_publish as tp

    write_config_yaml(_YAML)
    seen = {}

    def _fake(command, payload=None, timeout=tp.DEFAULT_TIMEOUT):
        seen["profile"] = os.environ.get("TOUTIAO_PROFILE_DIR")
        if command == "upload":
            return {"ok": True, "images": {}, "cover": None}
        return {"ok": True, "pgc_id": "1", "draft_url": "u"}

    monkeypatch.setattr(tp, "_run_cdp", _fake)
    md = tmp_path / "a.md"
    md.write_text("# 一个足够长的测试标题\n\n正文。\n", encoding="utf-8")
    tp.run(md_path=md, skip_ai_score=True)
    assert seen["profile"] == os.path.expanduser("~/tt-profile")
