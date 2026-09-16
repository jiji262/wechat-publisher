"""
toutiao_publish 的单元测试。

这个文件覆盖:
- run() 的返回值形状(success/pgc_id/draft_url/images/cover/error 六件套)
- 上传结果 → 渲染 → 发布 三段的衔接(web_uri 必须真的进到正文里)
- 缺图守卫、标题校验、封面兜底
- _run_cdp 的错误翻译(bun 缺失 / 非法 JSON / ok:false)

浏览器侧(bun + CDP)在这里一律打桩 —— 真实链路靠手动 e2e 验证。
"""

from __future__ import annotations

import json
import subprocess

import pytest

import toutiao_publish as tp


def _payload(calls, command):
    """按 command 取 payload。dict(calls) 会静默丢掉重复调用,断言就检查错了那次。"""
    hits = [p for c, p in calls if c == command]
    assert len(hits) == 1, f"{command} 调用了 {len(hits)} 次,断言无法确定该看哪一次"
    return hits[0]


@pytest.fixture
def article(tmp_path):
    """一篇带一张本地配图的文章。"""
    (tmp_path / "pic.png").write_bytes(b"\x89PNG fake")
    md = tmp_path / "article.md"
    md.write_text(
        "# 一个足够长的测试标题\n\n第一段正文。\n\n![配图说明](./pic.png)\n\n第二段正文。\n",
        encoding="utf-8",
    )
    return md


@pytest.fixture
def fake_cdp(monkeypatch):
    """打桩 _run_cdp,记录每次调用的 (command, payload)。"""
    calls = []

    def _fake(command, payload=None, timeout=tp.DEFAULT_TIMEOUT):
        calls.append((command, payload))
        if command == "upload":
            images = {
                item["key"]: {
                    "image_url": f"https://p3.toutiaoimg.com/{i}",
                    "image_uri": f"tos-cn-i-x/uri{i}",
                    "image_width": 800,
                    "image_height": 450,
                    "image_mime_type": "image/png",
                }
                for i, item in enumerate(payload.get("images") or [])
            }
            cover = (
                {
                    "image_url": "https://p3.toutiaoimg.com/cover",
                    "image_uri": "tos-cn-i-x/cover",
                    "image_width": 960,
                    "image_height": 540,
                    "image_mime_type": "image/jpeg",
                }
                if payload.get("cover")
                else None
            )
            return {"ok": True, "images": images, "cover": cover}
        if command == "publish":
            return {"ok": True, "pgc_id": "7123456789", "draft_url": "https://mp.toutiao.com/x?pgc_id=7123456789"}
        return {"ok": True, "user": {"id": 1, "name": "tester"}}

    monkeypatch.setattr(tp, "_run_cdp", _fake)
    return calls


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def test_run_happy_path(article, fake_cdp):
    r = tp.run(md_path=article, skip_ai_score=True)
    assert r["success"] is True
    assert r["platform"] == "toutiao"
    assert r["pgc_id"] == "7123456789"
    assert r["draft_url"].endswith("7123456789")
    assert r["images"] == 1
    assert r["cover"] is True
    assert r["error"] is None


def test_result_shape_is_stable(article, fake_cdp):
    """publish.py 会读这些 key,形状不能漂。"""
    r = tp.run(md_path=article, skip_ai_score=True)
    assert set(r) == {
        "success", "platform", "title", "pgc_id", "draft_url", "images", "cover", "error",
    }


def test_uploaded_web_uri_lands_in_published_content(article, fake_cdp):
    """上传 → 渲染 → 发布的衔接:正文里必须带上传回来的 web_uri。"""
    tp.run(md_path=article, skip_ai_score=True)
    publish_payload = _payload(fake_cdp, "publish")
    content = publish_payload["content"]
    assert 'web_uri="tos-cn-i-x/uri0"' in content
    assert 'class="pgc-img"' in content
    assert "style=" not in content
    assert "配图说明" in content


def test_title_extracted_from_h1_and_h1_not_in_body(article, fake_cdp):
    tp.run(md_path=article, skip_ai_score=True)
    payload = _payload(fake_cdp, "publish")
    assert payload["title"] == "一个足够长的测试标题"
    assert "一个足够长的测试标题" not in payload["content"]


def test_explicit_title_overrides(article, fake_cdp):
    r = tp.run(md_path=article, title="我自己定的标题", skip_ai_score=True)
    assert r["title"] == "我自己定的标题"


def test_cover_defaults_to_first_image(article, fake_cdp):
    tp.run(md_path=article, skip_ai_score=True)
    upload_payload = _payload(fake_cdp, "upload")
    assert upload_payload["cover"].endswith("pic.png")


def test_explicit_cover_wins(article, fake_cdp, tmp_path):
    cover = tmp_path / "mycover.jpg"
    cover.write_bytes(b"jpg")
    tp.run(md_path=article, cover_path=str(cover), skip_ai_score=True)
    assert _payload(fake_cdp, "upload")["cover"].endswith("mycover.jpg")


# ---------------------------------------------------------------------------
# 失败路径
# ---------------------------------------------------------------------------

def test_missing_article_file(tmp_path, fake_cdp):
    r = tp.run(md_path=tmp_path / "nope.md", skip_ai_score=True)
    assert r["success"] is False
    assert "不存在" in r["error"]


def test_title_too_long_blocks_before_upload(tmp_path, fake_cdp):
    md = tmp_path / "a.md"
    md.write_text("# " + "标" * 31 + "\n\n正文\n", encoding="utf-8")
    r = tp.run(md_path=md, skip_ai_score=True)
    assert r["success"] is False
    assert "30" in r["error"]
    assert fake_cdp == []          # 标题不合法就不该浪费一次浏览器启动


def test_missing_image_aborts_by_default(tmp_path, fake_cdp):
    md = tmp_path / "a.md"
    md.write_text("# 一个足够长的标题\n\n![x](./nope.png)\n", encoding="utf-8")
    r = tp.run(md_path=md, skip_ai_score=True)
    assert r["success"] is False
    assert "nope.png" in r["error"]
    assert fake_cdp == []


def test_missing_image_allowed_with_flag(tmp_path, fake_cdp):
    """--allow-missing-images 时缺图被丢弃,正文照常发出去。"""
    md = tmp_path / "a.md"
    md.write_text("# 一个足够长的标题\n\n正文。\n\n![x](./nope.png)\n", encoding="utf-8")
    r = tp.run(md_path=md, skip_ai_score=True, allow_missing_images=True)
    assert r["success"] is True
    content = _payload(fake_cdp, "publish")["content"]
    assert "pgc-img" not in content        # 缺的那张没混进正文
    assert "正文。" in content


def test_publish_failure_is_reported(article, monkeypatch):
    def _fail(command, payload=None, timeout=tp.DEFAULT_TIMEOUT):
        if command == "upload":
            return {"ok": True, "images": {"./pic.png": {
                "image_url": "u", "image_uri": "i",
                "image_width": 1, "image_height": 1, "image_mime_type": "image/png"}},
                "cover": None}
        raise tp.ToutiaoPublishError("头条拒绝保存: [7113] 发布失败，请重试")

    monkeypatch.setattr(tp, "_run_cdp", _fail)
    r = tp.run(md_path=article, skip_ai_score=True)
    assert r["success"] is False
    assert "7113" in r["error"]


# ---------------------------------------------------------------------------
# _run_cdp 的错误翻译
# ---------------------------------------------------------------------------

def test_run_cdp_missing_bun(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    with pytest.raises(tp.ToutiaoPublishError) as e:
        tp._run_cdp("check")
    assert "bun" in str(e.value)


def test_run_cdp_timeout(monkeypatch):
    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="bun", timeout=1)
    monkeypatch.setattr(subprocess, "run", _boom)
    with pytest.raises(tp.ToutiaoPublishError) as e:
        tp._run_cdp("check", timeout=1)
    assert "超时" in str(e.value)


class _Proc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def test_run_cdp_non_json_output(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(stdout="not json at all"))
    with pytest.raises(tp.ToutiaoPublishError) as e:
        tp._run_cdp("check")
    assert "JSON" in str(e.value)


def test_run_cdp_empty_output(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(stdout="", returncode=1))
    with pytest.raises(tp.ToutiaoPublishError) as e:
        tp._run_cdp("check")
    assert "没有输出" in str(e.value)


def test_run_cdp_propagates_browser_error(monkeypatch):
    payload = json.dumps({"ok": False, "error": "登录等待超时(180s)"})
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(stdout=payload))
    with pytest.raises(tp.ToutiaoPublishError) as e:
        tp._run_cdp("check")
    assert "登录等待超时" in str(e.value)


def test_run_cdp_reads_last_line_only(monkeypatch):
    """bun 可能先打了别的东西到 stdout,只认最后一行 JSON。"""
    out = "some noise\n" + json.dumps({"ok": True, "user": {"id": 7, "name": "n"}})
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(stdout=out))
    assert tp._run_cdp("check")["user"]["id"] == 7
