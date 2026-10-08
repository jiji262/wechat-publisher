"""发布用标题/摘要的唯一提取口径(E5):publish、toutiao 发布与 ai_score 默认摘要都从这里取。

从 publish.py 原样下沉,行为不变:标题取第一个 `# ` 标题,没有则取正文第一行;
摘要取全文第一个引用块的第一行,没有引用块就取正文前 120 字(会带上标题文字)。
"""
from __future__ import annotations

import re

from html_converter import strip_front_matter

TITLE_FALLBACK_MAX = 50
DIGEST_MAX = 120

# 成对行内标记(标记符必须成对出现),共用一个替换函数
_INLINE_PAIR_MARKERS = [
    (r"\*\*", r"\*\*"),   # **粗体**
    (r"==",   r"=="),      # ==黄色高亮==
    (r"\+\+", r"\+\+"),   # ++蓝色高亮++
    (r"%%",   r"%%"),      # %%粉色高亮%%
    (r"&&",   r"&&"),      # &&绿色高亮&&
    (r"!!",   r"!!"),      # !!红色强调!!
    (r"@@",   r"@@"),      # @@蓝色强调@@
    (r"\^\^", r"\^\^"),   # ^^橙色强调^^
]


def strip_inline_markers(text: str) -> str:
    """剥离 Markdown 行内排版标记(加粗/斜体/自定义标色),保留文字内容本身。

    处理成对标记(比如 `**foo**` → `foo`),同时清除末尾没配对的孤立符号,
    避免摘要里冒出 `**` 之类的裸标记。
    """
    for open_pat, close_pat in _INLINE_PAIR_MARKERS:
        text = re.sub(rf"{open_pat}([^\n]+?){close_pat}", r"\1", text)
    text = re.sub(r"\*([^*\n]+)\*", r"\1", text)          # 斜体(单星号)
    text = re.sub(r"\*\*|==|\+\+|%%|&&|!!|@@|\^\^", "", text)   # 剩余孤立标记
    return text.replace("`", "")


def extract_title_from_markdown(md_content: str) -> str:
    """第一个 `# ` 标题;没有时跳过 YAML front matter,取第一行非空正文(排除引用/列表/图片/分隔线)。"""
    match = re.search(r'^#\s+(.+)$', md_content, re.MULTILINE)
    if match:
        return strip_inline_markers(match.group(1).strip())
    for line in strip_front_matter(md_content).split("\n"):
        line = line.strip()
        if not line or line.startswith((">", "!", "-", "*", "+")) or set(line) <= {"-", "=", " "}:
            continue
        return strip_inline_markers(line)[:TITLE_FALLBACK_MAX]
    return "未命名文章"


def extract_digest_from_markdown(md_content: str) -> str:
    """全文第一个引用块的第一行;没有引用块时取正文前 120 字。先清行内标记再截断。"""
    match = re.search(r'^>\s+(.+)$', md_content, re.MULTILINE)
    if match:
        return strip_inline_markers(match.group(1).strip())[:DIGEST_MAX]
    text = strip_front_matter(md_content)
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)          # 标题符号
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)           # 引用符号
    text = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', text)                # 图片
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)            # 链接留文字
    text = re.sub(r'[\[\]]', '', strip_inline_markers(text))        # 剩余方括号
    return " ".join(text.split())[:DIGEST_MAX]
