"""
toutiao_render 的单元测试。

这个文件覆盖:
- markdown → 头条正文 HTML 的结构映射(标题/段落/列表/引用/代码块/表格)
- 头条的硬约束: 不能有内联样式、不能有 <a>、图片必须带 web_uri
- 行内标记的降级(斜体/高亮/链接 → 纯文本)
- HTML 转义与 front matter 剥离
- 标题长度校验

头条会丢弃所有 style 属性和 <a> 标签(见 references/toutiao-publish-research.md 4.3),
所以这里的断言不是风格偏好,是平台事实。
"""

from __future__ import annotations

import pytest

from toutiao_render import (
    ToutiaoRenderError,
    render_toutiao_html,
    validate_title,
)


def _img_info(width=960, height=540):
    """模拟 /spice/image 上传成功后返回的 data 结构。"""
    return {
        "image_url": "https://p3-sign.toutiaoimg.com/fake~tplv-obj.image",
        "image_uri": "tos-cn-i-6w9my0ksvp/abc123",
        "image_width": width,
        "image_height": height,
        "image_mime_type": "image/jpeg",
    }


# ---------------------------------------------------------------------------
# 平台硬约束
# ---------------------------------------------------------------------------

def test_no_inline_styles_anywhere():
    """头条会清洗掉所有 style 属性,所以我们一开始就不生成。"""
    md = "# 标题\n\n正文**加粗**。\n\n## 小节\n\n- 项目一\n- 项目二\n\n> 引用\n"
    html = render_toutiao_html(md)
    assert "style=" not in html


def test_links_degrade_to_plain_text():
    """头条不允许正文外链,<a> 会被吃掉,所以渲染成纯文本而不是留空。"""
    html = render_toutiao_html("详见[官方文档](https://example.com)说明。")
    assert "<a " not in html
    assert "href" not in html
    assert "官方文档" in html


def test_h1_is_dropped_because_title_is_separate():
    """文章标题走 title 字段,正文里的 H1 不该重复出现。"""
    html = render_toutiao_html("# 我是标题\n\n正文。")
    assert "我是标题" not in html
    assert "正文。" in html


# ---------------------------------------------------------------------------
# 结构映射
# ---------------------------------------------------------------------------

def test_paragraph_and_heading_levels():
    html = render_toutiao_html("## 二级\n\n段落。\n\n### 三级\n")
    assert "<h2>二级</h2>" in html
    assert "<h3>三级</h3>" in html
    assert "<p>段落。</p>" in html


def test_bold_becomes_strong():
    html = render_toutiao_html("这是**重点**内容")
    assert "<strong>重点</strong>" in html


def test_unordered_and_ordered_lists():
    html = render_toutiao_html("- 甲\n- 乙\n\n1. 一\n2. 二\n")
    assert "<ul>" in html and "<li>甲</li>" in html and "<li>乙</li>" in html
    assert "<ol>" in html and "<li>一</li>" in html


def test_blockquote():
    html = render_toutiao_html("> 被引用的话")
    assert "<blockquote>" in html
    assert "被引用的话" in html


def test_fenced_code_block_is_escaped():
    html = render_toutiao_html("```python\nif a < b:\n    pass\n```")
    assert "<pre>" in html and "<code>" in html
    assert "&lt;" in html          # < 必须转义
    assert "if a" in html


def test_inline_code():
    html = render_toutiao_html("用 `pip install` 安装")
    assert "<code>pip install</code>" in html


def test_table():
    md = "| 列A | 列B |\n|---|---|\n| 1 | 2 |\n"
    html = render_toutiao_html(md)
    assert "<table>" in html and "<th>列A</th>" in html and "<td>1</td>" in html


# ---------------------------------------------------------------------------
# 图片
# ---------------------------------------------------------------------------

def test_image_renders_pgc_img_block_with_required_attrs():
    """web_uri / img_width / img_height 缺一不可,否则头条报 7115 图片uri非法。"""
    md = "![配图说明](./pic.png)"
    html = render_toutiao_html(md, image_map={"./pic.png": _img_info()})
    assert 'class="pgc-img"' in html
    assert 'web_uri="tos-cn-i-6w9my0ksvp/abc123"' in html
    assert 'img_width="960"' in html
    assert 'img_height="540"' in html
    assert 'image_type="image/jpeg"' in html


def test_image_alt_becomes_caption():
    html = render_toutiao_html("![一句说明](./pic.png)", image_map={"./pic.png": _img_info()})
    assert '<p class="pgc-img-caption">一句说明</p>' in html


def test_image_without_caption_still_valid():
    html = render_toutiao_html("![](./pic.png)", image_map={"./pic.png": _img_info()})
    assert 'class="pgc-img"' in html
    assert '<p class="pgc-img-caption"></p>' in html


def test_unmapped_image_raises():
    """没上传成功的图片必须响亮失败,而不是产出缺图草稿。"""
    with pytest.raises(ToutiaoRenderError) as e:
        render_toutiao_html("![x](./missing.png)", image_map={})
    assert "missing.png" in str(e.value)


def test_no_external_image_src_survives():
    """外链图片同样要经过 image_map,不能直接透传(头条会拒)。"""
    with pytest.raises(ToutiaoRenderError):
        render_toutiao_html("![x](https://example.com/a.jpg)", image_map={})


# ---------------------------------------------------------------------------
# 行内标记降级与安全
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "md,expect",
    [
        ("*斜体*", "斜体"),
        ("==高亮==", "高亮"),
        ("++下划线++", "下划线"),
        ("%%强调%%", "强调"),
        ("!!警示!!", "警示"),
    ],
)
def test_extended_marks_degrade_to_plain_text(md, expect):
    """头条只认结构标签,自定义标记要剥成纯文本,不能把 == 之类漏到正文里。"""
    html = render_toutiao_html(md)
    assert expect in html
    for ch in ("==", "++", "%%", "!!", "*"):
        assert ch not in html


def test_raw_html_is_escaped():
    html = render_toutiao_html("正文 <script>alert(1)</script> 结束")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_front_matter_is_stripped():
    md = "---\ntitle: 不该出现\nauthor: x\n---\n\n正文。"
    html = render_toutiao_html(md)
    assert "不该出现" not in html
    assert "正文。" in html


def test_ampersand_escaped():
    html = render_toutiao_html("A & B")
    assert "&amp;" in html


# ---------------------------------------------------------------------------
# 标题校验
# ---------------------------------------------------------------------------

def test_validate_title_accepts_normal():
    assert validate_title("  一个正常的标题  ") == "一个正常的标题"


@pytest.mark.parametrize("bad", ["", "  ", "短"])
def test_validate_title_rejects_too_short(bad):
    with pytest.raises(ToutiaoRenderError):
        validate_title(bad)


def test_validate_title_rejects_too_long():
    with pytest.raises(ToutiaoRenderError) as e:
        validate_title("标" * 31)
    assert "30" in str(e.value)


def test_validate_title_accepts_exactly_30():
    assert len(validate_title("标" * 30)) == 30


# ---------------------------------------------------------------------------
# 代码审查发现的回归(每条对应一个真实缺陷)
# ---------------------------------------------------------------------------

def test_snake_case_identifiers_survive():
    """曾经有条 _斜体_ 规则会把 user_name 吃成 username —— 技术文里这是静默数据损坏。"""
    html = render_toutiao_html("变量 user_name 和 max_retries 还有 __init__")
    assert "user_name" in html
    assert "max_retries" in html
    assert "__init__" in html


def test_inline_code_content_is_not_reprocessed():
    """行内代码必须隔离,否则后面的粗体/标记正则会钻进去改内容。"""
    assert "<code>foo_bar_baz</code>" in render_toutiao_html("用 `foo_bar_baz` 调用")
    assert "<code>a**b**c</code>" in render_toutiao_html("`a**b**c`")
    assert "<code>x==y</code>" in render_toutiao_html("`x==y`")


def test_front_matter_with_leading_blank_line():
    """带前导空行的 front matter 也要剥掉,否则和微信侧产出不一致。"""
    html = render_toutiao_html("\n---\ntitle: 不该出现\n---\n\n正文。")
    assert "不该出现" not in html
    assert "<hr>" not in html
    assert "正文。" in html


def test_image_in_list_item_still_checked_and_hoisted():
    """li 里不能嵌图片块,但'必须先上传'的守卫不能因此被绕过。"""
    with pytest.raises(ToutiaoRenderError):
        render_toutiao_html("- 看图 ![a](./missing.png)", image_map={})

    html = render_toutiao_html("- 看图 ![a](./pic.png)", image_map={"./pic.png": _img_info()})
    assert "<li>看图</li>" in html
    assert html.index("</ul>") < html.index("pgc-img")   # 图片提到列表之后


def test_image_in_table_cell_still_checked():
    with pytest.raises(ToutiaoRenderError):
        render_toutiao_html("| a | ![x](./missing.png) |\n|---|---|\n| 1 | 2 |", image_map={})


def test_image_in_blockquote_is_hoisted_out():
    html = render_toutiao_html("> 引用 ![a](./pic.png)", image_map={"./pic.png": _img_info()})
    assert "<blockquote><p>引用</p></blockquote>" in html
    assert html.index("</blockquote>") < html.index("pgc-img")


def test_hash_without_space_is_not_a_heading():
    """#话题标签 不是标题,不能整行丢掉。"""
    html = render_toutiao_html("#话题标签\n\n正文。")
    assert "话题标签" in html
    assert "正文。" in html


def test_caption_not_double_escaped():
    html = render_toutiao_html("![a<b & c](./pic.png)", image_map={"./pic.png": _img_info()})
    assert "&amp;lt;" not in html          # 不能双重转义
    assert "&lt;" in html and "&amp;" in html


def test_forged_image_token_is_neutralized():
    """用户 markdown 里塞裸 NUL 不能让渲染器崩成 IndexError。"""
    html = render_toutiao_html("正文 \x00IMG0\x00 结束")
    assert "正文" in html and "结束" in html


def test_missing_image_fields_raise_clearly():
    """头条少返字段时要报可读的错,不能是 KeyError。"""
    with pytest.raises(ToutiaoRenderError) as e:
        render_toutiao_html("![x](./p.png)", image_map={"./p.png": {"image_width": 1}})
    assert "缺字段" in str(e.value)
