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
import tempfile
from pathlib import Path
from typing import Optional

# 添加脚本目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from wechat_api import (
    publish_article,
    upload_thumb_image,
    get_access_token,
    set_account,
    get_config,
    ConfigError,
)
from html_converter import convert_markdown_to_wechat_html, load_styles, load_theme
from image_handler import process_article_images


# ============================================================
# Markdown 文本处理工具
# ============================================================

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


def _strip_inline_markers(text: str) -> str:
    """剥离 Markdown 行内排版标记(加粗/斜体/自定义标色),保留文字内容本身。

    处理成对标记(比如 `**foo**` → `foo`),同时清除末尾没配对的孤立符号,
    避免摘要里冒出 `**` 之类的裸标记。
    """
    # 先处理成对标记
    for open_pat, close_pat in _INLINE_PAIR_MARKERS:
        text = re.sub(rf"{open_pat}([^\n]+?){close_pat}", r"\1", text)
    # 斜体(单星号)
    text = re.sub(r"\*([^*\n]+)\*", r"\1", text)
    # 剩余的孤立标记符号一律剥掉,避免摘要里冒出 `**` 之类
    text = re.sub(r"\*\*|==|\+\+|%%|&&|!!|@@|\^\^", "", text)
    # 反引号
    text = text.replace("`", "")
    return text


def _strip_front_matter(md_content: str) -> str:
    """如果文章以 YAML front matter(--- ... ---)开头,去掉整段 front matter。"""
    if md_content.lstrip().startswith("---"):
        # 找到起始 `---` 后的第二个 `---` 行
        m = re.match(r"^\s*---\s*\n(.*?)\n---\s*\n", md_content, flags=re.DOTALL)
        if m:
            return md_content[m.end():]
    return md_content


def extract_title_from_markdown(md_content):
    """从Markdown中提取标题（第一个#标题）。

    回退顺序:
      1. 第一个 `# ` 标题
      2. 跳过 YAML front matter 后的第一行非空文本(排除引用/列表/图片等)
    """
    match = re.search(r'^#\s+(.+)$', md_content, re.MULTILINE)
    if match:
        return _strip_inline_markers(match.group(1).strip())

    # 回退前先剥掉 YAML front matter,避免把 `---` 或 `title: xxx` 当成标题
    body = _strip_front_matter(md_content)
    for line in body.split("\n"):
        line = line.strip()
        if not line:
            continue
        # 排除引用、图片、分隔线、列表项
        if line.startswith((">", "!", "-", "*", "+")):
            continue
        if set(line) <= {"-", "=", " "}:  # 纯分隔线
            continue
        return _strip_inline_markers(line)[:50]
    return "未命名文章"


def extract_digest_from_markdown(md_content):
    """从Markdown中提取摘要（blockquote或前120字）。

    清理所有行内排版标记(`**foo**`, `==foo==` 等)后再截断,避免摘要里
    残留 `**`、`==` 这类裸标记符号。
    """
    # 优先使用 blockquote
    match = re.search(r'^>\s+(.+)$', md_content, re.MULTILINE)
    if match:
        cleaned = _strip_inline_markers(match.group(1).strip())
        return cleaned[:120]

    # 回退：提取正文前120字
    text = _strip_front_matter(md_content)
    # 去掉标题符号、引用符号、图片链接
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = _strip_inline_markers(text)
    # 剥掉剩余的方括号
    text = re.sub(r'[\[\]]', '', text)
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


# ============================================================
# 默认临时目录
# ============================================================

def _default_temp_dir() -> str:
    """为本次运行创建一个独立的临时目录,避免并发运行互相覆盖文件。"""
    return tempfile.mkdtemp(prefix="wechat_images_")


# ============================================================
# 发布主流程
# ============================================================

def publish_from_markdown(
    md_path,
    title=None,
    author=None,
    digest=None,
    cover_path=None,
    source_url="",
    temp_dir=None,
    style_path=None,
    theme=None,
    sync_platforms=None,
    account_name: Optional[str] = None,
    ai_score_threshold: float = 45.0,
    skip_ai_score: bool = False,
    debug: bool = False,
):
    """
    从Markdown文件发布文章到微信公众号草稿箱。

    完整流程：
    1. 读取Markdown
    2. AI 味检测(gate,可用 skip_ai_score 关闭)
    3. 提取/确认标题和摘要
    4. 处理图片（下载+上传微信）
    5. 转换HTML排版
    6. 准备封面图
    7. 创建草稿

    Args:
        md_path: Markdown文件路径
        title: 标题（可选，默认从Markdown提取）
        author: 作者名(默认从账号配置读取,再兜底到 "飞哥")
        digest: 摘要（可选，默认从Markdown提取）
        cover_path: 封面图路径（可选，默认使用文章第一张图）
        source_url: 原文链接
        temp_dir: 临时文件目录(默认为每次运行独立生成)
        style_path: 自定义样式文件路径
        theme: 排版主题名(默认从账号配置读取)
        sync_platforms: 同步到其他平台的列表
        account_name: 若指定,则在函数内部调用 set_account() 切换账号
        ai_score_threshold: AI 味检测阈值,总分 >= 阈值视为不通过(默认 45)
        skip_ai_score: True 时跳过 AI 味检测(默认 False)
        debug: True 时把生成的 HTML 保存到 temp_dir 下方便调试

    Returns:
        dict: 发布结果
    """
    # 如果库调用方指定了账号,立即切换
    if account_name:
        set_account(account_name)

    if temp_dir is None:
        temp_dir = _default_temp_dir()

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

    # 2. AI 味检测(在图片上传前,失败时避免浪费素材库配额)
    if not skip_ai_score:
        # 延迟导入,避免其他 agent 正在写 ai_score.py 时触发 import 错误
        try:
            from ai_score import check_ai_score
        except ImportError as exc:
            print(f"\n[警告] 无法加载 ai_score 模块({exc}),跳过 AI 味检测。")
        else:
            print("\n[预检] AI 味检测...")
            passed, report = check_ai_score(md_content, ai_score_threshold)
            total = report.get("total_score")
            print(f"  总分: {total} / 100  (阈值 {ai_score_threshold})")
            if not passed:
                print(f"  结果: 未通过 AI 味检测(总分 {total} >= 阈值 {ai_score_threshold})")
                dims = report.get("dimensions", {}) or {}
                if dims:
                    print("  失分维度:")
                    for name, info in dims.items():
                        score = info.get("score") if isinstance(info, dict) else info
                        print(f"    · {name}: {score}")
                hit_phrases = report.get("hit_phrases") or []
                if hit_phrases:
                    print("  命中 AI 套话:")
                    for s in hit_phrases[:10]:
                        print(f"    · {s}")
                hit_vocab = report.get("hit_vocab") or []
                if hit_vocab:
                    print("  命中 AI 高频词: " + ", ".join(str(v) for v in hit_vocab[:15]))
                print(
                    "\n  发布已阻止。请回到 SKILL.md 阶段 3.5『人味化改写』按清单逐条打磨,\n"
                    "  或使用 --skip-ai-score 跳过此检测(不推荐)。"
                )
                raise SystemExit(1)
            print("  结果: 通过")

    # 3. 提取标题和摘要
    if not title:
        title = extract_title_from_markdown(md_content)
    if not digest:
        digest = extract_digest_from_markdown(md_content)

    print(f"标题：{title}")
    print(f"摘要：{digest[:50]}...")

    # 4. 验证API连接
    print("\n[步骤1] 验证API连接...")
    try:
        token = get_access_token()
        print(f"  API连接正常，token已获取")
    except Exception as e:
        print(f"  API连接失败：{e}")
        print("  请检查 accounts.yaml 中的 app_id / app_secret 配置")
        sys.exit(1)

    # 5. 处理图片
    print("\n[步骤2] 处理文章图片...")
    # 移除标题后处理（标题不包含在正文中）
    content_md = remove_title_from_content(md_content)
    processed_md, img_mapping, first_img = process_article_images(content_md, temp_dir)

    # 6. 转换HTML
    print("\n[步骤3] 转换HTML排版...")
    styles, highlights, divider_text = load_theme(theme_name=theme, style_path=style_path)
    print(f"  主题: {theme or '(默认)'}")
    html_content = convert_markdown_to_wechat_html(
        processed_md, styles, highlights, divider_text
    )
    print(f"  HTML生成完成 ({len(html_content)} 字符)")

    # 仅在 debug 模式下持久化中间 HTML(否则会堆满临时目录)
    if debug:
        html_path = Path(temp_dir) / "article_output.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"  [debug] HTML已保存到：{html_path}")

    # 7. 准备封面图
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

    # 8. 如未提供 author,从账号配置兜底读取
    if author is None:
        try:
            cfg = get_config(account_name)
            author = cfg.get("author", "") or "飞哥"
        except ConfigError:
            author = "飞哥"

    # 9. 发布到草稿箱
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

    # 可选阶段：同步到其他内容平台(opt-in,失败不影响微信发布结果)
    if sync_platforms:
        print(f"\n[可选] 同步到其他平台: {', '.join(sync_platforms)}")
        try:
            from multi_publish import run as sync_run
            sync_result = sync_run(
                md_path=md_path,
                platforms=sync_platforms,
                title=title,
                cover_path=cover_path,
                strict=False,
            )
            result["sync"] = {
                "platforms": sync_platforms,
                "success": sync_result["success"],
                "returncode": sync_result["returncode"],
            }
        except Exception as e:
            print(f"  同步环节异常(不影响微信发布): {e}")
            result["sync"] = {"platforms": sync_platforms, "success": False, "error": str(e)}

    return result


def publish_from_html(
    html_path,
    title,
    cover_path,
    author=None,
    digest="",
    source_url="",
    account_name: Optional[str] = None,
):
    """
    从已排版的HTML文件发布文章。

    适用于已经完成排版的HTML内容，直接上传。HTML 已经是微信专用排版,
    因此不做 AI 味检测,也不支持多平台同步。

    Args:
        html_path: HTML文件路径
        title: 文章标题（必需）
        cover_path: 封面图路径（必需）
        author: 作者名(默认从账号配置读取,再兜底到 "飞哥")
        digest: 摘要
        source_url: 原文链接
        account_name: 若指定,则在函数内部调用 set_account() 切换账号

    Returns:
        dict: 发布结果
    """
    if account_name:
        set_account(account_name)

    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # 如未提供 author,从账号配置兜底读取
    if author is None:
        try:
            cfg = get_config(account_name)
            author = cfg.get("author", "") or "飞哥"
        except ConfigError:
            author = "飞哥"

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

def _build_parser() -> argparse.ArgumentParser:
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

  # 跳过 AI 味检测或放宽阈值
  python publish.py --input article.md --cover cover.jpg --skip-ai-score
  python publish.py --input article.md --cover cover.jpg --ai-score-threshold 55
        """
    )

    parser.add_argument("--input", "-i", help="Markdown文件路径")
    parser.add_argument("--html", help="HTML文件路径（已排版）")
    parser.add_argument("--title", "-t", help="文章标题（默认从文章提取）")
    parser.add_argument("--cover", "-c", help="封面图路径")
    parser.add_argument("--author", "-a", default=None,
                        help="作者名（默认从账号配置获取，兜底：飞哥）")
    parser.add_argument("--digest", "-d", help="文章摘要（默认从文章提取）")
    parser.add_argument("--source-url", default="", help="原文链接")
    parser.add_argument("--style", help="自定义样式JSON路径")
    parser.add_argument("--theme", help="排版主题名(对应 assets/themes/<name>.json,默认从账号配置读取)")
    parser.add_argument(
        "--temp-dir",
        default=None,
        help="临时文件目录(默认每次运行独立生成,避免并发冲突)",
    )
    parser.add_argument("--account", help="指定公众号账号（对应 accounts.yaml 中的账号名）")
    parser.add_argument(
        "--sync",
        help="可选:发到微信后同步到其他平台,逗号分隔(如 zhihu,juejin,csdn)。"
             "覆盖 --sync-from-config。需先装 @wechatsync/cli 并配置 WECHATSYNC_MCP_TOKEN",
    )
    parser.add_argument(
        "--sync-from-config", action="store_true",
        help="可选:同步到账号配置里 sync_platforms 字段指定的平台",
    )
    parser.add_argument(
        "--ai-score-threshold",
        type=float,
        default=45.0,
        help="AI 味检测阈值(默认 45.0)。总分 >= 阈值则阻止发布",
    )
    parser.add_argument(
        "--skip-ai-score",
        action="store_true",
        help="跳过 AI 味检测(不推荐,仅在已经人工改写过时使用)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="调试模式:把生成的 HTML 保存到 temp_dir 方便排查",
    )
    return parser


def _resolve_config(args):
    """按命令行参数回读账号配置,填充 author/theme/sync_platforms。

    返回 config_sync_platforms(配置里声明的同步平台列表,可能为 None)。
    约定:
      - `--sync-from-config` 显式要求读配置,任何 ConfigError 都应 exit 1。
      - 其他情况(只是兜底 author/theme)下 ConfigError 会被静默吞掉,
        保留原有"没有 accounts.yaml 也能用 --author 硬写"的行为。
    """
    config_sync_platforms = None
    needs_config = (
        args.author is None or args.theme is None or args.sync_from_config
    )
    if not needs_config:
        return config_sync_platforms

    try:
        config = get_config()
    except ConfigError as e:
        if args.sync_from_config:
            print(f"[配置错误] {e}", file=sys.stderr)
            print("--sync-from-config 需要有效的 accounts.yaml 配置。", file=sys.stderr)
            sys.exit(1)
        if args.author is None:
            args.author = "飞哥"
        return config_sync_platforms

    if args.author is None:
        args.author = config.get("author", "") or "飞哥"
    if args.theme is None:
        args.theme = config.get("theme", "") or None
    config_sync_platforms = config.get("sync_platforms") or None
    return config_sync_platforms


def _resolve_sync_platforms(args, config_sync_platforms):
    """解析最终要同步的平台列表: --sync 显式指定 > 配置里的 sync_platforms。"""
    if args.sync:
        return [p.strip() for p in args.sync.split(",") if p.strip()]
    if args.sync_from_config and config_sync_platforms:
        if isinstance(config_sync_platforms, str):
            return [p.strip() for p in config_sync_platforms.split(",") if p.strip()]
        return [str(p).strip() for p in config_sync_platforms if str(p).strip()]
    return None


def main():
    parser = _build_parser()
    args = parser.parse_args()

    # 设置全局账号
    if args.account:
        set_account(args.account)

    # 从账号配置回读 author / theme / sync_platforms
    config_sync_platforms = _resolve_config(args)

    # 解析最终要同步的平台列表
    sync_platforms = _resolve_sync_platforms(args, config_sync_platforms)

    if args.html:
        if not args.title or not args.cover:
            parser.error("使用 --html 模式时，必须提供 --title 和 --cover")
        if args.sync or args.sync_from_config:
            parser.error(
                "--html 模式不支持多平台同步(HTML 已是微信专用排版)。"
                "如需同步请改用 --input <markdown>。"
            )
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
            theme=args.theme,
            sync_platforms=sync_platforms,
            ai_score_threshold=args.ai_score_threshold,
            skip_ai_score=args.skip_ai_score,
            debug=args.debug,
        )
    else:
        parser.error("请提供 --input (Markdown) 或 --html 参数")

    # 输出JSON结果
    print("\n" + json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
