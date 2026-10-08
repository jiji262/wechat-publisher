"""zh_text / zh_tells:切句、mask、文本单元、advisory 规则正反例、artifacts、对抗字符硬门。

正例取自 .work/detector-specs.md 的修订规格与 tests/fixtures/claude_tells.md(本 skill 存量稿摘句),
反例取自 detector-specs 的反例与人工核对出的误报句。不读取 mp-articles。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import zh_text as T
import zh_tells as Z

FIXTURES = Path(__file__).parent / "fixtures"
CLAUDE = (FIXTURES / "claude_tells.md").read_text(encoding="utf-8")
HUMAN = (FIXTURES / "human_public_domain.md").read_text(encoding="utf-8")

CONTRACT_IDS = {
    "neg_contrast", "neg_listing", "empty_short_para", "fake_reaction", "candor_tic", "perf_imperfect", "salience",
    "staged", "colon_reveal", "self_qa", "strawman", "restate", "aphorism_end", "cta_end", "triad", "couplet",
    "heading_template", "dash_overuse", "highlight_sentence", "no_stance", "unsourced_experience",
    "unsourced_quote", "hedge_stack", "false_agency",
}


def ids(items):
    return {i["id"] for i in items}


# ---------- zh_text ----------

@pytest.mark.parametrize("text,expected", [
    ("真的吗？对！好；嗯。", 4),
    ("真的?!不会吧。", 2),
    ("“好的。”然后走了。", 2),
    ("等等……然后呢？", 1),
    ("版本 2.1.277 不切。", 1),
    ("第一行\n第二行", 2),
])
def test_split_sentences_fullwidth_and_newline(text, expected):
    assert len(T.split_sentences(text)) == expected


def test_split_keeps_closing_quote_in_sentence():
    assert T.split_sentences("“好的。”然后走了。") == ["“好的。”", "然后走了。"]


@pytest.mark.parametrize("md", [
    "---\ntitle: x\n---\n正文", "---\r\ntitle: x\r\n---\r\n正文", "﻿---\ntitle: x\n---\n正文", "---\ntitle: x\n---",
    "---\n# 注释\ntitle: x\n---\n正文",
])
def test_strip_front_matter_variants(md):
    assert "title:" not in T.strip_front_matter(md)


def test_leading_hr_is_not_front_matter():
    md = "---\n\n开头一段话。\n\n---\n\n第二段。"
    assert "开头一段话" in T.strip_front_matter(md)


def test_mask_keeps_length_and_lines():
    md = CLAUDE + "\n```python\nx = 1; y = 2\n```\n~~~\n未闭合\n"
    masked = T.mask_markdown(md)
    assert len(masked) == len(T.normalize(md))
    assert masked.count("\n") == T.normalize(md).count("\n")
    assert "2,768,000,000" not in masked and "x = 1" not in masked and "未闭合" not in masked


def test_url_masked_without_eating_text():
    masked = T.mask_markdown("详见 https://a.b/c?d=1 这里。然后")
    assert "?" not in masked and "这里。然后" in masked


def test_text_units_kinds_and_lines():
    md = "# 标题行\n\n> 摘要行\n\n## 小节\n\n正文第一句。\n第二行。\n\n- 列表项\n\n![图注文字](a.png)\n"
    units = T.text_units(md, title="外部标题", digest="外部摘要")
    by_kind = {u["kind"]: u for u in units if u["line"]}
    assert by_kind["title"]["line"] == 1 and by_kind["digest"]["line"] == 3
    assert by_kind["heading"]["section"] == 1 and by_kind["para"]["line"] == 7
    assert by_kind["list"]["text"] == "列表项" and by_kind["caption"]["text"] == "图注文字"
    assert {(u["kind"], u["line"]) for u in units if u["line"] == 0} == {("title", 0), ("digest", 0)}


def test_attributed_quote_is_blanked_unattributed_kept():
    assert "终点" not in T.blank_attributed("他说：“这不是终点，而是起点。”")
    assert "终点" in T.blank_attributed("“这不是终点，而是起点。”")
    # 同一句里有出处才算归属(按句,不按整段)
    assert "终点" not in T.blank_attributed("“这不是终点，而是起点”,出处 。", raw="“这不是终点，而是起点”,出处 https://x.y/z 。")
    assert "终点" in T.blank_attributed("“这不是终点，而是起点”。\n另见 。", raw="“这不是终点，而是起点”。\n另见 https://x.y/z 。")


@pytest.mark.parametrize("text,attributed", [
    ("“这不是终点，而是起点。”，说白了就是重构。", False), ("“降本增效”这个说法早就被用烂了。", False),
    ("“先跑起来”，这么说。", False), ("“先跑起来”，张三说。", True), ("“先跑起来”——CTO 在发布会上这样说。", True),
])
def test_attribution_after_quote(text, attributed):
    assert T.quote_spans(text)[0][2] is attributed


def test_quote_wrapped_digest_still_linted():
    assert ("neg_contrast", "digest") in {(i["id"], i["kind"]) for i in
                                         Z.lint("正文。\n", digest="“这次更新不是修补，而是重写”，说白了就是重构。")}


# ---------- advisory 规则正反例 ----------

CASES = json.loads((FIXTURES / "rule_cases.json").read_text(encoding="utf-8"))
POSITIVE, NEGATIVE, NOT_LISTED = CASES["positive"], CASES["negative"], CASES["not_listed"]


@pytest.mark.parametrize("rid,text", [(r, t) for r, xs in POSITIVE.items() for t in xs])
def test_rule_positive(rid, text):
    hits, _ = Z.scan(text)
    assert hits[rid], f"{rid} 漏检: {text}"


@pytest.mark.parametrize("rid,text", [(r, t) for r, xs in NEGATIVE.items() for t in xs])
def test_rule_negative(rid, text):
    hits, _ = Z.scan(text)
    assert not hits[rid], f"{rid} 误报: {text} -> {hits[rid]}"


@pytest.mark.parametrize("rid,text", [(r, t) for r, xs in NOT_LISTED.items() for t in xs])
def test_rule_not_listed(rid, text):
    assert rid not in ids(Z.lint(text)), f"{rid} 不应列出: {text}"


def test_rule_ids_match_contract():
    assert {r.id for r in Z.RULES} == CONTRACT_IDS
    assert set(Z.RULE_LABELS) == CONTRACT_IDS and all(Z.RULE_LABELS.values())


# ---------- lint:只返回需要处理的条目 ----------

def test_lint_item_shape():
    items = Z.lint(CLAUDE)
    assert items
    for it in items:
        assert {"id", "label", "line", "kind", "excerpt", "count", "cap", "message"} <= set(it)


def test_claude_fixture_covers_many_rules():
    found = ids(Z.lint(CLAUDE))
    assert len(found) >= 6
    assert {"neg_contrast", "fake_reaction", "empty_short_para", "heading_template", "cta_end", "couplet"} <= found


def test_human_fixture_has_only_provenance_checks():
    # 朱自清的回忆散文:第一人称亲历按设计列为"待核对",其余规则不应命中
    assert ids(Z.lint(HUMAN)) <= {"unsourced_experience"}


def test_under_cap_body_hit_not_listed_but_zero_tolerance_positions_are():
    body = "这是一段很普通的正文。" * 200
    assert "neg_contrast" not in ids(Z.lint(body + "\n\n这不是还没做完,这是设计。\n"))
    items = Z.lint(body, title="这不是一次升级,而是一次范式转移", digest="真正值得关注的不是速度,是它的价格")
    assert {("neg_contrast", "title"), ("neg_contrast", "digest"), ("salience", "digest")} <= {(i["id"], i["kind"]) for i in items}


def test_over_cap_lists_all_hits():
    items = [i for i in Z.lint("这不是还没做完,这是设计。\n\n它不是工具,而是同事。\n") if i["id"] == "neg_contrast"]
    assert len(items) == 2 and items[0]["count"] == 2 and items[0]["cap"] == 1


def test_caption_zero_tolerance():
    assert "neg_contrast" in ids(Z.lint("正文。\n\n![压缩是投影不是变更](a.png)\n"))
    assert "aphorism_end" in ids(Z.lint("正文。\n\n![核心结论](a.png)\n"))
    assert not Z.lint("正文。\n\n![主线程与子代理的消耗对比](a.png)\n")


def test_scope_and_message_hide_cap():
    items = Z.lint("这不是还没做完,这是设计。\n\n它不是工具,而是同事。\n", title="这不是升级,而是范式转移")
    scope = {(i["kind"], i["scope"]) for i in items if i["id"] == "neg_contrast"}
    assert scope == {("title", "position"), ("para", "density")}
    assert all("上限" not in i["message"] and str(i["cap"]) not in i["message"].split("全文")[0] for i in items)
    assert {i["scope"] for i in Z.lint("这个开头我看了三遍。\n")} == {"position"}   # cap=0 规则逐条


def test_caption_hits_not_counted_for_section_end():
    md = "## 一\n\n正文。\n\n慢慢来，比较快。\n\n## 二\n\n正文。\n\n简单的事情重复做。\n\n![核心结论](a.png)\n"
    assert [i["kind"] for i in Z.lint(md) if i["id"] == "aphorism_end"] == ["caption"]


@pytest.mark.parametrize("last", ["代码会变，判断不会。", "真正的护城河，从来都是判断力。"])
def test_real_aphorism_at_article_end_forced(last):
    assert "aphorism_end" in ids(Z.lint(f"## 一\n\n第一节正文有具体内容。\n\n{last}\n"))


def test_section_end_skips_link_line():
    md = "".join(f"## {i}\n\n正文 {i} 写了一些东西。\n\n同一个坑，两拨人各自摔一遍。\n\n🔗 GitHub:https://x.y/{i}\n\n" for i in "一二三")
    assert len(Z.scan(md)[0]["aphorism_end"]) == 3


def test_series_ending_exempt():
    md = "## 一\n\n正文写了很多内容。\n\n欢迎在评论区聊聊你的做法。\n"
    assert "cta_end" in ids(Z.lint(md))
    brief = "---\nseries_ending: 欢迎在评论区聊聊你的做法\n---\n"
    assert not {"cta_end", "aphorism_end"} & ids(Z.lint(md, brief_text=brief))


def test_brief_outline_lines_linted():
    brief = "---\ntopic: x\n---\n\n## 结构规划\n\n1. 开篇:甩数字 + 这不是估算是日志实测\n2. 账单长什么样\n"
    got = {(i["id"], i["kind"], i["line"]) for i in Z.lint("正文。\n", brief_text=brief)}
    assert {("functional_heading", "brief", 7), ("neg_contrast", "brief", 7)} <= got
    assert not [g for g in got if g[2] == 8]


def test_number_only_paragraph_always_listed():
    items = Z.lint("这是一个 session 的输入 token。\n\n`2,768,000,000`。\n")
    assert [i["id"] for i in items] == ["empty_short_para"]
    assert not Z.lint("输入输出比 `644:1`。\n")
    assert [i["id"] for i in Z.lint("正文有 3 件事。\n\n100\n")] == ["empty_short_para"]   # 3 位以上不算章节序号


def test_account_banned_tic():
    text = "这个方案讲真不错,代码也少。\n"
    assert "candor_tic" in ids(Z.lint(text, account="main"))
    assert "candor_tic" not in ids(Z.lint(text, account="tech"))


def test_brief_experiences_exempt_first_person():
    text = "我上周数了一遍自己的调用日志,一共 184 个子代理。\n"
    assert Z.lint(text)[0]["message"].startswith("待核对")
    brief = "---\nexperiences:\n  - 上周数了一遍自己的调用日志,184 个子代理\n---\n"
    assert "unsourced_experience" not in ids(Z.lint(text, brief_text=brief))
    other = "---\nexperiences:\n  - 去年在一家创业公司做过推荐系统\n---\n"
    assert "unsourced_experience" in ids(Z.lint(text, brief_text=other))


def test_attributed_quote_exempt_and_scare_quote_removed():
    text = "他在 issue 里写道:“这不是 bug,而是 feature。”\n"
    assert "neg_contrast" not in ids(Z.lint(text))
    scare = "".join(f"这里有\"概念{i}\"和\"说法{i}\"。" for i in range(4))
    assert "scare_quote" not in Z.RULE_LABELS and not Z.lint(scare)   # E1:无区分力,整条删除


def test_dash_overuse_density():
    heavy = "".join(f"第{i}段话——补一句。\n\n" for i in range(8))
    assert "dash_overuse" in ids(Z.lint(heavy))
    assert "dash_overuse" not in ids(Z.lint("日志——确切说是 rollout 文件——在 sessions 下。\n"))


def test_highlight_sentence_and_heading_marker():
    dense = "".join(f"第 {i} 段。**这一整句都是加粗的结论句。**\n\n" for i in range(6))
    assert "highlight_sentence" in ids(Z.lint(dense))
    assert "highlight_sentence" in ids(Z.lint("## 场景:用 @@HyperFrames@@\n\n正文。\n"))


# ---------- artifacts / 对抗字符 ----------

def test_spaced_dash_in_dash_list_item():
    assert "spaced_dash" in Z.score_artifacts("- 列表里这个功能 — 我觉得很好用。\n")[1]["by_id"]
    assert Z.score_artifacts("-- 鲁迅\n")[0] == Z.score_artifacts("— 鲁迅\n")[0] == 0


def test_zero_width_is_artifact_not_hard():
    md = "复制来的\u200b一段话，又有\u200b一处，还有\u200b一处，再\u200b一处，最后\u200b一处。\n"
    assert Z.find_adversarial_chars(md) == [] and "zero_width" in Z.score_artifacts(md)[1]["by_id"]


def test_artifacts_hits():
    md = "## 写在最后\n\n## 开篇:你是不是也以为\n\n忘记判断 end_turn,这破玩意会一直烧 token。\n\n`4667` —— 这是点赞数。\n"
    score, detail = Z.score_artifacts(md)
    found = {h["id"] for h in detail["hits"]}
    assert {"functional_heading", "functional_heading_bare", "instruction_echo", "spaced_dash"} <= found
    assert score > 0


@pytest.mark.parametrize("md", [
    "## 最后一个坑:Windows 上 symlink 失效\n", "## 为什么我又把 symlink 放回去了\n",
    "日志——确切说是 rollout 文件——在 ~/.codex/sessions 下。\n", "版本 2.1.277,发布于 9 月 18 日。\n",
    "国际社会高度关注我国在气候问题上的立场。\n", "我跟你说过多少次了,别在生产环境调试。\n", "> —— 鲁迅《故乡》\n",
])
def test_artifacts_negative(md):
    assert Z.score_artifacts(md)[0] == 0


def test_instruction_echo_is_exported():
    assert "这破玩意" in Z.INSTRUCTION_ECHO and "讲真" in Z.TICS and "我的判断是" in Z.TICS
    assert set(Z.ACCOUNT_BANNED) == {"main", "tech"}


@pytest.mark.parametrize("md", [
    "Gооgle 搜索", "⼈⼯⼤脑", "用ΑΙ写代码",
])
def test_adversarial_hard(md):
    assert Z.find_adversarial_chars(md)


@pytest.mark.parametrize("md", [
    "﻿文件开头的 BOM。", "程序员 👨‍💻 的日常", "β版本今天上线。", "Привет是俄语里的你好。", "复制带来的一个​零宽空格",
    "零\u200b宽\u200b字\u200b符", "正常文字\u202e反转", "α粒子和 μs 级延迟",
])
def test_adversarial_soft_not_hard(md):
    assert Z.find_adversarial_chars(md) == []
