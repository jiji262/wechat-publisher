"""
publish.py 的 AI 味门禁集成测试。

守的是"发布前最后一道闸"的接线,不是检测规则本身(规则在 test_zh_tells / test_ai_score):
- advisory 没在 humanize_log.md 里记录 → 拒发;记录完整 → 放行(D1:超量规则按规则一行)
- 同形字硬门 → 拒发;零宽字符不拦,发布前自动清除(D2)
- 三类拒发各给各的下一步;人读输出不显示上限(D3)
- --skip-ai-score → 整个门禁不跑
- 手动 --digest 也要过 lint(以前它绕过了所有检查)
- 贴图相关用例在 test_publish_gate_paths.py

网络与微信 API 全部 mock;不依赖 mp-articles/。
"""

from __future__ import annotations

import sys
import textwrap

import pytest

import ai_score
import publish

CLEAN_MD = textwrap.dedent(
    """\
    # Claude Code 2.1 更新记录

    > 这次更新改了 hooks 的加载顺序。

    ## 改动

    2.1 版把项目级 hooks 的加载放到了用户级之后。旧版本里两者冲突时用户级生效,现在项目级生效。

    升级后跑一遍 `claude doctor`,输出里会列出当前生效的 hooks 来源。
    """
)

ADVISORY_ITEM = {
    "id": "neg_contrast", "label": "否定对照/翻案", "line": 9, "kind": "para",
    "excerpt": "旧版本里两者冲突时用户级生效", "count": 2, "cap": 1, "message": "否定对照/翻案:全文 2 处,上限 1",
}
LOG_HEADER = "| 规则 | 行 | 原文 | 处理 | 理由/出处 |\n|---|---|---|---|---|\n"
DIGEST = "这不是一次小修,而是一次重构"


class _ReachedApi(BaseException):
    """门禁放行后走到了 API 步骤。继承 BaseException,免得被 publish 的 except Exception 吞成 exit 1。"""


def _report(*, passed=True, total=10.0, advisory=(), hard_fail=None, artifacts=()):
    return passed, {
        "total_score": total, "mode": "news", "verdict": "", "dimensions": {},
        "hit_phrases": [], "hit_vocab": [], "threshold": 45.0,
        "advisory": list(advisory), "hard_fail": hard_fail, "artifacts": list(artifacts),
    }


def _density(line, count=3):
    return {"id": "neg_contrast", "label": "否定对照/翻案", "line": line, "kind": "para", "scope": "density",
            "excerpt": f"第 {line} 行不是这样而是那样", "count": count, "cap": 1, "message": "否定对照/翻案:全文 3 处"}


@pytest.fixture
def article(tmp_path):
    md = tmp_path / "article.md"
    md.write_text(CLEAN_MD, encoding="utf-8")
    return md


@pytest.fixture
def fake_score(monkeypatch):
    """替换 ai_score.check_ai_score,记录调用参数;返回值由测试设定。"""
    calls = []
    state = {"result": _report()}

    def _fake(md, threshold=ai_score.DEFAULT_THRESHOLD, mode="news", **ctx):
        calls.append({"md": md, "threshold": threshold, "mode": mode, **ctx})
        return state["result"]

    monkeypatch.setattr(ai_score, "check_ai_score", _fake)
    return state, calls


# ---------------------------------------------------------------------------
# run_ai_score_gate:四种结局
# ---------------------------------------------------------------------------

def test_advisory_without_log_blocks(article, fake_score, capsys, no_network):
    state, _ = fake_score
    state["result"] = _report(advisory=[ADVISORY_ITEM])
    with pytest.raises(SystemExit) as exc:
        publish.run_ai_score_gate(CLEAN_MD, md_path=article)
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "humanize_log 覆盖检查未通过" in out
    assert "--log-template" in out, "拒发时要告诉用户怎么生成 log 骨架"


def test_advisory_with_unkept_row_blocks(article, fake_score, capsys, no_network):
    """log 里写了'改',但 lint 仍命中 → 说明没改掉,照样拒发。"""
    state, _ = fake_score
    state["result"] = _report(advisory=[ADVISORY_ITEM])
    row = f"| neg_contrast | 9 | {ADVISORY_ITEM['excerpt']} | 改 |  |\n"
    (article.parent / "humanize_log.md").write_text(LOG_HEADER + row, encoding="utf-8")
    with pytest.raises(SystemExit):
        publish.run_ai_score_gate(CLEAN_MD, md_path=article)
    assert "1 项未通过" in capsys.readouterr().out


def test_advisory_with_complete_log_passes(article, fake_score, capsys, no_network):
    state, _ = fake_score
    state["result"] = _report(advisory=[ADVISORY_ITEM])
    row = f"| neg_contrast | 9 | {ADVISORY_ITEM['excerpt']} | 保留 | 官方 changelog 原文 https://example.com |\n"
    (article.parent / "humanize_log.md").write_text(LOG_HEADER + row, encoding="utf-8")
    publish.run_ai_score_gate(CLEAN_MD, md_path=article)   # 不抛 SystemExit 即放行
    assert "结果: 通过" in capsys.readouterr().out


def test_hard_fail_blocks_even_with_low_score(article, fake_score, capsys, no_network):
    state, _ = fake_score
    state["result"] = _report(passed=False, total=5.0, hard_fail="adversarial_chars")
    with pytest.raises(SystemExit) as exc:
        publish.run_ai_score_gate(CLEAN_MD, md_path=article)
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "硬门" in out
    assert "未通过 AI 味检测(总分" not in out, "低分时不该再报总分失败"


def test_score_over_threshold_still_blocks(article, fake_score, no_network):
    state, _ = fake_score
    state["result"] = _report(passed=False, total=60.0)
    with pytest.raises(SystemExit):
        publish.run_ai_score_gate(CLEAN_MD, md_path=article)


@pytest.mark.parametrize("swap", [("升级后跑一遍", "用ΑΙ升级后跑一遍"), ("claude doctor", "Gооgle")],
                         ids=["greek", "cyrillic"])
def test_real_adversarial_chars_block(article, capsys, no_network, swap):
    """不 mock:同形字(希腊 ΑΙ / 西里尔 о)走真实 ai_score 也要被硬门拦下,且拦下的原因是硬门,不是别的。"""
    with pytest.raises(SystemExit):
        publish.run_ai_score_gate(CLEAN_MD.replace(*swap), md_path=article)
    out = capsys.readouterr().out
    assert "未通过硬门 adversarial_chars" in out
    assert "humanize_log 覆盖检查未通过" not in out
    assert "同形字硬门" in out and "总分超限" not in out


# ---------------------------------------------------------------------------
# 拒发提示与 D1/D3 打印
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("report, expect, absent", [
    (_report(passed=False, total=5.0, hard_fail="adversarial_chars"), "同形字硬门", ("humanize_log 未覆盖", "总分超限")),
    (_report(advisory=[ADVISORY_ITEM]), "humanize_log 未覆盖", ("同形字硬门", "总分超限")),
    (_report(passed=False, total=60.0), "总分超限", ("同形字硬门", "humanize_log 未覆盖")),
], ids=["hard", "log", "score"])
def test_block_hint_matches_reason(article, fake_score, capsys, no_network, report, expect, absent):
    state, _ = fake_score
    state["result"] = report
    with pytest.raises(SystemExit):
        publish.run_ai_score_gate(CLEAN_MD, md_path=article)
    out = capsys.readouterr().out
    assert expect in out and not any(a in out for a in absent)
    assert "人味化" not in out
    if expect != "同形字硬门":
        assert "改稿 pass(阶段 3.5)" in out


def test_density_printed_by_rule_without_cap(article, fake_score, capsys, no_network):
    """超量规则按规则成组,只给「全文 N 处」;log 一行原文填 * 就覆盖整条规则。"""
    state, _ = fake_score
    state["result"] = _report(advisory=[_density(9), _density(11), _density(13)])
    with pytest.raises(SystemExit):
        publish.run_ai_score_gate(CLEAN_MD, md_path=article)
    out = capsys.readouterr().out
    assert "[neg_contrast] 否定对照/翻案:全文 3 处(L9/L11/L13)" in out
    assert "上限" not in out and "cap" not in out
    (article.parent / "humanize_log.md").write_text(
        LOG_HEADER + "| neg_contrast | 全文 3 处 | * | 保留 | 三处都是引用官方公告的原话 |\n", encoding="utf-8")
    publish.run_ai_score_gate(CLEAN_MD, md_path=article)
    assert "结果: 通过" in capsys.readouterr().out


def test_keep_overflow_printed_without_cap(article, fake_score, capsys, no_network):
    """保留行超过上限:提示改写,但不把上限数字打出来(D3)。"""
    items = [{**ADVISORY_ITEM, "id": rid, "excerpt": f"{rid} 这一句是需要保留的原文"}
             for rid in ("salience", "staged", "self_qa", "strawman")]
    state, _ = fake_score
    state["result"] = _report(advisory=items)
    rows = "".join(f"| {a['id']} | 9 | {a['excerpt']} | 保留 | 这是引用的官方原话 |\n" for a in items)
    (article.parent / "humanize_log.md").write_text(LOG_HEADER + rows, encoding="utf-8")
    with pytest.raises(SystemExit):
        publish.run_ai_score_gate(CLEAN_MD, md_path=article)
    out = capsys.readouterr().out
    assert "「保留」过多(已有 4 处)" in out and "「保留」过多:回到 SKILL.md 改稿 pass(阶段 3.5)" in out
    assert "上限" not in out
    assert "humanize_log 未覆盖" not in out and "--log-template" not in out, "只是保留过多时骨架已齐,不再提示生成"


def test_gate_passes_brief_and_context(article, fake_score, no_network):
    """文章同目录 brief.md 的内容、标题、摘要、账号都要原样传给 ai_score。"""
    (article.parent / "brief.md").write_text("## 亲历\n- 上周升级了 2.1\n", encoding="utf-8")
    _, calls = fake_score
    publish.run_ai_score_gate(CLEAN_MD, md_path=article, title="T", digest="D", account="tech")
    ctx = calls[-1]
    assert ctx["brief_text"].startswith("## 亲历")
    assert (ctx["title"], ctx["digest"], ctx["account"]) == ("T", "D", "tech")


def test_log_template_command_mirrors_gate_context(article):
    cmd = publish._log_template_command(article, {"brief_text": "x", "account": "main",
                                                  "title": "标 题", "digest": None})
    assert "--log-template" in cmd and "--account main" in cmd and "--brief" in cmd
    assert "'标 题'" in cmd, "带空格的标题要 shell 转义"
    assert "--digest" not in cmd


# ---------------------------------------------------------------------------
# CLI:--skip-ai-score 与 --digest
# ---------------------------------------------------------------------------

def _run_main(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["publish.py", *argv])
    publish.main()


@pytest.fixture
def stub_api(monkeypatch):
    """微信侧全部打桩:token 直接给,图片原样返回,草稿接口返回假 media_id。"""
    published = []
    monkeypatch.setattr(publish, "get_access_token", lambda: "fake-token")
    monkeypatch.setattr(publish, "process_article_images", lambda md, tmp, base_dir=None: (md, {}, None))
    monkeypatch.setattr(publish, "publish_article", lambda **kw: published.append(kw) or {"media_id": "m-1"})
    return published


def test_skip_ai_score_bypasses_gate(article, tmp_path, monkeypatch, stub_api, tmp_config_yaml, no_network):
    def _boom(*a, **kw):
        raise AssertionError("--skip-ai-score 时不应调用 check_ai_score")

    monkeypatch.setattr(ai_score, "check_ai_score", _boom)
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"\xff\xd8fake")
    _run_main(monkeypatch, ["--input", str(article), "--cover", str(cover), "--author", "a",
                            "--theme", "minimal-mono", "--temp-dir", str(tmp_path / "t"), "--skip-ai-score"])
    assert stub_api and stub_api[0]["title"] == "Claude Code 2.1 更新记录"


def test_manual_digest_goes_through_lint(article, monkeypatch, capsys, tmp_config_yaml, no_network):
    """手动 --digest 走真实 lint:摘要里的否定对照是零容忍位置,必须列出并拒发。"""
    seen = []
    real = ai_score.check_ai_score

    def _spy(md, threshold=ai_score.DEFAULT_THRESHOLD, mode="news", **ctx):
        seen.append(ctx)
        return real(md, threshold, mode, **ctx)

    monkeypatch.setattr(ai_score, "check_ai_score", _spy)
    monkeypatch.setattr(publish, "get_access_token", lambda: (_ for _ in ()).throw(_ReachedApi()))
    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, ["--input", str(article), "--author", "a", "--theme", "minimal-mono",
                                "--digest", DIGEST])
    assert exc.value.code == 1
    assert seen and seen[0]["digest"] == DIGEST
    assert seen[0]["account"] == "main", "账号要从配置解析出来传给 lint"
    out = capsys.readouterr().out
    assert "[neg_contrast] L0 " + DIGEST in out
