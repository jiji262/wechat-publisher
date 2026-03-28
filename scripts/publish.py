#!/usr/bin/env python3
"""
微信公众号文章发布 - 主流程脚本

整合所有模块，实现从Markdown文章到微信公众号草稿箱的一键发布：
1. 读取Markdown文章
2. 处理文章中的图片（下载+上传到微信）
3. 转换为微信兼容HTML（内联样式排版）
4. 准备封面图
5. 调用API创建草稿

用法：
    python publish.py --input article.md --author "作者名"
    python publish.py --input article.md --cover cover.jpg --title "自定义标题"
    python publish.py --html article.html --cover cover.jpg --title "标题"
"""

import sys
import re
import json
import argparse
from pathlib import Path

# 添加脚本目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from wechat_api import publish_article, upload_thumb_image, get_access_token, set_account, get_config
from html_converter import convert_markdown_to_wechat_html, load_styles
from image_handler import (
    process_article_images,
    download_image,
    extract_images_from_markdown,
)


def extract_title_from_markdown(md_content):
    """从Markdown中提取标题（第一个#标题）"""
    match = re.search(r'^#\s+(.+)$', md_content, re.MULTILINE)
    if match:
        return match.group(1).strip()
    # 回退：使用第一行非空文本
    for line in md_content.split("\n"):
        line = line.strip()
        if line and not line.startswith(">") and not line.startswith("!"):
            return line[:50]
    return "未命名文章"


def extract_digest_from_markdown(md_content):
    """从Markdown中提取摘要（blockquote或前120字）"""
    # 优先使用blockquote
    match = re.search(r'^>\s+(.+)$', md_content, re.MULTILINE)
    if match:
        return match.group(1).strip()[:120]
    # 回退：提取正文前120字
    text = re.sub(r'[#*>\[\]!`]', '', md_content)
    text = re.sub(r'\(http[^)]+\)', '', text)
    text = " ".join(text.split())
    return text[:120]


def remove_title_from_content(md_content):
    """从内容中移除标题行（避免在正文中重复显示标题）"""
    lines = md_content.split("\n")
    result = []
    title_removed = False
    for line in lines:
        if not title_removed and re.match(r'^#\s+', line.strip()):
            title_removed = True
            continue
        result.append(line)
    return "\n".join(result)


def publish_from_markdown(
    md_path,
    title=None,
    author="飞哥",
    digest=None,
    cover_path=None,
    source_url="",
    temp_dir="/tmp/wechat_images",
    style_path=None,
):
    """
    从Markdown文件发布文章到微信公众号草稿箱。

    完整流程：
    1. 读取Markdown
    2. 提取/确认标题和摘要
    3. 处理图片（下载+上传微信）
    4. 转换HTML排版
    5. 准备封面图
    6. 创建草稿

    Args:
        md_path: Markdown文件路径
        title: 标题（可选，默认从Markdown提取）
        author: 作者名
        digest: 摘要（可选，默认从Markdown提取）
        cover_path: 封面图路径（可选，默认使用文章第一张图）
        source_url: 原文链接
        temp_dir: 临时文件目录
        style_path: 自定义样式文件路径

    Returns:
        dict: 发布结果
    """
    print("=" * 60)
    print("微信公众号文章发布")
    print("=" * 60)

    # 1. 读取文章
    md_path = Path(md_path)
    if not md_path.exists():
        raise FileNotFoundError(f"文章文件不存在：{md_path}")

    with open(md_path, "r", encoding="utf-8") as f:
        md_content = f.read()

    print(f"读取文章：{md_path} ({len(md_content)} 字符)")

    # 2. 提取标题和摘要
    if not title:
        title = extract_title_from_markdown(md_content)
    if not digest:
        digest = extract_digest_from_markdown(md_content)

    print(f"标题：{title}")
    print(f"摘要：{digest[:50]}...")

    # 3. 验证API连接
    print("\n[步骤1] 验证API连接...")
    try:
        token = get_access_token()
        print(f"  API连接正常，token已获取")
    except Exception as e:
        print(f"  API连接失败：{e}")
        print("  请检查 .env 中的 WECHAT_APP_ID 和 WECHAT_APP_SECRET 配置")
        sys.exit(1)

    # 4. 处理图片
    print("\n[步骤2] 处理文章图片...")
    # 移除标题后处理（标题不包含在正文中）
    content_md = remove_title_from_content(md_content)
    processed_md, img_mapping, first_img = process_article_images(content_md, temp_dir)

    # 5. 转换HTML
    print("\n[步骤3] 转换HTML排版...")
    styles = load_styles(style_path) if style_path else load_styles()
    html_content = convert_markdown_to_wechat_html(processed_md, styles)
    print(f"  HTML生成完成 ({len(html_content)} 字符)")

    # 保存HTML到临时文件（方便调试）
    html_path = Path(temp_dir) / "article_output.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"  HTML已保存到：{html_path}")

    # 6. 准备封面图
    print("\n[步骤4] 准备封面图...")
    if cover_path and Path(cover_path).exists():
        print(f"  使用指定封面图：{cover_path}")
    elif first_img:
        cover_path = first_img
        print(f"  使用文章第一张图作为封面：{cover_path}")
    else:
        print("  警告：没有封面图！请提供 --cover 参数")
        print("  微信公众号要求每篇文章必须有封面图")
        sys.exit(1)

    # 7. 发布到草稿箱
    print("\n[步骤5] 发布到草稿箱...")
    result = publish_article(
        title=title,
        html_content=html_content,
        cover_image_path=cover_path,
        author=author,
        digest=digest,
        source_url=source_url,
    )

    print("\n" + "=" * 60)
    print("发布完成！")
    print(f"  草稿 media_id: {result['media_id']}")
    print("  请登录微信公众平台查看草稿箱")
    print("=" * 60)

    return result


def publish_from_html(
    html_path,
    title,
    cover_path,
    author="飞哥",
    digest="",
    source_url="",
):
    """
    从已排版的HTML文件发布文章。

    适用于已经完成排版的HTML内容，直接上传。

    Args:
        html_path: HTML文件路径
        title: 文章标题（必需）
        cover_path: 封面图路径（必需）
        author: 作者名
        digest: 摘要
        source_url: 原文链接

    Returns:
        dict: 发布结果
    """
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    result = publish_article(
        title=title,
        html_content=html_content,
        cover_image_path=cover_path,
        author=author,
        digest=digest,
        source_url=source_url,
    )
    return result


# ============================================================
# 命令行入口
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="微信公众号文章一键发布到草稿箱",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 从Markdown发布
  python publish.py --input article.md --author "张三"

  # 指定封面图和标题
  python publish.py --input article.md --cover cover.jpg --title "自定义标题"

  # 从HTML发布
  python publish.py --html article.html --cover cover.jpg --title "标题"
        """
    )

    parser.add_argument("--input", "-i", help="Markdown文件路径")
    parser.add_argument("--html", help="HTML文件路径（已排版）")
    parser.add_argument("--title", "-t", help="文章标题（默认从文章提取）")
    parser.add_argument("--cover", "-c", help="封面图路径")
    parser.add_argument("--author", "-a", default=None, help="作者名（默认从账号配置获取，兜底：飞哥）")
    parser.add_argument("--digest", "-d", help="文章摘要（默认从文章提取）")
    parser.add_argument("--source-url", default="", help="原文链接")
    parser.add_argument("--style", help="自定义样式JSON路径")
    parser.add_argument("--temp-dir", default="/tmp/wechat_images", help="临时文件目录")
    parser.add_argument("--account", help="指定公众号账号（对应 accounts.yaml 中的账号名）")

    args = parser.parse_args()

    # 设置全局账号
    if args.account:
        set_account(args.account)

    # 如果未指定author，从账号配置中获取，兜底为"飞哥"
    if args.author is None:
        try:
            config = get_config()
            args.author = config.get("author", "") or "飞哥"
        except SystemExit:
            args.author = "飞哥"

    if args.html:
        if not args.title or not args.cover:
            parser.error("使用 --html 模式时，必须提供 --title 和 --cover")
        result = publish_from_html(
            html_path=args.html,
            title=args.title,
            cover_path=args.cover,
            author=args.author,
            digest=args.digest or "",
            source_url=args.source_url,
        )
    elif args.input:
        result = publish_from_markdown(
            md_path=args.input,
            title=args.title,
            author=args.author,
            digest=args.digest,
            cover_path=args.cover,
            source_url=args.source_url,
            temp_dir=args.temp_dir,
            style_path=args.style,
        )
    else:
        parser.error("请提供 --input (Markdown) 或 --html 参数")

    # 输出JSON结果
    print("\n" + json.dumps(result, ensure_ascii=False, indent=2))
