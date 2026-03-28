#!/usr/bin/env python3
"""
Markdown → 微信公众号 HTML 转换器

微信公众号编辑器的特殊限制：
- 不支持外部CSS和JS引用
- 不支持class和id属性（部分支持但不可靠）
- 所有样式必须使用内联style
- 不支持<style>标签
- 不支持position、float等部分CSS属性
- 图片必须使用微信CDN的URL

本转换器将Markdown转换为满足以上限制的HTML，
并应用精美的内联排版样式。
"""

import re
import json
import sys
from pathlib import Path


# ============================================================
# 样式配置
# ============================================================

DEFAULT_STYLES = {
    "body": "font-family: -apple-system, BlinkMacSystemFont, 'Helvetica Neue', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif; font-size: 15px; color: #3f3f3f; line-height: 2; letter-spacing: 0.8px; word-spacing: 2px; padding: 15px 0;",

    "h1": "font-size: 21px; font-weight: 700; color: #1a1a2e; text-align: center; margin: 36px 0 24px; padding-bottom: 14px;",

    "h2": "font-size: 18px; font-weight: 700; color: #1a1a2e; margin: 32px 0 16px; padding: 8px 0 8px 14px; border-left: 4px solid #4a6cf7; background: linear-gradient(to right, #f0f4ff, transparent); border-radius: 0 4px 4px 0; line-height: 1.5;",

    "h3": "font-size: 16px; font-weight: 600; color: #2d3748; margin: 24px 0 12px; padding-left: 10px;",

    "p": "margin: 14px 0; text-indent: 0; text-align: justify; color: #3f3f3f;",

    "blockquote": "margin: 24px 0; padding: 16px 20px 16px 24px; background: #f8f9fc; border-left: 3px solid #4a6cf7; color: #5a6577; font-size: 14px; border-radius: 0 8px 8px 0; line-height: 1.9;",

    "img": "max-width: 100%; height: auto; border-radius: 6px; margin: 20px auto; display: block; box-shadow: 0 4px 16px rgba(0,0,0,0.06);",

    "strong": "color: #4a6cf7; font-weight: 600;",

    "em": "font-style: italic; color: #666;",

    "code_inline": "background: #f1f3f8; color: #4a6cf7; padding: 2px 8px; border-radius: 4px; font-size: 13px; font-family: 'Menlo', 'Consolas', 'SF Mono', monospace;",

    "code_block": "background: #1e1e2e; color: #cdd6f4; padding: 18px 22px; border-radius: 10px; font-size: 13px; line-height: 1.7; font-family: 'Menlo', 'Consolas', 'SF Mono', monospace; overflow-x: auto; white-space: pre-wrap; word-wrap: break-word; margin: 20px 0;",

    "ul": "margin: 14px 0; padding-left: 8px; list-style-type: none;",
    "ol": "margin: 14px 0; padding-left: 24px; list-style-type: decimal;",
    "li": "margin: 8px 0; line-height: 1.9; padding-left: 6px;",

    "hr": "border: none; height: 1px; background: linear-gradient(to right, transparent, #d1d9e6, transparent); margin: 36px 0;",

    "a": "color: #4a6cf7; text-decoration: none; border-bottom: 1px solid rgba(74,108,247,0.3);",

    "table": "width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 14px;",
    "th": "background: #4a6cf7; color: #ffffff; padding: 12px 14px; text-align: left; font-weight: 600; font-size: 13px;",
    "td": "padding: 10px 14px; border-bottom: 1px solid #eef1f6; color: #4a5568;",

    "caption": "font-size: 12px; color: #a0aec0; text-align: center; margin-top: 10px;",
}


def load_styles(style_path=None):
    """加载样式配置，优先使用用户自定义样式"""
    styles = DEFAULT_STYLES.copy()

    if style_path is None:
        style_path = Path(__file__).parent.parent / "assets" / "style_config.json"

    if Path(style_path).exists():
        try:
            with open(style_path, "r", encoding="utf-8") as f:
                custom = json.load(f)
                styles.update(custom.get("styles", {}))
        except (json.JSONDecodeError, KeyError):
            pass

    return styles


# ============================================================
# Markdown 解析与转换
# ============================================================

def convert_markdown_to_wechat_html(markdown_text, styles=None):
    """
    将 Markdown 文本转换为微信公众号兼容的 HTML。

    Args:
        markdown_text: Markdown格式的文章内容
        styles: 样式字典（可选，默认使用内置样式）

    Returns:
        str: 微信兼容的HTML字符串
    """
    if styles is None:
        styles = load_styles()

    lines = markdown_text.split("\n")
    html_parts = []
    in_code_block = False
    code_block_content = []
    in_list = False
    list_type = None  # "ul" or "ol"
    list_items = []
    in_blockquote = False
    blockquote_lines = []
    in_table = False
    table_rows = []
    h1_seen = False  # 跟踪是否已遇到第一个H1标题

    def flush_list():
        nonlocal in_list, list_items, list_type
        if in_list and list_items:
            tag = list_type or "ul"
            if tag == "ul":
                items_html = "\n".join(
                    f'<li style="{styles["li"]}"><span style="color: #4a6cf7; margin-right: 8px;">●</span>{item}</li>'
                    for item in list_items
                )
            else:
                items_html = "\n".join(
                    f'<li style="{styles["li"]}">{item}</li>'
                    for item in list_items
                )
            html_parts.append(f'<{tag} style="{styles[tag]}">{items_html}</{tag}>')
            list_items = []
            in_list = False
            list_type = None

    def flush_blockquote():
        nonlocal in_blockquote, blockquote_lines
        if in_blockquote and blockquote_lines:
            content = "<br>".join(blockquote_lines)
            html_parts.append(f'<blockquote style="{styles["blockquote"]}">{content}</blockquote>')
            blockquote_lines = []
            in_blockquote = False

    def flush_table():
        nonlocal in_table, table_rows
        if in_table and table_rows:
            rows_html = []
            for i, row in enumerate(table_rows):
                cells = [c.strip() for c in row.split("|")[1:-1]]
                if i == 0:
                    cells_html = "".join(f'<th style="{styles["th"]}">{c}</th>' for c in cells)
                    rows_html.append(f"<tr>{cells_html}</tr>")
                elif all(set(c.strip()) <= {"-", ":"} for c in cells):
                    continue  # 跳过分隔行
                else:
                    cells_html = "".join(f'<td style="{styles["td"]}">{c}</td>' for c in cells)
                    rows_html.append(f"<tr>{cells_html}</tr>")
            html_parts.append(f'<table style="{styles["table"]}">{"".join(rows_html)}</table>')
            table_rows = []
            in_table = False

    def _escape_html(text):
        """转义HTML特殊字符，防止代码内容被浏览器解析"""
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def process_inline(text):
        """处理行内Markdown语法"""
        # 图片 ![alt](url)
        text = re.sub(
            r'!\[([^\]]*)\]\(([^)]+)\)',
            lambda m: f'<img src="{m.group(2)}" alt="{m.group(1)}" style="{styles["img"]}"/>',
            text
        )
        # 链接 [text](url)
        text = re.sub(
            r'\[([^\]]+)\]\(([^)]+)\)',
            lambda m: f'<a href="{m.group(2)}" style="{styles["a"]}">{m.group(1)}</a>',
            text
        )
        # 行内代码 `code`
        text = re.sub(
            r'`([^`]+)`',
            lambda m: f'<code style="{styles["code_inline"]}">{_escape_html(m.group(1))}</code>',
            text
        )
        # 粗体 **text**
        text = re.sub(
            r'\*\*([^*]+)\*\*',
            lambda m: f'<strong style="{styles["strong"]}">{m.group(1)}</strong>',
            text
        )
        # 斜体 *text*
        text = re.sub(
            r'\*([^*]+)\*',
            lambda m: f'<em style="{styles["em"]}">{m.group(1)}</em>',
            text
        )
        return text

    for line in lines:
        stripped = line.strip()

        # 代码块
        if stripped.startswith("```"):
            if in_code_block:
                code_html = "\n".join(code_block_content)
                html_parts.append(f'<pre style="{styles["code_block"]}">{code_html}</pre>')
                code_block_content = []
                in_code_block = False
            else:
                flush_list()
                flush_blockquote()
                flush_table()
                in_code_block = True
            continue

        if in_code_block:
            code_block_content.append(_escape_html(line))
            continue

        # 表格
        if "|" in stripped and stripped.startswith("|"):
            flush_list()
            flush_blockquote()
            if not in_table:
                in_table = True
            table_rows.append(stripped)
            continue
        else:
            flush_table()

        # 引用块
        if stripped.startswith(">"):
            flush_list()
            if not in_blockquote:
                in_blockquote = True
            content = stripped.lstrip(">").strip()
            blockquote_lines.append(process_inline(content))
            continue
        else:
            flush_blockquote()

        # 标题
        h_match = re.match(r'^(#{1,3})\s+(.+)$', stripped)
        if h_match:
            flush_list()
            level = len(h_match.group(1))
            text = process_inline(h_match.group(2))
            tag = f"h{level}"
            # 跳过第一个H1标题（微信已在文章顶部显示标题，正文中重复会冗余）
            if level == 1 and not h1_seen:
                h1_seen = True
                continue
            html_parts.append(f'<{tag} style="{styles[tag]}">{text}</{tag}>')
            continue

        # 分割线
        if re.match(r'^(-{3,}|\*{3,}|_{3,})$', stripped):
            flush_list()
            html_parts.append(f'<hr style="{styles["hr"]}"/>')
            continue

        # 无序列表
        ul_match = re.match(r'^[-*+]\s+(.+)$', stripped)
        if ul_match:
            if not in_list or list_type != "ul":
                flush_list()
                in_list = True
                list_type = "ul"
            list_items.append(process_inline(ul_match.group(1)))
            continue

        # 有序列表
        ol_match = re.match(r'^\d+\.\s+(.+)$', stripped)
        if ol_match:
            if not in_list or list_type != "ol":
                flush_list()
                in_list = True
                list_type = "ol"
            list_items.append(process_inline(ol_match.group(1)))
            continue

        flush_list()

        # 空行
        if not stripped:
            continue

        # 纯图片行
        img_match = re.match(r'^!\[([^\]]*)\]\(([^)]+)\)$', stripped)
        if img_match:
            alt = img_match.group(1)
            src = img_match.group(2)
            html_parts.append(f'<p style="text-align:center;margin:16px 0;"><img src="{src}" alt="{alt}" style="{styles["img"]}"/></p>')
            if alt:
                html_parts.append(f'<p style="{styles["caption"]}">{alt}</p>')
            continue

        # 普通段落
        text = process_inline(stripped)
        html_parts.append(f'<p style="{styles["p"]}">{text}</p>')

    # 清理未关闭的块
    flush_list()
    flush_blockquote()
    flush_table()

    body = "\n".join(html_parts)
    return f'<section style="{styles["body"]}">\n{body}\n</section>'


# ============================================================
# 命令行入口
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Markdown → 微信公众号 HTML 转换器")
    parser.add_argument("input", help="Markdown文件路径")
    parser.add_argument("-o", "--output", help="输出HTML文件路径（默认输出到stdout）")
    parser.add_argument("--style", help="自定义样式JSON文件路径")

    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        md_text = f.read()

    styles = load_styles(args.style) if args.style else load_styles()
    html = convert_markdown_to_wechat_html(md_text, styles)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"转换完成：{args.output}")
    else:
        print(html)
