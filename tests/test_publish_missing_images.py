"""缺图预检:正文引用的本地图片不存在时,在验证 API 和任何上传之前中止发布。"""
from __future__ import annotations

import sys

import pytest

import image_handler
import publish


class _ReachedApi(BaseException):
    """预检放行后走到了 API 步骤。"""


def _publish(monkeypatch, article, *extra):
    monkeypatch.setattr(publish, "get_access_token", lambda: (_ for _ in ()).throw(_ReachedApi()))
    monkeypatch.setattr(sys, "argv", ["publish.py", "--input", str(article), "--author", "a",
                                      "--theme", "minimal-mono", "--skip-ai-score", *extra])
    publish.main()


def _article(tmp_path, body):
    path = tmp_path / "article.md"
    path.write_text(f"# 重试机制\n\n失败后按条件重试。\n\n{body}\n", encoding="utf-8")
    return path


def test_missing_local_images_lists_only_absent_local_files(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "01-ok.png").write_bytes(b"png")
    md = ("![有](images/01-ok.png)\n![缺](images/02-gone.png)\n"
          "![远程](https://example.com/a.png)\n![再缺](images/02-gone.png)\n")
    assert image_handler.missing_local_images(md, base_dir=tmp_path) == ["images/02-gone.png"]


def test_missing_local_image_blocks_before_api(tmp_path, monkeypatch, capsys, tmp_config_yaml, no_network):
    article = _article(tmp_path, "![失败到重试的时序](images/01-retry.png)")
    with pytest.raises(SystemExit) as exc:
        _publish(monkeypatch, article)
    assert exc.value.code == 1
    assert "images/01-retry.png" in capsys.readouterr().out


def test_allow_missing_images_skips_precheck(tmp_path, monkeypatch, tmp_config_yaml, no_network):
    article = _article(tmp_path, "![失败到重试的时序](images/01-retry.png)")
    with pytest.raises(_ReachedApi):
        _publish(monkeypatch, article, "--allow-missing-images")


def test_present_local_and_remote_images_pass_precheck(tmp_path, monkeypatch, tmp_config_yaml, no_network):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "01-retry.png").write_bytes(b"png")
    article = _article(tmp_path, "![时序](images/01-retry.png)\n\n![远程](https://example.com/a.png)")
    with pytest.raises(_ReachedApi):
        _publish(monkeypatch, article)
