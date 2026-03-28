#!/usr/bin/env python3
"""
微信公众号 API 客户端

封装了微信公众号开发所需的核心API调用：
- access_token 获取与自动刷新
- 图片素材上传（永久素材 + 文章内图片）
- 草稿箱操作（新建草稿）
- 多账号支持（通过 accounts.yaml 配置）

配置方式（二选一）：
  方式一：accounts.yaml 多账号配置（推荐）
  方式二：.env 单账号配置（向后兼容）
"""

import os
import sys
import json
import time
import requests
from pathlib import Path

# ============================================================
# 配置管理（支持多账号）
# ============================================================

# 当前激活的账号名，通过 set_account() 设置
_active_account = None

def _find_accounts_yaml():
    """查找 accounts.yaml 配置文件"""
    candidates = [
        Path.cwd() / "accounts.yaml",
        Path(__file__).parent.parent / "accounts.yaml",
        Path.home() / ".wechat-publisher" / "accounts.yaml",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _load_accounts_yaml(yaml_path=None):
    """加载 accounts.yaml 配置"""
    if yaml_path is None:
        yaml_path = _find_accounts_yaml()
    if yaml_path is None:
        return None

    try:
        import yaml
    except ImportError:
        # 轻量级YAML解析（仅支持简单的 key: value 格式）
        return _parse_simple_yaml(yaml_path)

    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _parse_simple_yaml(yaml_path):
    """简易YAML解析器，不依赖PyYAML库"""
    with open(yaml_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    result = {"accounts": {}}
    current_account = None
    default_name = None

    for line in lines:
        stripped = line.rstrip()
        if not stripped or stripped.lstrip().startswith("#"):
            continue

        indent = len(line) - len(line.lstrip())

        if stripped.startswith("default:"):
            default_name = stripped.split(":", 1)[1].strip().strip('"').strip("'")
        elif indent == 2 and stripped.endswith(":") and "accounts" not in stripped:
            current_account = stripped.strip().rstrip(":")
            result["accounts"][current_account] = {}
        elif indent >= 4 and current_account and ":" in stripped:
            key, _, value = stripped.strip().partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            result["accounts"][current_account][key] = value

    if default_name:
        result["default"] = default_name
    return result


def set_account(account_name):
    """设置当前激活的账号"""
    global _active_account
    _active_account = account_name


def get_account_name():
    """获取当前激活的账号名"""
    return _active_account


def list_accounts():
    """列出所有可用的账号"""
    config = _load_accounts_yaml()
    if not config or "accounts" not in config:
        # 回退到 .env 模式
        load_env()
        app_id = os.environ.get("WECHAT_APP_ID", "")
        if app_id:
            return [{"name": "default", "app_id": app_id[:8] + "...", "source": ".env"}]
        return []

    accounts = []
    default_name = config.get("default", "")
    for key, acc in config["accounts"].items():
        accounts.append({
            "key": key,
            "name": acc.get("name", key),
            "app_id": acc.get("app_id", "")[:8] + "...",
            "author": acc.get("author", ""),
            "is_default": key == default_name,
        })
    return accounts


def load_env(env_path=None):
    """从 .env 文件加载环境变量"""
    if env_path is None:
        # 依次查找：当前目录 → skill目录 → 用户主目录
        candidates = [
            Path.cwd() / ".env",
            Path(__file__).parent.parent / ".env",
            Path.home() / ".env",
        ]
        for p in candidates:
            if p.exists():
                env_path = p
                break

    if env_path and Path(env_path).exists():
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    os.environ.setdefault(key, value)


def get_config(account_name=None):
    """
    获取微信API配置。

    优先级：
    1. 指定的 account_name 参数
    2. 通过 set_account() 设置的全局账号
    3. accounts.yaml 中的 default 账号
    4. .env 中的单账号配置（向后兼容）

    Returns:
        dict: {"app_id": ..., "app_secret": ..., "author": ..., "account_key": ...}
    """
    account_name = account_name or _active_account

    # 尝试从 accounts.yaml 加载
    yaml_config = _load_accounts_yaml()
    if yaml_config and "accounts" in yaml_config and yaml_config["accounts"]:
        if account_name is None:
            account_name = yaml_config.get("default")

        if account_name and account_name in yaml_config["accounts"]:
            acc = yaml_config["accounts"][account_name]
            app_id = acc.get("app_id", "")
            app_secret = acc.get("app_secret", "")
            if app_id and app_secret:
                return {
                    "app_id": app_id,
                    "app_secret": app_secret,
                    "author": acc.get("author", ""),
                    "account_key": account_name,
                    "account_name": acc.get("name", account_name),
                }

        # 如果指定了账号名但找不到
        if account_name:
            available = ", ".join(yaml_config["accounts"].keys())
            print(f"错误：未找到账号 '{account_name}'。", file=sys.stderr)
            print(f"可用账号：{available}", file=sys.stderr)
            sys.exit(1)

    # 回退到 .env 单账号模式
    load_env()
    app_id = os.environ.get("WECHAT_APP_ID", "")
    app_secret = os.environ.get("WECHAT_APP_SECRET", "")

    if not app_id or not app_secret:
        print("错误：未找到微信公众号配置。", file=sys.stderr)
        print("请使用以下任一方式配置：", file=sys.stderr)
        print("  方式一：创建 accounts.yaml（支持多账号，参考 accounts.yaml.example）", file=sys.stderr)
        print("  方式二：在 .env 中设置 WECHAT_APP_ID 和 WECHAT_APP_SECRET", file=sys.stderr)
        sys.exit(1)

    return {
        "app_id": app_id,
        "app_secret": app_secret,
        "author": "",
        "account_key": "default",
        "account_name": "default",
    }


# ============================================================
# Token 管理（按账号隔离缓存）
# ============================================================

_token_caches = {}  # account_key → {"token": ..., "expires_at": ...}
TOKEN_CACHE_DIR = Path(__file__).parent


def _get_token_cache_file(account_key="default"):
    """获取指定账号的token缓存文件路径"""
    if account_key == "default":
        return TOKEN_CACHE_DIR / ".token_cache.json"
    return TOKEN_CACHE_DIR / f".token_cache_{account_key}.json"


def _load_token_cache(account_key="default"):
    """从文件加载指定账号的缓存token"""
    cache_file = _get_token_cache_file(account_key)
    if cache_file.exists():
        try:
            with open(cache_file, "r") as f:
                cached = json.load(f)
                if cached.get("expires_at", 0) > time.time() + 300:
                    _token_caches[account_key] = cached
                    return
        except (json.JSONDecodeError, KeyError):
            pass
    _token_caches.setdefault(account_key, {"token": None, "expires_at": 0})


def _save_token_cache(account_key="default"):
    """保存token到文件"""
    cache = _token_caches.get(account_key)
    if not cache:
        return
    try:
        cache_file = _get_token_cache_file(account_key)
        with open(cache_file, "w") as f:
            json.dump(cache, f)
    except IOError:
        pass


def get_access_token(force_refresh=False, account_name=None):
    """
    获取 access_token，带自动缓存和刷新。

    微信的 access_token 有效期为7200秒（2小时），
    这里在到期前5分钟自动刷新。

    Args:
        force_refresh: 强制刷新token
        account_name: 账号名（可选，默认使用当前激活账号）

    Returns:
        str: 有效的 access_token
    """
    config = get_config(account_name)
    account_key = config.get("account_key", "default")

    _load_token_cache(account_key)
    cache = _token_caches.get(account_key, {"token": None, "expires_at": 0})

    if not force_refresh and cache["token"] and cache["expires_at"] > time.time() + 300:
        return cache["token"]

    url = "https://api.weixin.qq.com/cgi-bin/token"
    params = {
        "grant_type": "client_credential",
        "appid": config["app_id"],
        "secret": config["app_secret"],
    }

    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if "access_token" not in data:
        error_msg = data.get("errmsg", "未知错误")
        error_code = data.get("errcode", -1)
        raise RuntimeError(f"获取access_token失败 [{error_code}] (账号: {account_key}): {error_msg}")

    _token_caches[account_key] = {
        "token": data["access_token"],
        "expires_at": time.time() + data.get("expires_in", 7200),
    }
    _save_token_cache(account_key)

    return data["access_token"]


# ============================================================
# 图片上传
# ============================================================

def upload_thumb_image(image_path):
    """
    上传封面图（永久素材）。

    封面图会占用公众号的永久素材名额（图片上限5000个），
    返回的 media_id 在创建草稿时用作 thumb_media_id。

    Args:
        image_path: 图片文件路径

    Returns:
        str: 素材的 media_id
    """
    token = get_access_token()
    url = f"https://api.weixin.qq.com/cgi-bin/material/add_material?access_token={token}&type=image"

    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"图片文件不存在: {image_path}")

    # 推断MIME类型
    suffix = image_path.suffix.lower()
    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif"}
    mime_type = mime_map.get(suffix, "image/jpeg")

    with open(image_path, "rb") as f:
        files = {"media": (image_path.name, f, mime_type)}
        resp = requests.post(url, files=files, timeout=30)

    resp.raise_for_status()
    data = resp.json()

    if "media_id" not in data:
        error_msg = data.get("errmsg", "未知错误")
        raise RuntimeError(f"上传封面图失败: {error_msg}")

    print(f"封面图上传成功: media_id={data['media_id']}")
    return data["media_id"]


def upload_content_image(image_path):
    """
    上传文章正文中的图片。

    使用 uploadimg 接口，返回微信CDN的图片URL，
    该URL可直接嵌入文章HTML中。此接口上传的图片
    不占用永久素材名额。

    Args:
        image_path: 图片文件路径

    Returns:
        str: 微信CDN的图片URL
    """
    token = get_access_token()
    url = f"https://api.weixin.qq.com/cgi-bin/media/uploadimg?access_token={token}"

    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"图片文件不存在: {image_path}")

    with open(image_path, "rb") as f:
        files = {"media": (image_path.name, f, "image/jpeg")}
        resp = requests.post(url, files=files, timeout=30)

    resp.raise_for_status()
    data = resp.json()

    if "url" not in data:
        error_msg = data.get("errmsg", "未知错误")
        raise RuntimeError(f"上传正文图片失败: {error_msg}")

    print(f"正文图片上传成功: {data['url']}")
    return data["url"]


# ============================================================
# 草稿箱操作
# ============================================================

def add_draft(articles):
    """
    新建草稿。

    Args:
        articles: 文章列表，每篇文章是一个字典，包含：
            - title (str): 标题
            - content (str): 正文HTML
            - thumb_media_id (str): 封面图media_id
            - author (str, optional): 作者
            - digest (str, optional): 摘要
            - content_source_url (str, optional): 原文链接
            - need_open_comment (int, optional): 是否打开评论 0/1
            - only_fans_can_comment (int, optional): 是否仅粉丝可评论 0/1

    Returns:
        str: 草稿的 media_id
    """
    token = get_access_token()
    url = f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={token}"

    # 确保 articles 是列表
    if isinstance(articles, dict):
        articles = [articles]

    payload = {"articles": articles}

    resp = requests.post(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    if "media_id" not in data:
        error_msg = data.get("errmsg", "未知错误")
        error_code = data.get("errcode", -1)
        raise RuntimeError(f"新建草稿失败 [{error_code}]: {error_msg}")

    print(f"草稿创建成功！media_id={data['media_id']}")
    return data["media_id"]


# ============================================================
# 便捷函数
# ============================================================

def publish_article(title, html_content, cover_image_path, author="", digest="", source_url="", account_name=None):
    """
    一站式发布文章到草稿箱。

    完整流程：上传封面图 → 创建草稿

    Args:
        title: 文章标题
        html_content: 文章HTML内容（已排版）
        cover_image_path: 封面图路径
        author: 作者名
        digest: 文章摘要（不超过120字）
        source_url: 原文链接
        account_name: 账号名（可选，默认使用当前激活账号）

    Returns:
        dict: {"media_id": "草稿media_id", "status": "success", "account": "账号名"}
    """
    # 如果指定了账号，激活它
    if account_name:
        set_account(account_name)

    # 如果没有指定author，尝试从账号配置中获取
    if not author:
        config = get_config(account_name)
        author = config.get("author", "")

    account_display = get_config(account_name).get("account_name", "default")
    print(f"开始发布文章：{title}")
    print(f"目标账号：{account_display}")
    print("=" * 50)

    # 1. 上传封面图
    print("[1/2] 上传封面图...")
    thumb_media_id = upload_thumb_image(cover_image_path)

    # 2. 创建草稿
    print("[2/2] 创建草稿...")
    article = {
        "title": title,
        "content": html_content,
        "thumb_media_id": thumb_media_id,
        "author": author,
        "digest": digest[:120] if digest else "",
    }
    if source_url:
        article["content_source_url"] = source_url

    media_id = add_draft(article)

    print("=" * 50)
    print(f"发布成功！文章已保存到草稿箱。")
    print(f"请登录微信公众平台查看和发布。")

    return {"media_id": media_id, "status": "success", "account": account_display}


# ============================================================
# 命令行入口
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="微信公众号API工具")
    parser.add_argument("--account", help="指定公众号账号（对应 accounts.yaml 中的账号名）")
    subparsers = parser.add_subparsers(dest="command")

    # list-accounts 命令
    subparsers.add_parser("list-accounts", help="列出所有已配置的公众号账号")

    # token 命令
    sub_token = subparsers.add_parser("token", help="获取access_token")

    # upload-thumb 命令
    sub_upload = subparsers.add_parser("upload-thumb", help="上传封面图")
    sub_upload.add_argument("image", help="图片文件路径")

    # upload-img 命令
    sub_img = subparsers.add_parser("upload-img", help="上传正文图片")
    sub_img.add_argument("image", help="图片文件路径")

    # draft 命令
    sub_draft = subparsers.add_parser("draft", help="创建草稿")
    sub_draft.add_argument("--title", required=True, help="文章标题")
    sub_draft.add_argument("--content", required=True, help="HTML内容文件路径")
    sub_draft.add_argument("--cover", required=True, help="封面图路径")
    sub_draft.add_argument("--author", default="", help="作者")
    sub_draft.add_argument("--digest", default="", help="摘要")

    args = parser.parse_args()

    # 设置全局账号
    if args.account:
        set_account(args.account)

    if args.command == "list-accounts":
        accounts = list_accounts()
        if not accounts:
            print("未找到任何账号配置。")
            print("请创建 accounts.yaml（参考 accounts.yaml.example）或在 .env 中配置。")
        else:
            print(f"已配置 {len(accounts)} 个账号：")
            for acc in accounts:
                default_mark = " (默认)" if acc.get("is_default") else ""
                source = acc.get("source", "accounts.yaml")
                name = acc.get("name", acc.get("key", ""))
                print(f"  {acc.get('key', 'default'):12s}  {name:16s}  AppID: {acc['app_id']}  作者: {acc.get('author', '-')}{default_mark}  [{source}]")

    elif args.command == "token":
        token = get_access_token()
        print(f"access_token: {token}")

    elif args.command == "upload-thumb":
        media_id = upload_thumb_image(args.image)
        print(json.dumps({"media_id": media_id}, ensure_ascii=False))

    elif args.command == "upload-img":
        url = upload_content_image(args.image)
        print(json.dumps({"url": url}, ensure_ascii=False))

    elif args.command == "draft":
        with open(args.content, "r", encoding="utf-8") as f:
            html = f.read()
        result = publish_article(
            title=args.title,
            html_content=html,
            cover_image_path=args.cover,
            author=args.author,
            digest=args.digest,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))

    else:
        parser.print_help()
