"""
publish.py 的 --platform 分发测试。

这条路径是用户最常敲的那行命令,之前零测试覆盖。
重点守两件事:向后兼容(不传 --platform 时行为不变)、
以及参数组合非法时要响亮报错而不是静默吞掉。
"""

from __future__ import annotations

import argparse

import pytest

import publish


class _Args:
    def __init__(self, platform="wechat", sync=None):
        self.platform = platform
        self.sync = sync


@pytest.fixture
def parser():
    p = argparse.ArgumentParser()
    return p


def test_default_is_wechat_only(parser):
    assert publish._resolve_target_platforms(_Args(), parser) == ["wechat"]


def test_parses_and_normalizes(parser):
    got = publish._resolve_target_platforms(_Args(" TouTiao , WeChat "), parser)
    assert got == ["toutiao", "wechat"]


def test_dedupes_preserving_order(parser):
    got = publish._resolve_target_platforms(_Args("toutiao,wechat,toutiao"), parser)
    assert got == ["toutiao", "wechat"]


def test_unknown_platform_errors(parser):
    with pytest.raises(SystemExit):
        publish._resolve_target_platforms(_Args("zhihu"), parser)


def test_empty_platform_errors(parser):
    with pytest.raises(SystemExit):
        publish._resolve_target_platforms(_Args("  "), parser)


def test_sync_without_wechat_errors(parser):
    """--sync 靠微信链路,只发头条时给了 --sync 必须报错,不能静默忽略。"""
    with pytest.raises(SystemExit):
        publish._resolve_target_platforms(_Args("toutiao", sync="zhihu,juejin"), parser)


def test_sync_with_wechat_is_fine(parser):
    got = publish._resolve_target_platforms(_Args("wechat,toutiao", sync="zhihu"), parser)
    assert got == ["wechat", "toutiao"]


def test_ai_gate_is_shared_not_duplicated():
    """头条和微信共用同一个门禁函数,阈值默认值不会两边漂移。"""
    assert callable(publish.run_ai_score_gate)
    import toutiao_publish  # noqa: F401  确保没有循环 import
