"""标题候选的编辑检查：机械问题给警告，具体对象和问句只给提示。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import title_check


def _codes(title: str) -> list[str]:
    return [issue["code"] for issue in title_check.check_title(title)["issues"]]


def _warnings(title: str) -> list[str]:
    return [issue["code"] for issue in title_check.check_title(title)["issues"] if issue["level"] == "warn"]


def test_specific_title_with_object_is_usable():
    result = title_check.check_title("Apache Maka 的事件日志、投影和上下文压缩")
    assert result["verdict"] == "可用"
    assert result["han"] >= 10


def test_clickbait_template_is_a_warning():
    assert "clickbait" in _warnings("一文读懂 Apache Maka 的事件日志")


def test_negated_contrast_is_a_warning():
    assert "neg_contrast" in _warnings("聊天记录不是记录，而是投影")


def test_anthromorphic_drama_is_a_warning():
    assert "drama" in _warnings("Apache 收编了一个 AI Agent")


def test_number_template_is_a_warning():
    assert "number_template" in _warnings("3 个 Agent 日志设计要点")


def test_suspense_colon_is_a_warning():
    assert "colon_suspense" in _warnings("真相：Agent 日志该存哪里")


def test_overlong_title_is_a_warning():
    title = "Apache Maka 的事件日志、投影、上下文压缩、恢复机制和权限边界到底应该怎么设计"
    assert "long" in _warnings(title)


def test_short_title_is_a_warning():
    assert "short" in _warnings("日志")


@pytest.mark.parametrize("title,code", [
    ("Agent 日志设计！", "exclaim"),
    ("《Agent 日志设计》", "book_marks"),
    ("“Agent”日志设计", "quotes"),
    ("Agent 日志设计 😀", "emoji"),
])
def test_typography_warnings(title, code):
    assert code in _warnings(title)


def test_missing_anchor_and_question_are_info_only():
    result = title_check.check_title("把聊天记录当成投影再看上下文压缩")
    assert result["verdict"] == "可用"
    assert "no_anchor" in _codes("把聊天记录当成投影再看上下文压缩")
    question = title_check.check_title("Agent 的聊天记录应该存在哪里？")
    assert question["verdict"] == "可用"
    assert "question" in _codes("Agent 的聊天记录应该存在哪里？")


def test_cli_json_shape():
    script = Path(title_check.__file__)
    result = subprocess.run(
        [sys.executable, str(script), "Agent 日志设计！", "--json"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload[0]["verdict"] == "需要改"
    assert payload[0]["issues"][0]["level"] == "warn"


def test_cli_strict_exits_nonzero_on_warning():
    script = Path(title_check.__file__)
    result = subprocess.run(
        [sys.executable, str(script), "一文读懂 Agent 日志", "--strict"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1