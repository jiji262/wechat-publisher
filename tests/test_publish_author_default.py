"""没配置作者时署名留空,不兜底到写死的个人笔名。"""

from __future__ import annotations

import publish


def _resolve(monkeypatch, get_config):
    monkeypatch.setattr(publish, "get_config", get_config)
    args = publish._build_parser().parse_args(["--input", "article.md"])
    publish._resolve_config(args)
    return args.author


def test_author_empty_when_account_has_no_author(monkeypatch):
    assert _resolve(monkeypatch, lambda *a, **k: {"theme": "refined-blue"}) == ""


def test_author_empty_when_config_missing(monkeypatch):
    def missing(*a, **k):
        raise publish.ConfigError("no config")

    assert _resolve(monkeypatch, missing) == ""


def test_author_from_account_config(monkeypatch):
    assert _resolve(monkeypatch, lambda *a, **k: {"author": "主号作者"}) == "主号作者"
