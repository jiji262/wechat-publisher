#!/usr/bin/env python3
"""
多账号配置管理

accounts.yaml 为唯一可信来源,不再从 .env 读取微信凭证。
`.env` 只保留给非微信凭证使用(比如 WECHATSYNC_MCP_TOKEN)。

用法:
    from config import set_account, get_config, ConfigError
    set_account("tech")
    cfg = get_config()  # 返回当前账号的完整配置
"""

import json
import os
from pathlib import Path
from typing import Optional, Dict, List, Any

try:
    import yaml  # pyyaml
except ImportError as exc:
    raise ImportError(
        "缺少 pyyaml 依赖。请执行: pip install pyyaml --break-system-packages"
    ) from exc


# ============================================================
# 异常
# ============================================================

class ConfigError(RuntimeError):
    """配置加载失败。由库函数抛出,CLI 层捕获后退出。"""


# ============================================================
# 全局激活账号
# ============================================================

_active_account: Optional[str] = None


def set_account(account_name: Optional[str]) -> None:
    """设置当前激活的账号(全局,影响后续所有调用)。"""
    global _active_account
    _active_account = account_name


def get_account_name() -> Optional[str]:
    """读取当前激活的账号名。"""
    return _active_account


# ============================================================
# .env 加载(仅用于非微信凭证,比如 WECHATSYNC_MCP_TOKEN)
# ============================================================

def load_env(env_path: Optional[Path] = None) -> None:
    """
    从 .env 加载环境变量到 os.environ(不覆盖已有值)。

    注意:从此版本起,**不再**从 .env 读取 WECHAT_APP_ID / WECHAT_APP_SECRET。
    accounts.yaml 是微信凭证的唯一可信来源。
    .env 只用于 WECHATSYNC_MCP_TOKEN 之类的辅助凭证。
    """
    if env_path is None:
        candidates = [
            Path.cwd() / ".env",
            Path(__file__).parent.parent / ".env",
            Path.home() / ".env",
        ]
        for p in candidates:
            if p.exists():
                env_path = p
                break

    if env_path is None or not Path(env_path).exists():
        return

    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


# ============================================================
# accounts.yaml
# ============================================================

def _find_accounts_yaml() -> Optional[Path]:
    """按优先级查找 accounts.yaml: CWD → skill 根 → $HOME/.wechat-publisher/。"""
    candidates = [
        Path.cwd() / "accounts.yaml",
        Path(__file__).parent.parent / "accounts.yaml",
        Path.home() / ".wechat-publisher" / "accounts.yaml",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _load_accounts_yaml(yaml_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """加载并解析 accounts.yaml。返回 None 表示找不到文件。"""
    if yaml_path is None:
        yaml_path = _find_accounts_yaml()
    if yaml_path is None:
        return None

    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def list_accounts() -> List[Dict[str, Any]]:
    """
    列出所有已配置的账号。

    返回统一 schema:
        {"key": str, "name": str, "app_id": str(截短), "author": str, "is_default": bool}
    """
    config = _load_accounts_yaml()
    if not config or "accounts" not in config:
        return []

    default_name = config.get("default", "")
    result = []
    for key, acc in config["accounts"].items():
        app_id = acc.get("app_id", "") or ""
        result.append({
            "key": key,
            "name": acc.get("name", key),
            "app_id": (app_id[:8] + "...") if app_id else "",
            "author": acc.get("author", "") or "",
            "is_default": key == default_name,
        })
    return result


def get_config(account_name: Optional[str] = None) -> Dict[str, Any]:
    """
    获取当前账号的完整配置。

    优先级:
      1. account_name 参数
      2. set_account() 设置的全局账号
      3. accounts.yaml 的 `default` 字段

    Raises:
        ConfigError: 配置文件缺失、账号不存在、或缺少必要字段(app_id/app_secret)

    Returns:
        dict: {
            "app_id": str,
            "app_secret": str,
            "author": str,
            "account_key": str,
            "account_name": str,
            "theme": str,
            "voice": str,
            "sync_platforms": list[str] | None,   # 可选,未配置为 None
        }
    """
    account_name = account_name or _active_account

    yaml_config = _load_accounts_yaml()
    if not yaml_config or "accounts" not in yaml_config or not yaml_config["accounts"]:
        raise ConfigError(
            "未找到 accounts.yaml 或文件为空。请参考 accounts.yaml.example 创建配置。"
        )

    if account_name is None:
        account_name = yaml_config.get("default")

    if account_name is None:
        available = ", ".join(yaml_config["accounts"].keys())
        raise ConfigError(
            f"未指定账号且 accounts.yaml 里无 default。可用账号: {available}"
        )

    if account_name not in yaml_config["accounts"]:
        available = ", ".join(yaml_config["accounts"].keys())
        raise ConfigError(
            f"未找到账号 '{account_name}'。可用账号: {available}"
        )

    acc = yaml_config["accounts"][account_name]
    app_id = acc.get("app_id", "")
    app_secret = acc.get("app_secret", "")
    if not app_id or not app_secret:
        raise ConfigError(
            f"账号 '{account_name}' 缺少 app_id 或 app_secret"
        )

    # sync_platforms 支持两种写法: list 或 comma-separated string
    sync_platforms = acc.get("sync_platforms")
    if isinstance(sync_platforms, str):
        sync_platforms = [p.strip() for p in sync_platforms.split(",") if p.strip()]
    elif isinstance(sync_platforms, list):
        sync_platforms = [str(p).strip() for p in sync_platforms if str(p).strip()]
    else:
        sync_platforms = None

    return {
        "app_id": app_id,
        "app_secret": app_secret,
        "author": acc.get("author", "") or "",
        "account_key": account_name,
        "account_name": acc.get("name", account_name),
        "theme": acc.get("theme", "") or "",
        "image_style": acc.get("image_style", "") or "",
        "voice": acc.get("voice", "") or "",
        "sync_platforms": sync_platforms,
    }


# ============================================================
# 图片风格(assets/image-styles/<name>.json)
# ============================================================

DEFAULT_IMAGE_STYLE = "hand-drawn-blue"


def _image_styles_dir() -> Path:
    """配图风格 JSON 目录: <skill>/assets/image-styles/"""
    return Path(__file__).parent.parent / "assets" / "image-styles"


def list_image_styles() -> List[str]:
    """列出所有可用配图风格名(按名字排序)。"""
    d = _image_styles_dir()
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def get_image_style(name: Optional[str] = None) -> Dict[str, Any]:
    """
    加载一个配图风格的配置。

    Args:
        name: 风格名(对应 assets/image-styles/<name>.json)。
              None 时使用 DEFAULT_IMAGE_STYLE(hand-drawn-blue)。

    Returns:
        完整的 style dict(至少包含 style_name / display_name / prompt_template 等)。

    Raises:
        ConfigError: 风格文件不存在或 JSON 损坏。
    """
    style_name = name or DEFAULT_IMAGE_STYLE
    path = _image_styles_dir() / f"{style_name}.json"
    if not path.exists():
        available = ", ".join(list_image_styles()) or "(无)"
        raise ConfigError(
            f"未找到配图风格 '{style_name}'。可用风格: {available}"
        )
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"配图风格 '{style_name}' JSON 解析失败: {e}") from e


def resolve_image_style(
    cli_value: Optional[str] = None,
    frontmatter_value: Optional[str] = None,
    account_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    按优先级解析最终使用的配图风格:
      1. CLI 参数(--image-style)
      2. brief.md / article.md 的 frontmatter image_style 字段
      3. accounts.yaml 对应账号的 image_style 字段
      4. DEFAULT_IMAGE_STYLE(hand-drawn-blue)

    Returns:
        与 get_image_style() 相同的 style dict。
    """
    for candidate in (cli_value, frontmatter_value):
        if candidate:
            return get_image_style(candidate)

    try:
        cfg = get_config(account_name)
        if cfg.get("image_style"):
            return get_image_style(cfg["image_style"])
    except ConfigError:
        pass

    return get_image_style(DEFAULT_IMAGE_STYLE)
