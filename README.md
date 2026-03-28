# wechat-publisher

微信公众号文章自动创作与发布工具。从选题搜索、文章撰写、AI配图生成、排版美化到发布草稿箱，一条命令搞定全流程。

可作为 [Claude Code](https://claude.ai/code) 的 Skill 使用，也可以独立命令行调用。

## 功能特性

- **全网素材搜索**：围绕话题自动多轮搜索，交叉验证数据，筛选最新案例和权威观点
- **AI智能写作**：按照头部博主风格生成3000-5000字深度文章，反AI味写作规则，段落短小有呼吸感
- **AI配图生成**：集成图片生成能力，为每个章节生成风格统一的手绘信息图（6-10张/篇）
- **微信排版转换**：Markdown → 微信兼容HTML，所有样式自动内联，蓝色主题精美排版
- **图片CDN上传**：自动上传图片到微信服务器，获取 `mmbiz.qpic.cn` 链接并替换占位符
- **一键发布草稿**：封面图、标题、摘要、作者全部自动填好，直达草稿箱
- **爆款标题公式**：内置5种10w+标题写法（痛点+方案+数字、身份代入+结果、反常识/悬念等）

## 项目结构

```
wechat-publisher/
├── SKILL.md              # Claude Code Skill 定义文件（6阶段工作流）
├── README.md             # 项目说明
├── .env.example          # 环境变量模板
├── .gitignore
├── 一键发布.sh            # Shell快捷脚本
├── scripts/
│   ├── publish.py        # 一键发布主流程（串联所有模块）
│   ├── wechat_api.py     # 微信API封装（token、上传、草稿）
│   ├── html_converter.py # Markdown → 微信HTML转换器
│   └── image_handler.py  # 图片下载/上传/替换
├── assets/
│   └── style_config.json # 排版样式配置（可自定义配色）
└── references/
    └── api_reference.md  # 微信API接口文档
```

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/jiji262/wechat-publisher.git
cd wechat-publisher
```

### 2. 安装依赖

```bash
pip install requests
```

### 3. 配置微信公众号

登录 [微信公众平台](https://mp.weixin.qq.com) → 设置与开发 → 基本配置：

1. 获取 AppID 和 AppSecret（首次使用需启用开发者密码）
2. 在「IP白名单」中添加当前机器的公网IP（`curl ifconfig.me` 查询）
3. 创建 `.env` 文件：

```bash
WECHAT_APP_ID=你的AppID
WECHAT_APP_SECRET=你的AppSecret
```

### 4. 验证连接

```bash
cd scripts
python3 -c "from wechat_api import get_access_token; print('连接成功:', get_access_token()[:10]+'...')"
```

## 使用方式

### 方式一：作为 Claude Code Skill（推荐）

将项目复制到 Claude Code 的 skills 目录：

```bash
cp -r wechat-publisher ~/.claude/skills/wechat-publisher
```

然后在 Claude Code 中直接用自然语言：

```
使用 /wechat-publisher 写一篇关于"大模型Agent最新进展"的公众号文章
```

也支持更具体的指令：

```
使用 /wechat-publisher 根据这篇论文写一篇公众号文章，
目标读者是AI开发者，风格偏技术科普，重点解读实验结果
```

或者提供参考资料：

```
使用 /wechat-publisher 基于以下3篇文章综合写一篇分析，
文章1: [URL]
文章2: [URL]
```

Skill 会自动执行6阶段工作流：搜索素材 → 撰写文章 → 生成配图 → 转换排版 → 上传图片 → 发布草稿。

### 方式二：命令行调用

**一键发布（Markdown → 草稿箱）：**

```bash
python3 scripts/publish.py \
  --input article.md \
  --cover cover.jpg \
  --title "文章标题" \
  --digest "文章摘要" \
  --author "作者名"
```

**从已有HTML发布：**

```bash
python3 scripts/publish.py \
  --html article.html \
  --cover cover.jpg \
  --title "文章标题"
```

**只做格式转换（Markdown → 微信HTML）：**

```bash
python3 scripts/html_converter.py article.md -o article.html
```

**只处理图片：**

```bash
# 上传单张图片到微信CDN
python3 scripts/image_handler.py upload photo.jpg

# 批量处理文章中的所有图片链接
python3 scripts/image_handler.py process article.md -o article_processed.md
```

每个脚本都支持 `--help` 查看完整参数。

## 排版主题

内置清新蓝色主题，专为微信阅读体验优化：

| 元素 | 样式 |
|------|------|
| 主色调 | `#4a6cf7`（优雅蓝） |
| 正文 | 15px / 2倍行高 / 0.8px字间距 |
| 二级标题 | 蓝色左边框 + 淡蓝渐变背景 |
| 引用块 | 浅灰蓝底 + 蓝色左边框 |
| 代码块 | 深色Catppuccin主题 / 10px圆角 |
| 图片 | 6px圆角 + 柔和阴影 |
| 列表 | 蓝色实心圆点 |

### 自定义配色

编辑 `assets/style_config.json`，修改颜色值即可：

```json
{
  "styles": {
    "h2": "font-size: 18px; color: #1a1a2e; border-left: 4px solid #你的颜色;",
    "strong": "color: #你的颜色; font-weight: 600;"
  }
}
```

## 脚本说明

### publish.py - 一键发布

串联所有模块，实现完整发布流程：读取Markdown → 处理图片 → 转换HTML → 上传封面 → 创建草稿。

默认作者为"飞哥"，可通过 `--author` 自定义。

### wechat_api.py - 微信API封装

封装了三个核心接口：
- **access_token 管理**：本地文件缓存，过期前5分钟自动刷新
- **图片上传**：正文图片用 `uploadimg`（返回CDN链接），封面图用 `add_material`（返回media_id）
- **草稿创建**：调用 `draft/add` 接口，支持标题、摘要、作者等字段

### html_converter.py - Markdown转换器

处理微信编辑器的特殊限制：
- 所有CSS样式内联到每个标签的 `style` 属性
- HTML实体转义（代码块中的 `<style>` 等标签不会被误解析）
- 支持标题、段落、列表、引用块、代码块、表格、图片、链接等Markdown语法

### image_handler.py - 图片处理

支持三种操作模式：
- `upload`：上传本地图片到微信CDN
- `download`：从URL下载图片到本地
- `process`：批量替换文章中的外部图片链接为微信CDN链接

## 常见问题

| 错误 | 原因 | 解决方法 |
|------|------|----------|
| `40164` IP不在白名单 | 机器IP未添加白名单 | `curl ifconfig.me` 获取IP，添加到公众平台 |
| `40001` access_token无效 | 凭证错误或token过期 | 检查 `.env` 中的 AppID/AppSecret |
| `40009` 图片大小超限 | 图片超过10MB | 压缩图片后重试 |
| `45166` 内容不合规 | 文章内容触发平台过滤 | 检查是否包含敏感词或特殊HTML标签 |
| `48001` 接口未授权 | 公众号类型不支持 | 需要已认证的服务号或订阅号 |
| 图片不显示 | 未使用微信CDN链接 | 确保所有图片通过 `uploadimg` 接口上传 |

## 注意事项

- 文章发布到**草稿箱**，不会自动群发，可放心使用
- access_token 有效期2小时，脚本自动管理缓存和刷新
- 微信API有频率限制（每日素材上传上限），避免短时间大量操作
- 正文图片通过 `uploadimg` 接口上传，不占用永久素材名额（上限5000个）
- 封面图通过 `add_material` 上传，会占用永久素材名额
- 微信编辑器不支持外部CSS、class属性、`<style>` 标签，所有样式必须内联

## License

MIT
