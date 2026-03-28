#!/bin/bash
# ============================================
# 微信公众号文章一键发布脚本
# ============================================
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================"
echo "  微信公众号文章一键发布"
echo "============================================"

# 检查Python和依赖
command -v python3 &>/dev/null || { echo "错误：未找到 Python3"; exit 1; }
pip3 install requests -q 2>/dev/null || pip install requests -q

# 检查.env
[ -f ".env" ] || { echo "错误：未找到 .env 配置文件"; exit 1; }

echo "[检查] 验证API连接..."
python3 -c "
import sys; sys.path.insert(0, 'scripts')
from wechat_api import get_access_token
try:
    get_access_token(); print('  API连接正常')
except Exception as e:
    print(f'  API连接失败: {e}'); sys.exit(1)
"

echo "[发布] 开始处理文章..."
python3 scripts/publish.py \
  --input article.md \
  --author "AI前沿观察" \
  --title "Anthropic翻车了：一个配置错误，把最强AI模型抖落给了全世界" \
  --digest "3000份内部文档意外公开，史上最强Claude Mythos模型提前曝光。有人存档了被删除的博客原文，有人发现了CEO的秘密庄园聚会，网络安全股应声暴跌——这瓜真的很大。"

echo ""
echo "发布完成！请登录 mp.weixin.qq.com 查看草稿箱"
