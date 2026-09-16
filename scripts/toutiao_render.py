"""
markdown → 头条正文 HTML。

和 html_converter.py 的关系:**产物**并列,互不复用;**输入侧的解析规则**共享。
产物不复用是因为几乎零重叠 —— 微信那份是全内联样式的精致排版,而头条会把
所有 style 属性、<a>、<section> 全部清洗掉(见 references/toutiao-publish-research.md 4.3)。
但 front matter 剥离和行内标记表必须共享,否则两边会各自漂移,
同一篇文章发两个平台产出不一致。

头条的硬约束:
- 正文里不能出现外链图片,必须先传到头条 CDN 再用 web_uri 引用,否则报 7115
- <a> 会被吃掉,链接一律降级成纯文本
- 所有 style 属性会被丢弃,所以这里一个都不生成
- 标题只有一级,## 和 ### 都会被归一成同级
"""

from __future__ import annotations

import html
import re
from typing import Dict, List, Optional, Tuple

# 与微信侧共享 front matter 剥离,避免两边解析规则漂移
from html_converter import strip_front_matter
from toutiao_inline import (
    IMG_TOKEN_RE,
    ToutiaoRenderError,
    process_inline,
    render_image_block,
)

TITLE_MIN_LEN = 2
TITLE_MAX_LEN = 30

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")

__all__ = ["ToutiaoRenderError", "render_toutiao_html", "validate_title"]


def validate_title(title: str) -> str:
    """头条标题必须 2~30 字。超长不静默截断,直接报错。"""
    text = (title or "").strip()
    if len(text) < TITLE_MIN_LEN:
        raise ToutiaoRenderError(
            f"头条标题至少 {TITLE_MIN_LEN} 个字,当前 {len(text)} 个:{text!r}"
        )
    if len(text) > TITLE_MAX_LEN:
        raise ToutiaoRenderError(
            f"头条标题最多 {TITLE_MAX_LEN} 个字,当前 {len(text)} 个。"
            f"请手动改短后重试:{text!r}"
        )
    return text



class _Renderer:
    """逐行状态机。拆成小方法是为了每个方法都能单独读懂。"""

    def __init__(self, image_map: Dict[str, dict], skip_missing: bool = False):
        self.image_map = image_map
        self.skip_missing = skip_missing
        self.out: List[str] = []
        self.pending: List[str] = []   # 从 li/td/引用里提出来、等容器收尾后再吐的图片块
        self.list_items: List[str] = []
        self.list_tag = ""
        self.table_rows: List[str] = []
        self.code_lines: Optional[List[str]] = None

    # -- 块收尾 -------------------------------------------------------
    def _flush_pending(self) -> None:
        self.out.extend(self.pending)
        self.pending = []

    def flush_list(self) -> None:
        if not self.list_items:
            return
        items = "".join(f"<li>{it}</li>" for it in self.list_items)
        self.out.append(f"<{self.list_tag}>{items}</{self.list_tag}>")
        self.list_items, self.list_tag = [], ""
        self._flush_pending()

    def flush_table(self) -> None:
        if not self.table_rows:
            return
        self.out.append(f"<table>{''.join(self.table_rows)}</table>")
        self.table_rows = []
        self._flush_pending()

    def flush_blocks(self) -> None:
        self.flush_list()
        self.flush_table()

    # -- 行内文本 + 图片处理 ------------------------------------------
    def _hoist_images(self, rendered: str, images: List[Tuple[str, str]]) -> str:
        """把行内图片摘出来挂到 pending —— 列表项/单元格/引用里不能嵌图片块。

        注意仍然走 render_image_block,所以"图片必须先上传"的守卫照常生效,
        不会因为图片长在 li 里就被静默放行。
        """
        def _sub(m):
            url, alt = images[int(m.group(1))]
            block = render_image_block(url, alt, self.image_map, skip_missing=self.skip_missing)
            if block:
                self.pending.append(block)
            return ""

        return IMG_TOKEN_RE.sub(_sub, rendered)

    def emit_text(self, raw: str, wrapper: str) -> None:
        """渲染一行文本;其中的图片按原顺序提升为独立的 pgc-img 兄弟块。"""
        images: List[Tuple[str, str]] = []
        rendered = process_inline(raw, images)
        cursor, parts = 0, []
        for m in IMG_TOKEN_RE.finditer(rendered):
            parts.append(("text", rendered[cursor:m.start()]))
            parts.append(("img", int(m.group(1))))
            cursor = m.end()
        parts.append(("text", rendered[cursor:]))
        for kind, val in parts:
            if kind == "img":
                url, alt = images[val]
                block = render_image_block(url, alt, self.image_map, skip_missing=self.skip_missing)
                if block:
                    self.out.append(block)
            elif val.strip():
                self.out.append(f"<{wrapper}>{val.strip()}</{wrapper}>")

    def _inline_no_images(self, raw: str) -> str:
        images: List[Tuple[str, str]] = []
        return self._hoist_images(process_inline(raw, images), images).strip()

    # -- 逐行分派 -----------------------------------------------------
    def _handle_code_fence(self, line: str, stripped: str) -> bool:
        """处理代码块状态。返回 True 表示这一行已被消费。"""
        if self.code_lines is not None:
            if stripped.startswith("```"):
                self._emit_code()
            else:
                self.code_lines.append(line)
            return True
        if stripped.startswith("```"):
            self.flush_blocks()
            self.code_lines = []
            return True
        return False

    def _emit_code(self) -> None:
        body = html.escape("\n".join(self.code_lines or []))
        self.out.append(f"<pre><code>{body}</code></pre>")
        self.code_lines = None

    def handle(self, line: str) -> None:
        stripped = line.strip()
        if self._handle_code_fence(line, stripped):
            return

        if stripped.startswith("|") and stripped.endswith("|"):
            self.flush_list()
            self._table_row(stripped)
            return
        self.flush_table()

        if not stripped:
            self.flush_list()
            return
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            self.flush_list()
            self.out.append("<hr>")
            return
        heading = _HEADING_RE.match(stripped)
        if heading:
            self.flush_list()
            self._heading(heading)
            return
        if stripped.startswith(">"):
            self.flush_list()
            self._blockquote(stripped)
            return
        if re.match(r"^[-*+]\s+", stripped):
            self._list_item(re.sub(r"^[-*+]\s+", "", stripped), "ul")
            return
        if re.match(r"^\d+\.\s+", stripped):
            self._list_item(re.sub(r"^\d+\.\s+", "", stripped), "ol")
            return

        self.flush_list()
        self.emit_text(stripped, "p")

    # -- 各块类型 -----------------------------------------------------
    def _heading(self, match: re.Match) -> None:
        level = len(match.group(1))
        if level <= 1:
            return  # H1 是文章标题,走 title 字段,不进正文
        self.emit_text(match.group(2).strip(), "h2" if level == 2 else "h3")

    def _blockquote(self, stripped: str) -> None:
        text = self._inline_no_images(stripped.lstrip(">").strip())
        if text:
            self.out.append(f"<blockquote><p>{text}</p></blockquote>")
        self._flush_pending()

    def _list_item(self, text: str, tag: str) -> None:
        if self.list_tag and self.list_tag != tag:
            self.flush_list()
        self.list_tag = tag
        self.list_items.append(self._inline_no_images(text))

    def _table_row(self, stripped: str) -> None:
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if all(set(c) <= {"-", ":"} and c for c in cells):
            return  # 分隔行
        tag = "th" if not self.table_rows else "td"
        rendered = [self._inline_no_images(c) for c in cells]
        cells_html = "".join(f"<{tag}>{c}</{tag}>" for c in rendered)
        self.table_rows.append(f"<tr>{cells_html}</tr>")

    def finish(self) -> str:
        if self.code_lines is not None:  # 未闭合的代码块
            self._emit_code()
        self.flush_blocks()
        self._flush_pending()
        return "".join(self.out)


def render_toutiao_html(
    md_content: str,
    image_map: Optional[Dict[str, dict]] = None,
    skip_missing: bool = False,
) -> str:
    """把 markdown 渲染成头条可直接入库的正文 HTML。

    Args:
        md_content: 文章正文 markdown(标题行可留可不留,H1 会被丢弃)
        image_map: 原始图片 url → /spice/image 返回的 data dict。
                   正文引用到但不在此映射里的图片会抛 ToutiaoRenderError。
        skip_missing: True 时把未上传成功的图静默丢弃,而不是抛错
                      (对应 CLI 的 --allow-missing-images)。

    Returns:
        不含任何 style 属性的 HTML 字符串。
    """
    renderer = _Renderer(image_map or {}, skip_missing=skip_missing)
    for line in strip_front_matter(md_content).split("\n"):
        renderer.handle(line)
    return renderer.finish()
