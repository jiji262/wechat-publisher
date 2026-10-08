"""第二修复轮(FIX2 E7/E8/E10)的规则回归:引号前非言说归属、摘要钩子词与「,才是」、series/series_ending 占位与匹配。

逐句正反例在 fixtures/rule_cases.json(由 test_zh_tells 参数化跑);这里放需要组合输入的用例。
"""
from __future__ import annotations

import pytest

import fingerprint as FP
import zh_text as T
import zh_tells as Z


def ids(items):
    return {i["id"] for i in items}


def _fp_doc(sections):
    parts = ["# 一个普通的标题", "", "> 导语一句。", ""]
    for h2, paras in sections:
        parts += [f"## {h2}", ""] + [x for p in paras for x in (p, "")]
    return "\n".join(parts)


def _fp_series(root, mds, briefs=None):
    """按日期顺序建一组 main 账号文章(可带 brief.md),返回 article.md 路径列表。"""
    paths = []
    for i, (md, brief) in enumerate(zip(mds, briefs or [None] * len(mds))):
        d = root / "main" / f"2026-09-0{i + 1}-a{i}"
        d.mkdir(parents=True)
        (d / "article.md").write_text(md, encoding="utf-8")
        if brief is not None:
            (d / "brief.md").write_text(brief, encoding="utf-8")
        paths.append(d / "article.md")
    return paths


def _fp_ids(result):
    return [a["id"] for a in result["advisories"]]


# ---------- E8:引号前后的非言说归属 ----------

@pytest.mark.parametrize("text", [
    "换句话说，“这次更新不是修补，而是重写”。", "简单说：“这次更新不是修补，而是重写”。", "一句话说：“这次更新不是修补，而是重写”。",
    "也就是说，“这次更新不是修补，而是重写”。", "老实说，“这次更新不是修补，而是重写”。", "据说：“这次更新不是修补，而是重写”。",
    "我说：“这次更新不是修补，而是重写”。", "“这次更新不是修补，而是重写”，我说。",
])
def test_non_speaker_prefix_is_not_attribution(text):
    assert T.quote_spans(text)[0][2] is False
    assert ("neg_contrast", "digest") in {(i["id"], i["kind"]) for i in Z.lint("正文。\n", digest=text)}


@pytest.mark.parametrize("text", [
    "他淡淡地说：“先跑起来。”", "官方写道：“先跑起来。”", "老张说：“先跑起来。”", "张三在会上表示：“先跑起来。”",
    "他告诉我：“先跑起来。”", "他对我说：“先跑起来。”", "“先跑起来”，他跟我说。",
])
def test_real_attribution_kept(text):
    assert T.quote_spans(text)[0][2] is True


def test_digest_hook_word_and_comma_salience():
    assert ("heading_template", "digest") in {(i["id"], i["kind"]) for i in Z.lint("正文。\n", digest="一个反直觉的结论:写得慢。")}
    assert ("salience", "digest") in {(i["id"], i["kind"]) for i in Z.lint("# 标题\n\n> 慢一点,才是最快的路。\n\n正文第一段。\n")}


# ---------- E7:series_ending ----------

_END_MD = ("## 一\n\n第一节正文写了很多内容。\n\n慢慢来，才是最快的。\n\n## 二\n\n第二节正文也写了很多内容。\n\n"
           "简单的事情重复做，才是真的难。\n\n## 三\n\n第三节正文也写了很多。\n\n长期主义，才是唯一的捷径。\n\n"
           "我是飞哥，一个写了二十年代码的老程序员。\n\n欢迎在评论区聊聊你的做法，我们下期见。\n")


@pytest.mark.parametrize("value", ["\"，\"", "完", "是", "无", "none", "<可选,固定结尾原文>", "\"\""])
def test_series_ending_short_or_placeholder_ignored(value):
    def got(brief=None):
        return [(i["id"], i["line"]) for i in Z.lint(_END_MD, brief_text=brief)]
    assert {"cta_end", "aphorism_end"} <= {i for i, _ in got()}
    assert got(f"---\nseries_ending: {value}\n---\n") == got()


def test_series_ending_multi_paragraph_list_and_ratio():
    brief = "---\nseries_ending:\n  - 我是飞哥，一个写了二十年代码的老程序员。\n  - 欢迎在评论区聊聊你的做法，我们下期见。\n---\n"
    assert "cta_end" not in ids(Z.lint(_END_MD, brief_text=brief))
    joined = "---\nseries_ending: 我是飞哥，一个写了二十年代码的老程序员。欢迎在评论区聊聊你的做法，我们下期见。\n---\n"
    assert "cta_end" in ids(Z.lint(_END_MD, brief_text=joined))      # 一个字符串写两段:长度比 <0.6,不豁免
    escaped = joined.replace("老程序员。", "老程序员。\\n")                # 字面 \n 按段切开
    assert "cta_end" not in ids(Z.lint(_END_MD, brief_text=escaped))
    long = "---\nseries_ending: 欢迎在评论区聊聊你的做法，我们下期见。另外这周还有一个很长很长的补充说明放在这里\n---\n"
    assert "cta_end" in ids(Z.lint(_END_MD, brief_text=long))


# ---------- E7:fingerprint series 占位 ----------

@pytest.mark.parametrize("value", ["无", "none", "<可选,固定栏目名>", "\"\""])
def test_series_placeholder_is_unset(tmp_path, value):
    md = _fp_doc((("第一节", ["先看三个数。", "讲真，这周的东西不多。"]), ("写在最后", ["收尾正文，说点具体的事情。"])))
    plain = _fp_ids(FP.run(_fp_series(tmp_path / "a", [md] * 3)[-1], "main", tmp_path / "a", last=5))
    paths = _fp_series(tmp_path / "b", [md] * 3, briefs=[f"---\nseries: {value}\n---\n"] * 3)
    res = FP.run(paths[-1], "main", tmp_path / "b", last=5)
    assert res["current"]["series"] is None and _fp_ids(res) == plain
    assert "opening_streak" in plain and "heading_key" in plain


# ---------- 第三轮复核遗留(主编排补修) ----------

def test_spaced_all_lookalike_token_is_homoglyph():
    """空格隔开、整词都是形似拉丁的希腊/西里尔字母(ΑΙ)也算同形字;正常希腊字母单字不算。"""
    import zh_tells
    assert zh_tells.find_adversarial_chars("用 ΑΙ 迁移 Redis")
    assert zh_tells.find_adversarial_chars("用 ΑΙ 写代码的三个月")
    assert not zh_tells.find_adversarial_chars("学习率 α 取 0.01,λ 演算和 Δ 变化")


def test_unsourced_keep_needs_real_source_format():
    """出处格式收紧:brief 后必须是行号或字段名;裸 #1、@ab、brief and 不算(引语条目;亲历见 test_humanize_log)。"""
    import humanize_log as H
    item = {"id": "unsourced_quote", "line": 5, "excerpt": "同事说这个脚本要跑三遍", "scope": "position"}
    brief = '---\ntopic: x\nmaterials:\n  - "同事说这个脚本要跑三遍 | 群聊截图 2026-08-01"\n---\n'

    def ok(reason):
        log = H.render_template([item]).replace("|  |  |", f"| 保留 | {reason} |")
        return not H.uncovered([item], log, han=1000, brief_text=brief)

    assert ok("见brief第4行,群聊截图")
    assert ok("出处 brief materials 第一条")
    assert ok("见 https://example.com/post")
    assert ok("见 issue #12 里作者原话")
    assert not ok("brief and 作者确认过的")
    assert not ok("作者确认过 #1 这条")
    assert not ok("作者在群里 @ab 说过")


def test_two_things_pattern_not_forced_in_title():
    """「和…是两回事」只在正文按密度计,不在标题等零容忍位置强制列出(真人事实句常见)。"""
    import zh_tells
    items = zh_tells.lint("正文一段。\n", title="感冒和流感是两回事")
    assert not [a for a in items if a["id"] == "neg_contrast"]


def test_zheme_shuo_is_not_attribution():
    """「这么说:"…"」是作者自己的话,不能把引号里的否定对照豁免掉。"""
    import zh_text
    assert not zh_text._ATTR_BEFORE.search("这么说:")
    assert not zh_text._ATTR_BEFORE.search("那么说,")
    assert zh_text._ATTR_BEFORE.search("他这样对我说:")


def test_gate_tells_writer_unsourced_needs_source(capsys):
    """拒发时出现 unsourced_* 缺口,要明确提示保留理由须带出处。"""
    import publish
    publish._print_gaps([{"id": "unsourced_experience", "line": 3, "excerpt": "我上周跑了一遍", "scope": "position"}])
    out = capsys.readouterr().out
    assert "只认 brief" in out and "链接证明不了" in out
