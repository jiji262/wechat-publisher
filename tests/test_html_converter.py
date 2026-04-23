"""
Tests for scripts/html_converter.py.

Focus:
- Plain markdown → HTML roundtrip sanity
- #5 fix: HTML-escaping of raw <script>/<style> and sanitization of javascript: URLs
- #23 fix: unclosed code blocks don't silently drop content
- Inline highlight markers (**, ==, ++) each produce styled output
"""

from __future__ import annotations

import pytest

from html_converter import convert_markdown_to_wechat_html, load_theme


# Shared theme fixture — every test needs the three tuples from load_theme.
@pytest.fixture(scope="module")
def theme():
    styles, highlights, divider = load_theme(theme_name="refined-blue")
    return styles, highlights, divider


def _convert(md: str, theme_tuple) -> str:
    styles, highlights, divider = theme_tuple
    return convert_markdown_to_wechat_html(md, styles, highlights, divider)


# ---------------------------------------------------------------------------
# Basic roundtrip
# ---------------------------------------------------------------------------

def test_plain_paragraph(theme):
    """A plain markdown paragraph should produce a <p ...>content</p> tag."""
    html = _convert("这是一段普通的段落文字。", theme)

    # Output is wrapped in <section>, so just look for the <p>.
    assert "<section" in html
    assert "<p" in html
    assert "这是一段普通的段落文字。" in html


def test_headings_rendered(theme):
    """h2 and h3 markdown should become <h2> and <h3>."""
    md = "## 二级标题\n\n正文\n\n### 三级标题\n\n更多正文"
    html = _convert(md, theme)

    assert "<h2" in html and "二级标题" in html
    assert "<h3" in html and "三级标题" in html


# ---------------------------------------------------------------------------
# Security — #5 fix
# ---------------------------------------------------------------------------

def test_script_tag_is_escaped(theme):
    """
    #5 fix: literal <script>alert(1)</script> in markdown must NOT produce
    a working <script> tag in the output. Content should be HTML-escaped.
    """
    md = "正文开始\n\n```html\n<script>alert(1)</script>\n```\n\n正文结束"
    html = _convert(md, theme)

    # A raw, executable <script> tag with a literal `>` would be dangerous.
    # After escaping, we expect `&lt;script&gt;` instead.
    assert "<script>alert(1)</script>" not in html, (
        "Raw <script> tag leaked through conversion — XSS risk"
    )
    # The escaped form should be present (content preserved, just neutralized).
    assert "&lt;script&gt;" in html or "&lt;script" in html


def test_inline_script_tag_in_code_is_escaped(theme):
    """Inline `<script>` in `\\`code\\`` must also be escaped."""
    md = "看这行内代码:`<script>`"
    html = _convert(md, theme)

    assert "<script>" not in html.replace("&lt;script&gt;", "")


def test_javascript_url_rejected(theme):
    """
    #5 fix: `[click](javascript:alert(1))` should NOT render as a
    working `href="javascript:alert(1)"` link.
    """
    md = "危险链接 [click me](javascript:alert(1))"
    html = _convert(md, theme)

    # The rendered anchor must not contain a javascript: href.
    # Accept either: href removed, or link rewritten, or the literal text
    # stays but no javascript: scheme in href attribute.
    assert 'href="javascript:' not in html.lower(), (
        "javascript: URL leaked into href — XSS risk"
    )


# ---------------------------------------------------------------------------
# Edge cases — #23 fix
# ---------------------------------------------------------------------------

def test_unclosed_code_block_preserved(theme):
    """
    #23 fix: if markdown ends with an unclosed ``` block, the content
    inside the block should not be silently dropped — it should end up
    in the output one way or another (either rendered as a <pre>
    auto-closed, or as plain text).
    """
    md = "## 开头\n\n```python\nprint('hello')\nimportant = 42\n"
    html = _convert(md, theme)

    # The body of the unclosed code block must not vanish completely.
    # We accept either the <pre> wrapper being present OR the raw content
    # making it through — what we DON'T accept is both being missing.
    has_pre = "<pre" in html
    has_content = "important = 42" in html or "print(&#x27;hello&#x27;)" in html or "print('hello')" in html
    assert has_pre or has_content, (
        "Unclosed code block silently dropped its content"
    )


def test_empty_input(theme):
    """Empty markdown should still produce a valid (if empty) <section>."""
    html = _convert("", theme)
    assert "<section" in html
    # The section should close properly.
    assert "</section>" in html


# ---------------------------------------------------------------------------
# Highlight markers
# ---------------------------------------------------------------------------

def test_bold_marker_renders_strong(theme):
    """**bold** should produce a <strong> tag with an inline style."""
    html = _convert("一个 **加粗** 的词", theme)
    assert "<strong" in html and "加粗" in html
    # Inline style must be present (WeChat requires inline styles only).
    assert "style=" in html


def test_highlight_markers_work(theme):
    """
    Each of ==yellow==, ++blue++, %%pink%%, &&green&&, !!red!!, @@blue-em@@,
    ^^orange^^ should produce a styled <span> (or equivalent tag) in output.
    """
    md = (
        "== 黄色高亮 ==\n\n"
        "++ 蓝色高亮 ++\n\n"
        "%% 粉色高亮 %%\n\n"
        "&& 绿色高亮 &&\n\n"
        "!! 红色强调 !!\n\n"
        "@@ 蓝色强调 @@\n\n"
        "^^ 橙色强调 ^^\n"
    )
    # These markers require no whitespace around them to match — rewrite tight.
    md_tight = (
        "==黄色高亮==\n\n"
        "++蓝色高亮++\n\n"
        "%%粉色高亮%%\n\n"
        "&&绿色高亮&&\n\n"
        "!!红色强调!!\n\n"
        "@@蓝色强调@@\n\n"
        "^^橙色强调^^\n"
    )
    html = _convert(md_tight, theme)

    # Each content string must survive and be wrapped in something styled.
    for text in ["黄色高亮", "蓝色高亮", "粉色高亮", "绿色高亮",
                 "红色强调", "蓝色强调", "橙色强调"]:
        assert text in html, f"highlight content '{text}' missing from output"

    # Minimum sanity: at least 7 inline <span> tags with style= for the
    # seven custom markers above.
    assert html.count("<span") >= 7, (
        f"expected >=7 styled <span> from 7 highlight markers; got {html.count('<span')}"
    )


# ---------------------------------------------------------------------------
# Images and links
# ---------------------------------------------------------------------------

def test_image_rendered_with_style(theme):
    """![alt](url) should produce an <img> with inline style."""
    md = "![示例图](https://example.com/img.png)"
    html = _convert(md, theme)

    assert "<img" in html
    assert "https://example.com/img.png" in html
    assert "style=" in html


def test_ordinary_http_link_kept(theme):
    """Normal https: links should render fine (sanity check for #5)."""
    md = "参考 [文档](https://example.com/doc)"
    html = _convert(md, theme)

    assert '<a ' in html
    assert 'https://example.com/doc' in html


# ---------------------------------------------------------------------------
# Sanity: list and blockquote
# ---------------------------------------------------------------------------

def test_unordered_list(theme):
    md = "- 第一项\n- 第二项\n- 第三项\n"
    html = _convert(md, theme)
    assert "<ul" in html
    assert "第一项" in html and "第二项" in html and "第三项" in html


def test_blockquote(theme):
    md = "> 一句引用\n> 的内容\n"
    html = _convert(md, theme)
    assert "<blockquote" in html
    assert "一句引用" in html
