#!/usr/bin/env python3
"""
发布文章到今日头条(头条号)草稿箱。

管线:
    article.md
      → AI 味门禁(与微信侧共用 publish.run_ai_score_gate)
      → 标题提取与校验(头条限 2~30 字)
      → 图片解析到本地(与微信侧共用 image_handler.resolve_images_to_local)
      → [bun toutiao_cdp.ts upload]   把图片传到头条 CDN
      → toutiao_render 渲染成头条裸 HTML
      → [bun toutiao_cdp.ts publish]  写入草稿箱(save=0)

浏览器侧为什么必须存在,见 toutiao_cdp.ts 的文件头注释。

用法:
    python3 toutiao_publish.py --check
    python3 toutiao_publish.py --input article.md
    python3 toutiao_publish.py --input article.md --cover cover.jpg --title "自定义标题"
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))

from config import load_env
from image_handler import resolve_images_to_local
from toutiao_render import ToutiaoRenderError, render_toutiao_html, validate_title

PLATFORM = "toutiao"
CDP_SCRIPT = Path(__file__).parent / "toutiao_cdp.ts"
DEFAULT_TIMEOUT = 600


class ToutiaoPublishError(RuntimeError):
    """发布链路的可预期错误。"""


# ------------------------------------------------------------------
# 浏览器侧调用(唯一的 subprocess 边界,测试从这里打桩)
# ------------------------------------------------------------------

def _run_cdp(command: str, payload: Optional[dict] = None,
             timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """调用 bun toutiao_cdp.ts <command>,JSON 走 stdin/stdout。"""
    if not CDP_SCRIPT.exists():
        raise ToutiaoPublishError(f"缺少浏览器侧脚本: {CDP_SCRIPT}")
    try:
        proc = subprocess.run(
            ["bun", str(CDP_SCRIPT), command],
            input=json.dumps(payload or {}, ensure_ascii=False),
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        raise ToutiaoPublishError(
            "找不到 bun。请先安装:curl -fsSL https://bun.sh/install | bash"
        ) from None
    except subprocess.TimeoutExpired:
        raise ToutiaoPublishError(
            f"浏览器侧操作超时({timeout}s)。若是首次使用,请在弹出的 Chrome 窗口里及时扫码登录。"
        ) from None

    if proc.stderr:
        print(proc.stderr.rstrip(), file=sys.stderr)

    stdout = (proc.stdout or "").strip()
    if not stdout:
        raise ToutiaoPublishError(f"浏览器侧没有输出(exit={proc.returncode})")
    try:
        result = json.loads(stdout.splitlines()[-1])
    except json.JSONDecodeError as exc:
        raise ToutiaoPublishError(f"浏览器侧输出不是合法 JSON: {stdout[:200]}") from exc

    if not result.get("ok"):
        raise ToutiaoPublishError(result.get("error") or "浏览器侧执行失败")
    return result


def check() -> Dict[str, Any]:
    """检查头条号登录态。未登录会拉起 Chrome 让用户扫码。"""
    load_env()
    return _run_cdp("check", {}, timeout=DEFAULT_TIMEOUT)


# ------------------------------------------------------------------
# 主流程
# ------------------------------------------------------------------

def _load_and_gate(md_path, ai_score_threshold, skip_ai_score, *,
                   title=None, account=None) -> tuple:
    """读文章 → 清零宽字符 → 定标题 → 过 AI 味门禁。返回 (Path, 正文, 最终标题)。

    门禁就是 publish.run_ai_score_gate,带文章路径(核对 brief.md / humanize_log.md),
    标题先定下来再查,保证查的就是要发的那个。单独运行本脚本也走这一道。
    """
    md_file = Path(md_path)
    if not md_file.exists():
        raise ToutiaoPublishError(f"文章不存在: {md_file}")
    from publish import run_ai_score_gate, strip_zero_width_chars
    md_content = md_file.read_text(encoding="utf-8")
    print(f"读取文章：{md_file} ({len(md_content)} 字符)")
    md_content = strip_zero_width_chars(md_content)
    resolved_title = _resolve_title(md_content, title)
    if not skip_ai_score:
        run_ai_score_gate(md_content, ai_score_threshold, md_path=md_file,
                          title=resolved_title, account=account)
    return md_file, md_content, resolved_title


def _resolve_title(md_content: str, title: Optional[str]) -> str:
    """最终标题:手动传入优先,否则按 publish 同一口径提取;都先清零宽字符(E4)再校验长度。"""
    from publish import extract_title_from_markdown, strip_zero_width_chars
    return validate_title(strip_zero_width_chars(title or extract_title_from_markdown(md_content)) or "")


def _collect_images(content_md: str, temp_dir: str, base_dir: Path,
                    *, allow_missing: bool = False) -> List[tuple]:
    """解析图片到本地路径。缺图默认中止,避免产出缺图草稿。

    同一个 URL 在文中出现多次只保留一份 —— 否则会重复上传,白白多传几张图。
    """
    resolved = resolve_images_to_local(content_md, temp_dir, base_dir=base_dir)
    missing = [url for url, local in resolved if not local]
    if missing and not allow_missing:
        raise ToutiaoPublishError(
            f"{len(missing)} 张图片无法解析到本地文件:\n"
            + "\n".join(f"  · {u}" for u in missing)
            + "\n相对路径按 article.md 所在目录解析。"
            "确认路径无误后重试,或加 --allow-missing-images 接受缺图草稿。"
        )
    deduped: Dict[str, str] = {}
    for url, local in resolved:
        if local and url not in deduped:
            deduped[url] = local
    return list(deduped.items())


def _upload_assets(images: List[tuple], cover_path: Optional[str]) -> Dict[str, Any]:
    """把正文图和封面传到头条 CDN,拿回带 web_uri 的图片信息。"""
    return _run_cdp("upload", {
        "images": [{"key": url, "path": local} for url, local in images],
        "cover": str(cover_path) if cover_path else None,
    })


def _create_draft(title: str, content_html: str,
                  cover_info: Optional[dict]) -> Dict[str, Any]:
    """写入头条草稿箱(save=0)。"""
    return _run_cdp("publish", {
        "title": title, "content": content_html, "cover": cover_info,
    })


def _publish_into(
    result: Dict[str, Any],
    md_path,
    *,
    title: Optional[str] = None,
    cover_path: Optional[str] = None,
    temp_dir: Optional[str] = None,
    ai_score_threshold: Optional[float] = None,
    skip_ai_score: bool = False,
    allow_missing_images: bool = False,
    account: Optional[str] = None,
) -> None:
    """实际干活的部分,把进度写进 result。异常一律交给 run() 翻译。

    边做边写 result(而不是最后一次性返回),是为了失败时仍能报出已经确定的
    title / images —— 光一句"失败了"对排查没用。
    """
    load_env()  # 把 wechat-publisher.yaml 的 integrations.toutiao 注入环境变量
    md_file, md_content, resolved_title = _load_and_gate(md_path, ai_score_threshold, skip_ai_score,
                                                         title=title, account=account)
    result["title"] = resolved_title
    print(f"\n[头条] 标题：{resolved_title}")

    from publish import remove_title_from_content
    content_md = remove_title_from_content(md_content)

    if temp_dir is None:
        temp_dir = tempfile.mkdtemp(prefix="toutiao_images_")
    print("\n[头条 1/3] 解析图片...")
    images = _collect_images(content_md, temp_dir, md_file.parent,
                             allow_missing=allow_missing_images)
    if not cover_path and images:
        cover_path = images[0][1]
        print(f"  用文章第一张图作封面：{cover_path}")

    print("\n[头条 2/3] 上传图片到头条 CDN...")
    upload = _upload_assets(images, cover_path)
    image_map = upload.get("images") or {}
    cover_info = upload.get("cover")
    result["images"] = len(image_map)
    result["cover"] = bool(cover_info)

    html = render_toutiao_html(content_md, image_map=image_map, skip_missing=allow_missing_images)
    print(f"  正文 HTML 生成完成 ({len(html)} 字符)")

    print("\n[头条 3/3] 写入草稿箱...")
    published = _create_draft(resolved_title, html, cover_info)
    result.update(
        success=True,
        pgc_id=published.get("pgc_id"),
        draft_url=published.get("draft_url"),
    )
    print(f"\n  头条草稿已保存：{result['draft_url']}")


def run(
    md_path,
    *,
    title: Optional[str] = None,
    cover_path: Optional[str] = None,
    temp_dir: Optional[str] = None,
    ai_score_threshold: Optional[float] = None,
    skip_ai_score: bool = False,
    allow_missing_images: bool = False,
    account: Optional[str] = None,
) -> Dict[str, Any]:
    """把 markdown 发布到头条草稿箱。

    account 只用于 AI 味门禁的账号禁用口头禅检查(头条本身没有账号概念)。

    Returns:
        dict: success / platform / title / pgc_id / draft_url / images / cover / error
        失败时 success=False 且 error 有值,不抛异常(方便被 publish.py 当可选阶段调用)。
    """
    result: Dict[str, Any] = {
        "success": False, "platform": PLATFORM, "title": None,
        "pgc_id": None, "draft_url": None, "images": 0, "cover": False, "error": None,
    }
    try:
        _publish_into(
            result, md_path,
            title=title, cover_path=cover_path, temp_dir=temp_dir,
            ai_score_threshold=ai_score_threshold, skip_ai_score=skip_ai_score,
            allow_missing_images=allow_missing_images, account=account,
        )
    except (ToutiaoPublishError, ToutiaoRenderError) as exc:
        result["error"] = str(exc)
        print(f"\n  [头条] 发布失败：{exc}", file=sys.stderr)
    except SystemExit:
        raise  # AI 味门禁的 exit(1) 要原样穿透
    except Exception as exc:  # noqa: BLE001 - 兜底
        # 头条失败绝不能掀翻微信那条已经成功的链路:异常穿透会让 publish.py
        # 打不出微信的 media_id。所以这里一律翻译成 result["error"]。
        result["error"] = f"{type(exc).__name__}: {exc}"
        print(f"\n  [头条] 发布异常：{result['error']}", file=sys.stderr)
    return result


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="发布文章到今日头条草稿箱")
    p.add_argument("--input", "-i", help="Markdown 文件路径")
    p.add_argument("--title", "-t", help="文章标题(默认从文章提取,头条限 2~30 字)")
    p.add_argument("--cover", "-c", help="封面图路径(默认用文章第一张图)")
    p.add_argument("--temp-dir", default=None, help="临时图片目录")
    p.add_argument("--check", action="store_true", help="只检查登录态,不发布")
    p.add_argument("--ai-score-threshold", type=float, default=None, help="AI 味检测阈值")
    p.add_argument("--skip-ai-score", action="store_true", help="跳过 AI 味检测(不推荐)")
    p.add_argument("--allow-missing-images", action="store_true",
                   help="允许部分图片缺失仍继续(默认缺图即中止)")
    return p


def main() -> int:
    args = _build_parser().parse_args()

    if args.check:
        try:
            info = check()
        except ToutiaoPublishError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
            return 1
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0

    if not args.input:
        _build_parser().error("请提供 --input <markdown>,或用 --check 检查登录态")

    result = run(
        md_path=args.input, title=args.title, cover_path=args.cover,
        temp_dir=args.temp_dir, ai_score_threshold=args.ai_score_threshold,
        skip_ai_score=args.skip_ai_score,
        allow_missing_images=args.allow_missing_images,
    )
    print("\n" + json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
