# wechat-publisher

微信公众号文章自动创作与发布工具:从选题搜索、撰写、AI 配图、排版到发布草稿箱,一条命令搞定。可作为 [Claude Code](https://claude.ai/code) / Codex / Cursor 的 Skill,也可独立命令行调用。

## 功能

- **全网素材搜索**:围绕话题多轮搜索、交叉验证,筛选最新案例与权威观点
- **AI 写作**:3000–5000 字深度长文,多种结构按题材选择,内置反 AI 味规则
- **AI 配图**:`scripts/generate_image.py` 为每章生成风格统一的手绘信息图,支持 OpenAI / Gemini 后端
- **微信排版**:Markdown → 微信兼容 HTML,样式全内联,内置 **15 套主题**,粘贴不丢样式
- **一键发布**:封面、标题、摘要、作者自动填好,直达草稿箱
- **反 AI 检测 gate**:`ai_score.py` 5 维打分,发布前自动拦截高 AI 味稿件

## 安装

作为 Skill 安装(通过 [skills.sh](https://skills.sh)):

```bash
npx skills add jiji262/wechat-publisher
```

或手动安装到 Agent 客户端(推荐软链接,更新仓库即自动生效):

```bash
git clone https://github.com/jiji262/wechat-publisher.git
cd wechat-publisher
pip install requests pyyaml

# Claude Code / Codex / OpenClaw 任选其一:
ln -s "$(pwd)" ~/.claude/skills/wechat-publisher
ln -s "$(pwd)" ~/.codex/skills/wechat-publisher
ln -s "$(pwd)" ~/.openclaw/skills/wechat-publisher
```

安装后重启客户端或新开会话让 skill 被发现。

## 配置

复制模板并填入凭证:

```bash
cp wechat-publisher.yaml.example wechat-publisher.yaml
```

```yaml
default: main
accounts:
  main:
    name: "我的公众号"
    app_id: "wx..."
    app_secret: "..."
    author: "作者名"

image_generation:
  generator: "baoyu-image-gen"      # 或 baoyu-danger-gemini-web(Web 登录版 Gemini)
  gemini_proxy:
    base_url: "https://generativelanguage.googleapis.com"
    api_key: "AIza..."
    image_model: "gemini-2.5-flash"

integrations:
  wechatsync_mcp_token: ""
```

在[微信公众平台](https://mp.weixin.qq.com) → 设置与开发 → 基本配置 获取 AppID / AppSecret,并把 `curl ifconfig.me` 得到的公网 IP 加入「IP 白名单」(否则报 `40164`)。验证连接:

```bash
python3 scripts/wechat_api.py list-accounts
```

## 使用

### 作为 Skill

```
使用 /wechat-publisher 写一篇关于"大模型 Agent 最新进展"的公众号文章
```

Skill 自动执行 7 阶段:搜索素材 → 选结构 → 撰写 → 人味化改写 → 生成配图 → 排版转换 → AI 味自检 →发布草稿 →(可选)多平台同步。完整流程见 [`SKILL.md`](SKILL.md)。

### 命令行

```bash
# 一键发布:Markdown → 草稿箱
python3 scripts/publish.py --account main --input article.md \
  --cover cover.jpg --title "标题" --digest "摘要"

# 只转排版:Markdown → 微信 HTML
python3 scripts/html_converter.py article.md --theme refined-blue -o article.html

# 单独跑 AI 味检测
python3 scripts/ai_score.py article.md --threshold 45
```

`publish.py` 会从 `wechat-publisher.yaml` 读 author / theme,依次做图片处理 → HTML 转换 → AI 味 gate(默认阈值 45)→ 封面上传 → 创建草稿。每个脚本 `--help` 查看完整参数。

## 排版主题

内置 **15 套主题**(`assets/themes/*.json`):正文 ~15.5px、行高 ~1.85、纯 inline style、无外部依赖。打开 [`assets/theme-previews/index.html`](assets/theme-previews/index.html) 可在手机宽度 frame 里并排对比、按分类筛选。

![15 套公众号主题总览](assets/theme-previews/screenshots/theme-overview.webp)

<table>
<tr>
<td width="50%">
<img src="assets/theme-previews/screenshots/refined-blue.webp" alt="refined-blue preview" />
<br /><code>refined-blue</code> · main 默认,AI / 产品 / 深度分析
</td>
<td width="50%">
<img src="assets/theme-previews/screenshots/minimal-mono.webp" alt="minimal-mono preview" />
<br /><code>minimal-mono</code> · tech 默认,技术 / 工程
</td>
</tr>
<tr>
<td width="50%">
<img src="assets/theme-previews/screenshots/news-bold.webp" alt="news-bold preview" />
<br /><code>news-bold</code> · 新闻 / 热点 / 速读
</td>
<td width="50%">
<img src="assets/theme-previews/screenshots/ink-wash.webp" alt="ink-wash preview" />
<br /><code>ink-wash</code> · 人文 / 随笔 / 文化
</td>
</tr>
</table>

| 类别 | 推荐主题 |
|---|---|
| AI / 产品 / 深度分析 | `refined-blue`(main 默认)· `business-navy` · `sage-premium` |
| 技术 / SDK / 工程 | `minimal-mono`(tech 默认)· `minimal-bw` · `academic-paper` |
| 新闻 / 热点 / 速读 | `news-bold` · `warm-editorial` |
| 人文 / 随笔 / 文化 | `ink-wash` · `elegant-ink` · `magazine-grid` |
| 生活 / 美食 / 旅行 | `warm-orange` · `mint-fresh` · `sunset-coral` |
| 时尚 / 美妆 / 情感 | `girly-pink` · `sunset-coral` |

新增主题:复制任意 `assets/themes/*.json` 改名改键即可,无需改代码。详见 [`assets/theme-previews/README.md`](assets/theme-previews/README.md)。

## 常见问题

| 错误 | 解决 |
|---|---|
| `ConfigError: 未找到 wechat-publisher.yaml` | 复制 `.example` 并填值 |
| `40164` IP 不在白名单 | `curl ifconfig.me` 取 IP,加入公众平台白名单 |
| `40001` access_token 无效 | 检查 AppID / AppSecret |
| `40009` 图片超 10MB | 压缩后重试 |
| `45166` 内容不合规 | 检查敏感词或特殊 HTML 标签 |
| `ai_score.py` 返回 FAIL | 按命中清单重写,或 `--skip-ai-score` 临时绕过 |

## 注意事项

- 文章发布到**草稿箱**,不会自动群发
- access_token 有效期 2 小时,脚本自动缓存与刷新
- 正文图走 `uploadimg`(不占素材名额),封面走 `add_material`(占用永久素材名额)

## 测试

```bash
pip install pytest
python3 -m pytest tests/ -v
```

测试不依赖真实微信凭证(网络调用全部 mock),覆盖配置解析、AI 味打分与 HTML 转换安全性。

## License

MIT
