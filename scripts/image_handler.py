#!/usr/bin/env python3
"""
图片处理模块

负责文章图片的完整生命周期：
1. 从网络搜索并下载相关图片
2. 图片格式检查和基本处理
3. 上传到微信服务器获取CDN链接
4. 替换文章中的图片引用

搜索图片时会优先寻找无版权限制的图片源。
"""

import os
import re
import sys
import json
import hashlib
import requests
from pathlib import Path
from urllib.parse import urlparse, quote

# 导入微信API
sys.path.insert(0, str(Path(__file__).parent))
from wechat_api import upload_content_image, upload_thumb_image, set_account


# ============================================================
# 图片下载
# ============================================================

def download_image(url, save_dir, filename=None, timeout=15, max_retries=2):
    """
    从URL下载图片到本地，支持自动重试。

    Args:
        url: 图片URL
        save_dir: 保存目录
        filename: 文件名（可选，默认根据URL生成）
        timeout: 超时时间
        max_retries: 最大重试次数

    Returns:
        str: 本地文件路径，下载失败返回None
    """
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    if not filename:
        # 从URL推断文件名
        parsed = urlparse(url)
        path = parsed.path
        ext = Path(path).suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
            ext = ".jpg"
        url_hash = hashlib.md5(url.encode()).hexdigest()[:10]
        filename = f"img_{url_hash}{ext}"

    filepath = save_dir / filename

    for attempt in range(max_retries + 1):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=timeout, stream=True, allow_redirects=True)
            resp.raise_for_status()

            # 检查是否真的是图片
            content_type = resp.headers.get("Content-Type", "")
            if "image" not in content_type and "octet-stream" not in content_type:
                print(f"  警告：{url[:60]} 返回的不是图片类型 ({content_type})")
                return None

            with open(filepath, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

            # 检查文件大小（微信限制图片不超过10MB）
            file_size = filepath.stat().st_size
            if file_size < 1000:  # 小于1KB可能不是有效图片
                filepath.unlink()
                return None
            if file_size > 10 * 1024 * 1024:
                print(f"  警告：图片过大 ({file_size/1024/1024:.1f}MB)，尝试跳过")
                filepath.unlink()
                return None

            # WebP格式转JPG（微信对WebP支持不稳定）
            if filepath.suffix.lower() == ".webp":
                jpg_path = filepath.with_suffix(".jpg")
                converted = convert_webp_to_jpg(str(filepath), str(jpg_path))
                if converted:
                    filepath.unlink()
                    filepath = jpg_path

            print(f"  下载成功：{filepath.name} ({file_size/1024:.0f}KB)")
            return str(filepath)

        except requests.exceptions.Timeout:
            if attempt < max_retries:
                print(f"  下载超时，重试 ({attempt+1}/{max_retries})...")
                continue
            print(f"  下载超时失败：{url[:60]}")
        except Exception as e:
            if attempt < max_retries:
                print(f"  下载出错，重试 ({attempt+1}/{max_retries})...")
                continue
            print(f"  下载失败 {url[:60]}: {e}")

        if filepath.exists():
            filepath.unlink()

    return None


def convert_webp_to_jpg(webp_path, jpg_path):
    """将WebP图片转换为JPG格式（微信对WebP支持不稳定）"""
    try:
        from PIL import Image
        img = Image.open(webp_path).convert("RGB")
        img.save(jpg_path, "JPEG", quality=90)
        return True
    except ImportError:
        # 没有Pillow就保留webp，微信新版本也能显示
        return False
    except Exception:
        return False


def download_images_from_urls(urls, save_dir):
    """
    批量下载图片。

    Args:
        urls: URL列表
        save_dir: 保存目录

    Returns:
        list[dict]: 下载结果列表 [{"url": ..., "local_path": ...}, ...]
    """
    results = []
    for url in urls:
        local_path = download_image(url, save_dir)
        results.append({
            "url": url,
            "local_path": local_path,
            "success": local_path is not None
        })
    return results


# ============================================================
# 图片上传到微信
# ============================================================

def upload_images_to_wechat(image_paths, as_thumb=False):
    """
    批量上传图片到微信服务器。

    Args:
        image_paths: 本地图片路径列表
        as_thumb: 是否作为封面图上传（永久素材）

    Returns:
        dict: {本地路径: 微信URL/media_id}
    """
    mapping = {}
    for path in image_paths:
        if not path or not Path(path).exists():
            continue
        try:
            if as_thumb:
                result = upload_thumb_image(path)
            else:
                result = upload_content_image(path)
            mapping[path] = result
        except Exception as e:
            print(f"上传失败 {path}: {e}")
            mapping[path] = None
    return mapping


# ============================================================
# 文章图片替换
# ============================================================

def replace_images_in_html(html_content, image_mapping):
    """
    将HTML中的本地图片路径替换为微信CDN链接。

    Args:
        html_content: HTML字符串
        image_mapping: {本地路径或原始URL: 微信CDN URL}

    Returns:
        str: 替换后的HTML
    """
    for original, wechat_url in image_mapping.items():
        if wechat_url:
            html_content = html_content.replace(original, wechat_url)
    return html_content


def replace_images_in_markdown(md_content, image_mapping):
    """
    将Markdown中的图片路径替换为微信CDN链接。

    Args:
        md_content: Markdown字符串
        image_mapping: {原始路径/URL: 微信CDN URL}

    Returns:
        str: 替换后的Markdown
    """
    for original, wechat_url in image_mapping.items():
        if wechat_url:
            md_content = md_content.replace(original, wechat_url)
    return md_content


def extract_images_from_markdown(md_content):
    """
    从Markdown中提取所有图片引用。

    Returns:
        list[dict]: [{"alt": "描述", "url": "路径/URL"}, ...]
    """
    pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
    matches = re.findall(pattern, md_content)
    return [{"alt": alt, "url": url} for alt, url in matches]


def extract_images_from_html(html_content):
    """
    从HTML中提取所有img标签的src。

    Returns:
        list[str]: 图片URL列表
    """
    pattern = r'<img[^>]+src=["\']([^"\']+)["\']'
    return re.findall(pattern, html_content)


# ============================================================
# 完整图片处理流程
# ============================================================

def process_article_images(md_content, temp_dir="/tmp/wechat_images"):
    """
    完整的文章图片处理流程：
    1. 提取Markdown中的所有图片引用
    2. 下载外部图片到本地
    3. 上传所有图片到微信服务器
    4. 替换Markdown中的图片链接

    Args:
        md_content: Markdown文章内容
        temp_dir: 临时图片目录

    Returns:
        tuple: (处理后的Markdown, 图片映射字典, 第一张图片的本地路径)
    """
    temp_dir = Path(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    images = extract_images_from_markdown(md_content)
    if not images:
        print("文章中没有找到图片引用")
        return md_content, {}, None

    print(f"发现 {len(images)} 张图片，开始处理...")

    mapping = {}  # 原始URL → 微信URL
    first_image_path = None

    for i, img in enumerate(images):
        url = img["url"]
        alt = img["alt"]
        print(f"[{i+1}/{len(images)}] 处理图片：{alt or url[:50]}")

        local_path = None

        # 判断是本地文件还是网络URL
        if url.startswith(("http://", "https://")):
            local_path = download_image(url, temp_dir, filename=f"article_{i}.jpg")
        elif Path(url).exists():
            local_path = url
        else:
            print(f"  跳过无效路径：{url}")
            continue

        if local_path:
            if first_image_path is None:
                first_image_path = local_path

            try:
                wechat_url = upload_content_image(local_path)
                mapping[url] = wechat_url
                print(f"  上传成功 → {wechat_url[:60]}...")
            except Exception as e:
                print(f"  上传失败：{e}")

    # 替换Markdown中的图片链接
    processed_md = replace_images_in_markdown(md_content, mapping)

    print(f"图片处理完成：{len(mapping)}/{len(images)} 张成功上传")
    return processed_md, mapping, first_image_path


# ============================================================
# 命令行入口
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="微信公众号图片处理工具")
    parser.add_argument("--account", help="指定公众号账号（对应 accounts.yaml 中的账号名）")
    subparsers = parser.add_subparsers(dest="command")

    # download 命令
    sub_dl = subparsers.add_parser("download", help="下载图片")
    sub_dl.add_argument("url", help="图片URL")
    sub_dl.add_argument("-d", "--dir", default="/tmp/wechat_images", help="保存目录")

    # upload 命令
    sub_up = subparsers.add_parser("upload", help="上传图片到微信")
    sub_up.add_argument("path", help="本地图片路径")
    sub_up.add_argument("--thumb", action="store_true", help="作为封面图上传")

    # process 命令
    sub_proc = subparsers.add_parser("process", help="处理文章中的所有图片")
    sub_proc.add_argument("markdown_file", help="Markdown文件路径")
    sub_proc.add_argument("-o", "--output", help="输出文件路径")

    args = parser.parse_args()

    # 设置全局账号
    if args.account:
        set_account(args.account)

    if args.command == "download":
        path = download_image(args.url, args.dir)
        if path:
            print(json.dumps({"local_path": path}))
        else:
            print("下载失败", file=sys.stderr)
            sys.exit(1)

    elif args.command == "upload":
        if args.thumb:
            result = upload_thumb_image(args.path)
            print(json.dumps({"media_id": result}))
        else:
            result = upload_content_image(args.path)
            print(json.dumps({"url": result}))

    elif args.command == "process":
        with open(args.markdown_file, "r", encoding="utf-8") as f:
            md = f.read()
        processed, mapping, cover = process_article_images(md)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(processed)
        print(json.dumps({
            "cover_image": cover,
            "images_processed": len(mapping),
            "mapping": mapping
        }, ensure_ascii=False, indent=2))

    else:
        parser.print_help()
