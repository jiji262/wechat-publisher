"""fingerprint.py:跨篇指纹(DC-13 修订版 + critic)。全部用 tmp_path 构造假的 mp-articles,不依赖真实稿件。"""
from __future__ import annotations

import json

import fingerprint as FP


def _doc(title="一个普通的标题", digest="导语一句。", sections=(("第一节", ["正文第一段，说一件事。"]),)):
    parts = [f"# {title}", "", f"> {digest}", ""]
    for h2, paras in sections:
        parts += [f"## {h2}", ""]
        for p in paras:
            parts += [p, ""]
    return "\n".join(parts)


def _art(root, name, md, acct="main", brief=None):
    d = root / acct / name
    d.mkdir(parents=True)
    (d / "article.md").write_text(md, encoding="utf-8")
    if brief is not None:
        (d / "brief.md").write_text(brief, encoding="utf-8")
    return d / "article.md"


def _series(root, mds, acct="main", briefs=None):
    """按日期顺序建一组文章,返回 article.md 路径列表。"""
    briefs = briefs or [None] * len(mds)
    return [_art(root, f"2026-09-0{i + 1}-a{i}", md, acct, b) for i, (md, b) in enumerate(zip(mds, briefs))]


def _ids(result):
    return [a["id"] for a in result["advisories"]]


# ---------- 排序与窗口 ----------
def test_date_key_mixed_naming_order(tmp_path):
    for n in ("2026-10-01-b", "20260920-a", "2026-09-30-c"):
        _art(tmp_path, n, _doc())
    names = [p.parent.name for p in FP.list_articles(tmp_path, "main")]
    assert names == ["20260920-a", "2026-09-30-c", "2026-10-01-b"]


def test_history_only_before_current_and_limited(tmp_path):
    paths = _series(tmp_path, [_doc()] * 4)
    hist = FP.history_for(paths[2], tmp_path, "main", last=5)
    assert [p.parent.name for p in hist] == [paths[0].parent.name, paths[1].parent.name]
    assert [p.parent.name for p in FP.history_for(paths[2], tmp_path, "main", last=1)] == [paths[1].parent.name]


# ---------- opening ----------
def test_opening_hook_from_yaml_and_bullet_brief(tmp_path):
    a = _art(tmp_path, "2026-09-01-a", _doc(), brief="---\nopening_hook: hard-number\nseries: 周刊\n---\n")
    b = _art(tmp_path, "2026-09-02-b", _doc(), brief="# brief\n\n- **opening_hook**:`hard-number`(这个数字就是钩子)\n")
    fa, fb = FP.features(a), FP.features(b)
    assert fa["hook"] == fb["hook"] == "hard-number"
    assert fa["series"] == "周刊"


def test_opening_class_rules():
    assert FP.opening_class("`2,768,000,000`。") == "number"
    assert FP.opening_class("2024 年 3 月 5 日，国务院总理在政府工作报告中提出。") == "other"
    assert FP.opening_class("“这个能用吗？”他问。") == "quote"
    assert FP.opening_class("你有没有算过一次会话烧多少钱？") == "question"
    assert FP.opening_class("上周五凌晨两点，我盯着账单发呆。") == "scene"
    assert FP.opening_class("上周三，市场监管总局通报了一批不合格产品。") == "other"
    assert FP.opening_class("先看三个数。") == "staged"


def test_opening_skips_digest_quote(tmp_path):
    p = _art(tmp_path, "2026-09-01-a", _doc(sections=(("第一节", ["先看三个数。", "第二段。"]),)))
    assert FP.features(p)["opening"] == "staged"


# ---------- ending ----------
def _ending(tmp_path, paras, name="2026-09-01-a"):
    return FP.features(_art(tmp_path, name, _doc(sections=(("收尾这一节", paras),))))["ending"]


def test_ending_cta_found_before_last_para(tmp_path):
    tags = _ending(tmp_path, ["如果你手上有 agent 在跑，今天可以花十分钟做一件事：翻一遍日志。",
                              "我上周数了一遍我自己的。比我以为的多得多。"])
    assert "cta" in tags and "punchline" in tags


def test_ending_last_para_categories(tmp_path):
    assert "aphorism" in _ending(tmp_path, ["前面一段比较长的正文。", "代码会变。这个判断大概不会。"], "2026-09-01-a")
    assert "link_or_cmd" in _ending(tmp_path, ["仓库在 `github.com/x/y`，自己去看。"], "2026-09-02-b")
    assert "engage" in _ending(tmp_path, ["两种方案都试过了。你会怎么选？"], "2026-09-03-c")
    assert "question" in _ending(tmp_path, ["这件事最后会怎样，还没有人知道？"], "2026-09-04-d")


def test_ending_skips_boilerplate(tmp_path):
    assert "aphorism" in _ending(tmp_path, ["代码会变。这个判断大概不会。", "（全文完）"])


def test_cta_repeat_advisory(tmp_path):
    cta = _doc(sections=(("收尾", ["这周抽十分钟，把日志翻一遍。", "就这些。后面再说说别的事情吧。"]),))
    paths = _series(tmp_path, [cta, _doc(), cta])
    res = FP.run(paths[-1], "main", tmp_path, last=5)
    assert "ending_cta" in _ids(res)
    adv = next(a for a in res["advisories"] if a["id"] == "ending_cta")
    assert paths[0].parent.name in adv["articles"]


def test_ending_streak_any_category(tmp_path):
    link = _doc(sections=(("收尾", ["仓库地址 `github.com/a/b`，直接读 README。"]),))
    paths = _series(tmp_path, [link, link, link])
    assert "ending_streak" in _ids(FP.run(paths[-1], "main", tmp_path, last=5))


def test_no_advisory_when_history_short(tmp_path):
    link = _doc(sections=(("写在最后", ["讲真，仓库地址 `github.com/a/b`。"]),))
    paths = _series(tmp_path, [link, link])
    assert FP.run(paths[-1], "main", tmp_path, last=5)["advisories"] == []


# ---------- opening streak ----------
def test_opening_streak_but_not_other(tmp_path):
    staged = _doc(sections=(("第一节", ["先看三个数。", "正文。"]),))
    paths = _series(tmp_path, [staged] * 3)
    assert "opening_streak" in _ids(FP.run(paths[-1], "main", tmp_path, last=5))
    other = _doc(sections=(("第一节", ["这是一段普通的叙述句子。"]),))
    paths = _series(tmp_path / "x", [other] * 3)
    assert "opening_streak" not in _ids(FP.run(paths[-1], "main", tmp_path / "x", last=5))


# ---------- heading keys ----------
def test_heading_keys_normalize_templates():
    keys = FP.heading_keys(["踩过的 3 个坑", "三个坑", "写在最后的话", "最后说两句", "开篇"])
    assert keys.count("tpl:个坑") == 1
    assert "func:close" in keys and "func:open" in keys


def test_heading_hook_words_use_zh_rules_template():
    """情绪钩子词按 zh_rules.HEADING_TEMPLATE 认,按族记一个 key;已归一成 N 个坑 的不重复记。"""
    assert FP.heading_keys(["一个反直觉的发现"]) == ["tpl:heading_template"]
    assert FP.heading_keys(["这才是真正的瓶颈"]) == ["tpl:heading_template"]
    assert FP.heading_keys(["踩过的 3 个坑"]) == ["tpl:个坑"]
    assert FP.heading_keys(["缓存命中率"]) == []


def test_func_close_synonyms_streak(tmp_path):
    mds = [_doc(sections=(("第一节", ["正文。"]), (h, ["收尾正文，说点具体的事情。"])))
           for h in ("写在最后", "最后说两句", "写在最后的话")]
    paths = _series(tmp_path, mds)
    res = FP.run(paths[-1], "main", tmp_path, last=5)
    assert any(a["id"] == "heading_key" and "func:close" in a["message"] for a in res["advisories"])


# ---------- tics ----------
def _tic_doc(line):
    return _doc(sections=(("第一节", [line, "后面是一段普通的正文。"]),))


def test_tic_family_requires_current(tmp_path):
    paths = _series(tmp_path, [_tic_doc("讲真，这个很好用。"), _tic_doc("说实话，这个很难用。"), _tic_doc("讲真，又来了。")])
    res = FP.run(paths[-1], "main", tmp_path, last=5)
    assert any(a["id"] == "tic_family" and "candor_tic" in a["message"] for a in res["advisories"])
    paths = _series(tmp_path / "x", [_tic_doc("讲真，这个很好用。"), _tic_doc("说实话，这个很难用。"), _tic_doc("普通的一句话。")])
    assert "tic_family" not in _ids(FP.run(paths[-1], "main", tmp_path / "x", last=5))


def test_research_act_family(tmp_path):
    mds = [_tic_doc(s) for s in ("我翻了一遍 issue 列表。", "我翻了三个仓库的提交。", "我翻了日志才看明白。")]
    paths = _series(tmp_path, mds)
    res = FP.run(paths[-1], "main", tmp_path, last=5)
    assert any(a["id"] == "tic_family" and "research_act" in a["message"] for a in res["advisories"])


def test_research_act_words_come_from_zh_tells():
    """研究者动作族 = zh_tells.TICS 去掉口头禅族;fingerprint 不另写词表。"""
    import zh_tells
    assert not hasattr(FP, "TPL_WORDS")
    f = FP._tic_features(_tic_doc("我对照了两份日志。"))
    assert "我对照了" in zh_tells.TICS and f["tics"]["research_act"] == ["我对照了"]


# ---------- series 豁免 ----------
def test_series_exempts_opening_and_heading_not_tics(tmp_path):
    md = _doc(sections=(("第一节", ["先看三个数。", "讲真，这周的东西不多。"]), ("写在最后", ["收尾正文，说点具体的事情。"])))
    brief = "---\nseries: 周报\n---\n"
    paths = _series(tmp_path, [md] * 3, briefs=[brief] * 3)
    ids = _ids(FP.run(paths[-1], "main", tmp_path, last=5))
    assert "opening_streak" not in ids and "heading_key" not in ids
    assert "tic_family" in ids


# ---------- 标题 / 摘要 / 小标题形状 ----------
def test_title_shape_tags():
    assert "comma_turn" in FP.title_shape("Claude Code 终于读 AGENTS.md 了，但先别急着删 symlink")
    assert "colon" in FP.title_shape("Apache 收编了一个 AI Agent，开口第一句是：聊天记录不算数")
    assert "question" in FP.title_shape("27.8 亿 token 烧在哪了？我扒了 793MB 会话日志")
    assert FP.title_shape("我把 Code Agent 拆成了 23 节可运行的课") == []


def test_title_shape_streak(tmp_path):
    mds = [_doc(title=t) for t in ("他做了一件事，然后放弃了", "一个人拆了很多图，把它写成协议", "模型终于更新了，但先别急")]
    paths = _series(tmp_path, mds)
    assert "title_shape_streak" in _ids(FP.run(paths[-1], "main", tmp_path, last=5))


def test_digest_shape_tags():
    assert "neg_contrast" in FP.digest_shape("结论比我想的难堪：钱不是花在想上，是花在重复念稿上。")
    tags = FP.digest_shape("4667 个赞、361 条评论、等了 13 个月，换来的是一行 changelog。")
    assert "number_pile" in tags and "turn" in tags


def test_digest_shape_streak(tmp_path):
    mds = [_doc(digest=d) for d in ("钱不是花在想上，是花在念稿上。", "这不是估算，这是实测。", "问题不在模型，而在流程。")]
    paths = _series(tmp_path, mds)
    assert "digest_shape_streak" in _ids(FP.run(paths[-1], "main", tmp_path, last=5))


def test_heading_shape(tmp_path):
    colon = [("先别删：三个原因", ["正文。"]), ("拆第一层：入口", ["正文。"]), ("拆第二层：历史", ["正文。"])]
    short = [("先看数字", ["正文。"]), ("账单", ["正文。"]), ("你该抄什么", ["正文。"])]
    assert FP.heading_shape([h for h, _ in colon]) == "colon"
    assert FP.heading_shape([h for h, _ in short]) == "short"
    paths = _series(tmp_path, [_doc(sections=colon)] * 3)
    assert "heading_shape_streak" in _ids(FP.run(paths[-1], "main", tmp_path, last=5))
    paths = _series(tmp_path / "x", [_doc(sections=short)] * 3)
    assert "heading_shape_streak" not in _ids(FP.run(paths[-1], "main", tmp_path / "x", last=5))


def test_h2_similarity(tmp_path):
    secs = (("上下文窗口怎么被吃掉", ["正文。"]), ("子代理为什么背着整段历史", ["正文。"]))
    other = (("缓存命中率说明什么", ["正文。"]), ("账单里的输入输出比", ["正文。"]))
    assert FP.h2_similarity(["A 上下文窗口 3"], ["上下文窗口 B"]) == 1.0
    paths = _series(tmp_path, [_doc(sections=other), _doc(sections=secs), _doc(sections=secs)])
    assert "h2_similar" in _ids(FP.run(paths[-1], "main", tmp_path, last=5))
    paths = _series(tmp_path / "x", [_doc(sections=other), _doc(sections=other), _doc(sections=secs)])
    assert "h2_similar" not in _ids(FP.run(paths[-1], "main", tmp_path / "x", last=5))


def test_simile_recorded_and_repeat(tmp_path):
    mds = [_tic_doc(s) for s in ("架构图画得像地铁线路。", "普通的一句话。", "这套流程也像地铁线路。")]
    paths = _series(tmp_path, mds)
    assert "地铁线路" in FP.features(paths[0])["similes"]
    assert "simile_repeat" in _ids(FP.run(paths[-1], "main", tmp_path, last=5))


# ---------- 坏稿 ----------
def _bad_history(root):
    """三篇正常稿中间夹一篇非 UTF-8 的历史稿,返回 (坏稿路径, 当前稿路径)。"""
    paths = _series(root, [_doc()] * 4)
    paths[1].write_bytes(b"\xff\xfe bad")
    return paths[1], paths[-1]


def test_bad_history_article_skipped_with_warning(tmp_path):
    bad, cur = _bad_history(tmp_path)
    res = FP.run(cur, "main", tmp_path, last=5)
    assert res["current"] is not None and len(res["history"]) == 2
    assert any(n.startswith("警告:跳过历史稿") and str(bad) in n for n in res["notes"])


def test_bad_history_cli_still_renders(tmp_path, capsys):
    bad, cur = _bad_history(tmp_path)
    for argv in ([str(cur), "--root", str(tmp_path)], ["--account", "main", "--root", str(tmp_path)]):
        assert FP.main(argv) == 0
        out = capsys.readouterr().out
        assert "未执行" not in out and "跳过历史稿" in out and str(bad) in out


def test_bad_current_article_reports_not_run(tmp_path, capsys):
    paths = _series(tmp_path, [_doc()] * 3)
    paths[-1].write_bytes(b"\xff\xfe bad")
    assert FP.main([str(paths[-1]), "--root", str(tmp_path)]) == 0
    assert "fingerprint 未执行" in capsys.readouterr().out


# ---------- CLI ----------
def test_cli_json_exit0(tmp_path, capsys):
    paths = _series(tmp_path, [_doc()] * 3)
    assert FP.main([str(paths[-1]), "--root", str(tmp_path), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["current"]["name"] == paths[-1].parent.name
    assert len(out["history"]) == 2 and "advisories" in out


def test_cli_list_mode_without_article(tmp_path, capsys):
    paths = _series(tmp_path, [_doc()] * 4)
    assert FP.main(["--account", "main", "--root", str(tmp_path), "--last", "3"]) == 0
    out = capsys.readouterr().out
    assert paths[-1].parent.name in out and paths[0].parent.name not in out


def test_cli_missing_root_exit0(tmp_path, capsys):
    assert FP.main(["--root", str(tmp_path / "nope")]) == 0


def test_account_inferred_from_path(tmp_path, capsys):
    paths = _series(tmp_path, [_doc()] * 3, acct="tech")
    assert FP.main([str(paths[-1]), "--root", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["account"] == "tech"
