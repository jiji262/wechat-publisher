"""
头条渲染的行内层:行内语法处理 + 图片块标记。

和 toutiao_render.py 的分工:这里只管"一行文本里的东西怎么变成 HTML 片段",
块级状态机(段落/列表/表格/代码块怎么组织)在 toutiao_render.py。

行内标记表和 front matter 剥离与微信侧共享(见 html_converter.INLINE_MARKS),
避免两边各自漂移导致同一篇文章发两个平台产出不一致。
"""

from __future__ import annotations

import html
import re
from typing import Dict, List, Tuple

from html_converter import INLINE_MARKS

# 图片和行内代码都先换成占位符再回填,理由见 process_inline 的 docstring
IMG_TOKEN = "\x00IMG{}\x00"
IMG_TOKEN_RE = re.compile(r"\x00IMG(\d+)\x00")
_CODE_TOKEN = "\x00CODE{}\x00"
_CODE_TOKEN_RE = re.compile(r"\x00CODE(\d+)\x00")
# 与 html_converter.py:378 同一条:只转义游离的 &,不碰已有实体
_BARE_AMP_RE = re.compile(r"&(?!(?:[a-zA-Z][a-zA-Z0-9]{1,31}|#[0-9]{1,7}|#x[0-9a-fA-F]{1,6});)")


class ToutiaoRenderError(RuntimeError):
    """渲染阶段的可预期错误(缺图、标题不合法等)。"""


def escape_amp(text: str) -> str:
    """把游离的 & 转成 &amp;,不破坏已经生成的实体。"""
    return _BARE_AMP_RE.sub("&amp;", text)


def render_image_block(
    url: str, alt: str, image_map: Dict[str, dict], *, skip_missing: bool = False
) -> str:
    """把一张图渲染成头条的 pgc-img 块。

    web_uri / img_width / img_height 缺一不可,否则头条返回 7115 图片uri非法。
    未上传成功的图默认抛错;skip_missing=True 时静默丢弃(对应 --allow-missing-images)。
    """
    info = image_map.get(url)
    if not info:
        if skip_missing:
            return ""
        raise ToutiaoRenderError(
            f"图片未上传到头条,无法引用:{url}。"
            "所有图片都必须先经 /spice/image 上传拿到 web_uri。"
        )
    missing = [k for k in ("image_url", "image_uri") if not info.get(k)]
    if missing:
        raise ToutiaoRenderError(
            f"头条返回的图片信息缺字段 {missing}(图片 {url}),无法拼出合法的 web_uri。"
        )
    src = html.escape(str(info["image_url"]), quote=True)
    web_uri = html.escape(str(info["image_uri"]), quote=True)
    mime = html.escape(str(info.get("image_mime_type") or "image/jpeg"), quote=True)
    width = int(info.get("image_width") or 0)
    height = int(info.get("image_height") or 0)
    # alt 取自已经转义过 < > 的文本,这里只补 & —— 再 html.escape 一次会变成 &amp;lt;
    return (
        '<div class="pgc-img">'
        f'<img src="{src}" class="" ic-uri="" image_type="{mime}" mime_type="" '
        f'web_uri="{web_uri}" img_width="{width}" img_height="{height}">'
        f'<p class="pgc-img-caption">{escape_amp(alt or "")}</p>'
        "</div>"
    )


def process_inline(text: str, images: List[Tuple[str, str]]) -> str:
    """处理一行文本的行内语法,返回 HTML 片段。

    图片和行内代码都先换成占位符:
    - 图片要提升成兄弟块(头条不支持段落内嵌图片),占位符由调用方拆分
    - 行内代码必须隔离,否则 `user_name` 会被斜体规则吃掉下划线、
      `a**b**c` 会被粗体规则拆开

    Args:
        text: 原始 markdown 文本行
        images: 输出参数,发现的图片按顺序追加 (url, alt)
    """
    text = text.replace("\x00", "")  # 防止用户输入伪造占位符
    text = text.replace("<", "&lt;").replace(">", "&gt;")

    def _img(m):
        images.append((m.group(2).strip(), m.group(1)))
        return IMG_TOKEN.format(len(images) - 1)

    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _img, text)
    # 链接降级成纯文本 —— 头条会吃掉 <a>
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: m.group(1), text)

    codes: List[str] = []

    def _code(m):
        codes.append(m.group(1))
        return _CODE_TOKEN.format(len(codes) - 1)

    text = re.sub(r"`([^`]+)`", _code, text)

    # 扩展标记(==高亮== 之类)在头条一律剥成纯文本,规则表与微信侧共享
    for pattern, _key in INLINE_MARKS:
        text = re.sub(pattern, lambda m: m.group(1), text)
    text = re.sub(r"\*\*([^*\n]+)\*\*", lambda m: f"<strong>{m.group(1)}</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", lambda m: m.group(1), text)
    # 刻意不处理 _斜体_:微信侧也没有这条规则,加上会把 user_name 吃成 username

    text = escape_amp(text)
    return _CODE_TOKEN_RE.sub(lambda m: f"<code>{codes[int(m.group(1))]}</code>", text)
