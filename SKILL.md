---
name: wechat-publisher
description: |
  微信公众号文章自动创作与发布工具。给定参考文章、文字或文档,自动搜索整理全网相关信息,使用项目内置 generate_image 生图入口生成手绘风格配图,生成图文并茂的公众号文章,并发布到微信公众号草稿箱。特别强调反 AI 检测写作。

  触发场景(只要沾边就该使用本skill):
  - 用户提到"公众号"、"微信文章"、"推文"、"公号"、"发文"、"mp"等关键词
  - 用户要求写文章并发布到微信
  - 用户提供参考素材并希望生成公众号内容
  - 用户希望把文档/笔记转为微信公众号文章
  - 用户要求搜索某个话题并写成公众号文章
  - 用户提到"草稿箱"、"群发"等微信公众号相关操作
  - 用户要求写一篇适合在微信上传播的文章
---

# 微信公众号文章自动创作与发布

本 skill 实现从素材输入到公众号草稿箱的完整自动化流程。核心价值:用户只需提供一个话题或几篇参考资料,skill 自动完成搜索调研、撰写、生成配图、排版、AI 味自检、发布。

> **⚠️ 不要使用 `baoyu-post-to-wechat` skill。** 本 skill 是自研的完整发布管线,和 `baoyu-post-to-wechat` 功能有重合但行为不同(本 skill 带多账号 / 主题排版 / 反 AI 检测 gate)。如果 Claude 路由时同时看到两者,**明确选本 skill(`wechat-publisher`)**,不要调用 `baoyu-post-to-wechat`。

## 账号与人格

目前配置了 2 个账号(见 `wechat-publisher.yaml`):

| key | 公众号名 | 作者 | 主题 | 人格(voice) |
|---|---|---|---|---|
| `main`(默认) | 刷屏AI | **飞哥** | `refined-blue` | 热情、类比、北京口语、爱讲踩坑经历。面向 AI 产品 / 提示工程 / Agent / 个人生产力 |
| `tech` | 蒜是哪根葱 | **葱哥** | `minimal-mono` | 技术直男味、冷幽默、不用感叹号、爱命令行和 commit hash。面向工程实践 / SDK / CLI / 底层原理 |

**默认作者**:不指定 `--account` 时用 `main`(飞哥 + refined-blue)。使用 `--account tech` 时自动切到葱哥 + minimal-mono 主题。

写作时**必须按当前账号的 voice 字段改写语气**,不同账号写出来要有明显的风格差异 —— 这本身就是反 AI 检测的关键(平台会对每个号建立历史文风基线,突然风格统一化就是 AI 信号)。

---

## 前置条件检查

### 首次使用必须先配置

`wechat-publisher` 现在优先使用一个统一配置文件:

```bash
cp wechat-publisher.yaml.example wechat-publisher.yaml
```

真实配置文件名是 `wechat-publisher.yaml`,已被 `.gitignore` 忽略。这是唯一支持的配置文件。

#### 1) 统一配置文件位置

配置文件固定放在 skill 根目录:

1. `wechat-publisher/wechat-publisher.yaml`

代码证据在 `scripts/config.py`:
- `_find_unified_yaml()` 只查 skill 根目录
- `get_config()` 强制要求账号下必须有 `app_id` 和 `app_secret`
- `load_env()` 会从统一配置里的 `image_generation` / `integrations` 写入环境变量

最常见用法:

```yaml
default: main

accounts:
  main:
    name: "刷屏AI"
    app_id: "wx..."
    app_secret: "..."
    author: "飞哥"
    theme: "refined-blue"
    image_style: "hand-drawn-blue"
    newspic_image_style: "infographic-warm"

image_generation:
  generator: "baoyu-image-gen"
  gemini_proxy:
    base_url: "https://generativelanguage.googleapis.com"
    api_key: "AIza..."
    image_model: "gemini-3-pro-image-preview"

integrations:
  wechatsync_mcp_token: ""
```

#### 2) 生图后端选择

默认后端是 `baoyu-image-gen`,也就是项目内置 `scripts/baoyu_image_gen.ts`。如需使用 Web 登录版 Gemini,改统一配置:

```yaml
image_generation:
  generator: "baoyu-danger-gemini-web"
```

```bash
python3 scripts/generate_image.py --account main --prompt "A hand-drawn AI infographic" --image ./images/01.png
```

可选值:
- `baoyu-image-gen`:默认,支持 OpenAI Images 与 Gemini CLI / chat 代理,不依赖外部 baoyu skill
- `baoyu-danger-gemini-web`:Web 登录版 Gemini,使用本 skill 内置拷贝 `scripts/baoyu_danger_gemini_web/`,需要本机 Google/Gemini Web 登录 cookie

**第一步:确认账号配置**

如需新增账号,参照 `wechat-publisher.yaml.example`。

查看已配置账号:
```bash
python3 scripts/wechat_api.py list-accounts
```

**第二步:验证 API 连接**
```bash
cd <skill-path>/scripts && python3 -c "from wechat_api import get_access_token; print('OK:', get_access_token()[:10]+'...')"
```
- 报 `40164`:IP 白名单未配(`curl ifconfig.me` 拿公网 IP,去公众平台加白名单)
- 报 `40001`/`40002`:AppID 或 AppSecret 错

**第三步:依赖**
```bash
pip install requests pyyaml --break-system-packages 2>/dev/null || pip install requests pyyaml
```

---

## 完整工作流程(7 个阶段,第 7 阶段为可选)

与早期版本相比,多了**阶段 3.5(人味化改写)** 和 **阶段 5.5(AI 味 gate)** —— 这两步是反 AI 检测的核心。**阶段 7(多平台同步)** 默认不启用,显式传参才触发。

---

### 阶段一:理解需求与收集素材

目标:搞清楚用户到底要什么,同时采集**真人味原料**。

1. **分析用户输入**
   - 用户给了参考文章/文档:Read 工具读完,提取核心观点、写作风格、目标受众
   - 用户只给话题:快速确认"这篇发哪个号(main / tech)?是"我"口吻还是机构口吻?有没有个人亲历的细节可以加进去?"
   - **尽量问出用户能提供的具体细节**:具体人名、时间、金额、产品版本、场景、踩过的坑 —— 这些是反 AI 检测的最重要原料。

2. **识别目标账号**:根据话题自动选账号(AI 产品类 → main,技术工程类 → tech),并加载对应 voice。也可由用户显式指定。

3. **选择文章结构**:写作前先确定 `article_structure` 和 `opening_hook`。用户指定则照做;未指定时先按题材匹配,有多个候选就随机选一个;批量写多篇时避免连续两篇使用同一结构。

4. **产出**:写入 `mp-articles/<main|tech>/<YYYY-MM-DD>-<slug>/brief.md`,包含话题、目标账号、3-5 个关键词、用户提供的真实细节清单、`article_structure`、`opening_hook`。

---

### 阶段二:全网信息搜索与整理

目标:既要权威数据,也要**真人语料**(反 AI 检测的第二重原料)。

1. **权威层**(WebSearch):
   - 最新资讯 + 数据(优先 6 个月内)
   - 相关案例 / 故事
   - 专家观点 / 官方报告 / Release Notes

2. **真人层**(**重要**):专门搜"真人讨论"作为语料库,让文章自然带上真人句式:
   - Reddit / HackerNews / V2EX / 即刻 / 少数派的帖子原话
   - X (Twitter) 上当事人 / 员工的发言原文
   - 小红书 / 知乎的一线用户吐槽
   - 产品具体的 commit message / issue 讨论

3. **信息筛选与交叉验证**:关键数据多源交叉,具体到数字 / 名字 / 时间 / 产品版本号。

4. **产出**:`mp-articles/<main|tech>/<slug>/research.md`,每个素材标来源,区分"权威层"和"真人层"。

---

### 阶段三:撰写骨架稿(第一轮)

目标:按结构写出初稿。**允许这一稿有 AI 味**,下一阶段专门负责"人味化"。

#### 结构选择规则与结构库(概览)

- 不要每篇都用"我遇到一件事"式故事开场;用户指定 `article_structure` / `opening_hook` 就照做,否则按题材匹配、多候选随机、连发时避开上一篇用过的结构,选定后写入 `brief.md`
- `article_structure` 共 8 种:data-first / question-led / contrarian / teardown / field-notes / timeline-news / playbook / case-file
- `opening_hook` 共 7 种:hard-number / sharp-question / contradiction / quote-first / artifact-first / timeline-first / scene-first
- 完整选择规则、每种结构的适合题材与正文推进、每种钩子的写法与避免项,详见 [references/article-structures.md](references/article-structures.md)

#### 默认骨架(Markdown)

> Markdown 中的第一个 `# 标题` 会被 html_converter 自动跳过(微信顶部已显示标题,不重复)。

```markdown
# 标题(抓眼球,15-25 字)

> 摘要引言(1-2 句话,会显示在分享卡片中)

## 开篇
(按选定的 opening_hook 切入,3-5 行抓住注意力。
可以是具体数字 / 尖锐问题 / 反常识判断 / 原话 / 命令输出 / 时间线 / 具体场景。
禁止"随着 XX 的飞速发展"这类宏观铺垫。)

![开篇配图描述](placeholder)

## 小节一:xxx

## 小节二:xxx

## 小节三:xxx

(可选更多)

## 写在最后
```

#### 文章规模(柔性指南,不要机械)

- **小节数量:3-6 个**,按话题决定,**不要强行凑对称**。有的小节 1000 字,有的 200 字都可以 —— 真人写作就是这样不均匀。
- **配图数量:6-10 张**,每个小节至少 1 张。所有配图统一使用手绘蓝色信息图风格(见阶段四)。
- **总字数目标:2500-5000 字**,有话则长无话则短。

#### 写作风格(按账号 voice 区分)

**main(飞哥 / 刷屏AI)**:热情,类比多,偶尔北京口语("这事儿"、"说实话"),可以写踩坑经历但不要每篇都用故事开头,情绪有起伏,可以用破折号和感叹号。**彻底禁用"我跟你讲""我跟你说"这类对读者喊话的口头语。**

**tech(葱哥 / 蒜是哪根葱)**:冷,偏吐槽,**不用感叹号**,爱用命令行片段、版本号、commit hash,文末常带一个反问或小段 rant("这破玩意""讲真""其实挺简单的"风格)。

无论哪个号,都要遵守 **阶段 3.5 的反 AI 检测清单**(下一节)。

#### 排版增强标记(行内标色)

骨架稿阶段就要**主动混用**多种行内标记,让段内文字有丰富的颜色变化。整篇只用一种 `**加粗**` 是最典型的 AI 公众号指纹。

| 标记 | 效果 | 什么时候用 |
|---|---|---|
| `**文本**` | 主加粗(深色 + 黄下划线) | 最重要的一句结论,一段最多 1 次 |
| `==文本==` | 黄色背景高亮 | 关键数据 / 核心论点 / 名言 |
| `++文本++` | 蓝色背景高亮 | 概念定义 / 工具名 / 平台名 |
| `%%文本%%` | 粉色背景高亮 | 警示 / 陷阱 / 反面案例 |
| `&&文本&&` | 绿色背景高亮 | 正面结果 / 推荐做法 |
| `!!文本!!` | 红色强调(不加背景) | 警告 / 反对 / 关键负面数字 |
| `@@文本@@` | 蓝色强调(不加背景) | 术语 / 专有名词 / 产品名 |
| `^^文本^^` | 橙色强调 | 温暖点缀 / 小惊喜 |
| `> ...` | 引用块 | 金句、关键数据、一段独立有力的话 |
| `===` 或 `[SEC]` 单独一行 | 分节符(主题自带字符,如 `● ● ●` / `— — —` / `§ § §`) | 大段之间的呼吸符 |

**密度建议**:每 500 字出现 **3-5 处** 行内标记,分散在不同段落,**至少混用 4 种不同的标记类型**。禁止整篇只有 `**加粗**` 一种。

#### 要避免的"AI 味"写法

- 不用"首先...其次...再次...最后..."这种教科书枚举
- 不用"值得一提的是"、"不可否认"、"毋庸置疑"、"综上所述"、"总而言之"、"由此可见"、"众所周知"
- 不用"一方面...另一方面..."、"不仅...而且..."
- 不用"在...的背景下"、"随着...的发展"、"站在...的角度"
- 不用过于工整的排比句
- 文末不做全面的"总结回顾"

---

### 阶段 3.5:人味化改写 pass(反 AI 检测核心)

这是整个流程最关键的一步,必须作为独立 pass 执行,不能和阶段三混在一起。

Claude 自己扮演"反 AI 检测审校"的角色,对骨架稿做 **9 条强制清单** 检查,逐项改写。

#### 反 AI 检测强制清单(概览)

9 条强制项:① Burstiness(句长抖动) ② 句式多样性禁用词清单 ③ AI 高频词黑名单 ④ 开头破冰规则 ⑤ 人称和立场 ⑥ 事实密度 ⑦ 标点多样性 ⑧ 结构的"不完美" ⑨ 按账号 voice 再过滤。

每条的具体阈值、完整禁用词表和改写示例,改写时**必须逐条对照** [references/anti-ai-checklist.md](references/anti-ai-checklist.md),不能只看本概览。

#### 执行方式

Claude 明确说:"现在进入人味化改写 pass"。对骨架稿**逐段**过一遍,每段输出"原文 → 改写"对照,确保覆盖了上面 9 条。可以直接在 `article.md` 文件中原地改。

---

### 阶段四:生成配图

**通过可选的 `image_style` 配图风格库控制视觉**。默认 `hand-drawn-blue`(手绘蓝调),保持 skill 原有视觉指纹;需要其他感觉时可换风格。

#### 风格选择

1. 不指定 → 用账号的 `image_style`(`main` = `hand-drawn-blue`,`tech` = `marker-lime`)→ 兜底 `hand-drawn-blue`
2. 单篇覆盖:article frontmatter 加 `image_style: <name>`,或 CLI `--image-style <name>`
3. 可用风格列表:
   ```bash
   python3 scripts/wechat_api.py list-image-styles
   ```

#### 风格详表与手绘水彩信息图系列(概览)

- 文章内联默认 `hand-drawn-blue`;`marker-lime`(+pink/sky/coral/violet)适合刷体大字金句卡;另有 `illustrated-warm` / `xiaohongshu-colorful` / `magazine-editorial` / `knowledge-card` / `data-chart` / `meme-illustration`
- **`infographic-warm/blue/dark/mint`** 手绘水彩信息图系列(v4):高密度中文信息图 + 手绘水彩墨线,9:16 竖版,**贴图模式默认**(warm)
- 要点里有具体数字 / 对比 / 多层信息 → 用 `infographic-*`;单一观点或金句、大字留白 → 用 `marker-*`
- 全部风格的适用场景、卡面密度、共享视觉原则与选择判据,详见 [references/image-styles-guide.md](references/image-styles-guide.md)
- 每种风格的预览图、完整 prompt 模板、适用场景见 [`assets/image-styles/README.md`](assets/image-styles/README.md)

#### 排版卡(typeset-card)—— 代码渲染的排版海报卡(手绘之外的第二条路)

`generate_image` 的手绘水彩会把中文和数字糊掉。**只要图里有必须一字不差的文字**(新闻 changelog、数据、
金句原文、@handle、对比),或题材偏严肃(讣告、争议、反网暴),就改走排版卡:手写 HTML/CSS → 无头
Chrome 2× 截图,文字精确、能上品牌色。四套配色:`ink`(挽联)/ `signal`(广播)/ `terminal`(终端新闻)/ `versus`(对比)。

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=2 \
  --window-size=1080,1350 --screenshot=out.png "file:///abs/card.html"
python3 scripts/image_handler.py upload out.png   # 拿 CDN URL;封面走 publish.py --cover
```

起手式 `assets/typeset-card/template.html`;完整设计系统 + 坑(**渲染后必看,溢出会静默裁掉来源行**)见
[`references/typeset-card.md`](references/typeset-card.md)。适合封面、newspic 金句 / 新闻首卡、需要精确数据的文内图。

#### 配图数量

**优先使用项目内置 `scripts/generate_image.py` 生成**。一篇完整文章 6-10 张配图,每个小节至少 1 张。

#### 配图类型(按内容选)

- 概念解释图
- 流程 / 架构图
- 对比图(before/after、A vs B)
- 数据可视化(趋势、占比、排名)
- 场景示意图
- 总结提炼图

#### 生图 prompt

读你要用的风格 JSON,拿出 `prompt_template.article_inline`,用它作模板生图。示例:

```bash
# 读 hand-drawn-blue 风格的 article 模板
cat assets/image-styles/hand-drawn-blue.json | python3 -c "
import json, sys
s = json.load(sys.stdin)
print(s['prompt_template']['article_inline'])
"
```

替换 `{image_subject}` 占位符为你这张图的具体主题,喂给项目内置 `scripts/generate_image.py`。

**禁忌**(和默认风格有冲突时以所选风格为准):
- 不要混用风格 —— 一篇文章所有配图统一一种风格
- 不要用写实照片、3D 渲染(除非明确选了 `meme-illustration` 等允许卡通的风格)

#### 下载 + 上传

```bash
python3 scripts/image_handler.py upload /path/to/generated_image.png
```

把返回的微信 CDN URL 替换 Markdown 中对应的 placeholder。

#### 封面图

从已生成的图里挑一张最有视觉冲击力的,或用同一 prompt 模板单独生成。推荐尺寸 **900×383**(2.35:1)。

---

### 阶段五:格式转换与排版

**为什么需要特殊转换**:微信公众号编辑器不支持外部 CSS / JS、不支持 class、所有样式必须内联。

#### 执行转换

```bash
python3 scripts/html_converter.py article_processed.md \
  --theme <theme-name> \
  -o article.html
```

**主题一般不用手动指定** —— 后面 `publish.py` 会根据 `--account` 自动从 `wechat-publisher.yaml` 里读 theme 字段。但如果你想预览某个主题:
```bash
python3 scripts/html_converter.py article.md --list-themes
python3 scripts/html_converter.py article.md --theme refined-blue -o preview.html
```

对比全部主题的可视化预览:打开 `assets/theme-previews/index.html`,15 套主题用同一篇文章渲染在手机宽度 frame 里并排对比。

#### 主题说明(共 15 套 · v2026)

- main 默认 `refined-blue`(蓝调极简),tech 默认 `minimal-mono`(极简黑白等宽);不确定就用 `refined-blue`
- 15 套按文章气质覆盖:AI 深度分析 / 技术工程 / 新闻热点 / 人文随笔 / 生活 / 时尚等类别
- 按类别的推荐主题表与 15 套逐条视觉简介,详见 [references/themes.md](references/themes.md)

**通过主题名选择**:在 `wechat-publisher.yaml` 里修改对应账号的 `theme:` 字段即可切换。例如把 main 账号换到 `sunset-coral`:

```yaml
accounts:
  main:
    theme: "sunset-coral"    # 默认 refined-blue
```

#### 行内标色系统

排版系统支持 7 种行内标色(见阶段三的标记表),转换器会把自定义标记替换为内联 style:

- `**加粗**`:主强调,深色 + 黄色下划线
- `==黄==` / `++蓝++` / `%%粉%%` / `&&绿&&`:4 种背景高亮
- `!!红!!` / `@@蓝@@` / `^^橙^^`:3 种字体强调色

实际主题文件在 `assets/themes/*.json`,内部结构:`styles`(标签样式)+ `highlights`(行内标色)+ `section_divider_text`(分节符字符)+ `list_style`(序号 / 项目符号样式)。

#### 自定义

要改配色 / 字号 / 间距,编辑 `assets/themes/<theme>.json`,修改 `styles` 或 `highlights` 字段。
要改有序列表的序号样式(如阿拉伯数字 / 中文 / 罗马数字 / 圆圈数字),改 `list_style.num_formatter`(可选 `decimal` / `padded` / `chinese` / `roman_upper` / `roman_lower` / `circled` / `circled_filled`)。

---

### 阶段 5.5:AI 味自检 gate(publish.py 自动拦截)

**这一步已经是 publish.py 内置的强制 gate**:`publish.py` 在调用草稿接口之前会自动调用 `ai_score.check_ai_score()`,分数 ≥ 阈值(默认 45)直接拦住,不会发草稿。

#### publish.py 的自动 gate

```bash
# 默认阈值 45
python3 scripts/publish.py --account main --input article.md --cover cover.jpg --title "..."

# 自定义阈值(更严)
python3 scripts/publish.py ... --ai-score-threshold 35

# 极少数情况下强制绕过(需要人工已审校确认)
python3 scripts/publish.py ... --skip-ai-score
```

#### 写作过程中手动检查

写作时还是推荐显式跑一次 `ai_score.py` 看细节报告:

```bash
python3 scripts/ai_score.py mp-articles/<main|tech>/<slug>/article.md --threshold 45
```

输出示例:
```
 AI 味检测报告  —— 🟢 PASS (真人味)
总分: 28.3 / 100
  [burstiness  ] 分数=45.0  权重=30%
  [phrases     ] 分数=15.0  权重=30%
  [vocab       ] 分数=10.0  权重=20%
  [structural  ] 分数= 0.0  权重=10%
  [punctuation ] 分数=30.0  权重=10%
```

#### 阈值约定

- **< 35**:🟢 PASS,可以发
- **35-45**:🟡 WARN,能发但建议再改一轮
- **≥ 45**:🔴 FAIL,`publish.py` 会拒绝发送,**必须回到阶段 3.5 重写命中的段落**

#### 脚本命中时怎么做

`ai_score.py` 会列出具体命中的 AI 套话和 AI 高频词。Claude 应该:
1. 读取脚本输出里的 "命中 X 次 AI 套话" 列表
2. 对每一条命中,在文章里定位那个句子,**重写**(不只是替换词,而是换整个句式)
3. 对 vocab 命中,替换成更具体 / 更口语的表达(比如"赋能" → "让 xxx 变得能做 yyy")
4. 重跑 `ai_score.py`,直到通过

#### 可选:外部第三方检测

作为双保险,建议在发布前手动打开:
- 朱雀 AI 检测:https://matrix.tencent.com/ai-detect/
- GPTZero:https://gptzero.me/
- 百度 AI 检测

任一平台给出 >70% AI 概率的段落,必须重写。

---

### 阶段六:发布到草稿箱

目标:上传到微信公众号草稿箱(不会自动群发)。

**一键发布**(推荐):
```bash
python3 scripts/publish.py \
  --account <main|tech> \
  --input mp-articles/<main|tech>/<slug>/article.md \
  --cover mp-articles/<main|tech>/<slug>/cover.jpg \
  --title "文章标题" \
  --digest "120 字以内摘要"
```

`publish.py` 会自动:
1. 从 `wechat-publisher.yaml` 读取对应账号的 `author` 和 `theme`
2. 按 theme 加载对应主题排版
3. 处理图片 → HTML 转换 → 封面上传 → 创建草稿
4. 返回 `media_id`

**不需要手动传 `--theme` 或 `--author`** —— 账号配置会自动带入。

**已有排版好的 HTML**:
```bash
python3 scripts/publish.py --account tech --html article.html --cover cover.jpg --title "标题"
```

**发布成功后告知用户**:
- 草稿已保存,请登录 mp.weixin.qq.com 查看草稿箱并手动确认发布
- 文章不会自动群发

---

### 阶段七:多平台同步(可选,opt-in)

**目的**:把发到微信草稿箱的同一篇文章,一键同步到知乎、掘金、CSDN、头条等平台(各平台也存为草稿)。

**默认不启用** —— 只有显式传参才触发,微信发布流程完全不受影响。同步失败也不影响已经创建好的微信草稿。

- 底层基于 Wechatsync Chrome 扩展 + `@wechatsync/cli`,复用各平台已登录 Cookie,需一次性安装配置
- 触发方式:`publish.py --sync zhihu,juejin,csdn` / `--sync-from-config` / `multi_publish.py` 独立跑
- 同步走原始 markdown(微信 CDN 图有防盗链,其他平台加载不出);失败不回滚微信草稿,各平台均为草稿态,需用户登录二次确认

一次性安装步骤、三种触发方式的完整命令、图片注意事项与失败处理,详见 [references/multi-platform-sync.md](references/multi-platform-sync.md)。

---

### 发布到今日头条(`--platform toutiao`)

**和阶段七的多平台同步不是一回事** —— 头条是本 skill 原生实现的一等发布目标,
可以脱离微信单独发,不依赖任何浏览器扩展。

```bash
# 只发头条
python3 scripts/publish.py --input article.md --platform toutiao

# 一次发两边(微信 + 头条)
python3 scripts/publish.py --input article.md --platform wechat,toutiao --cover cover.jpg

# 独立入口(等价,参数更少)
python3 scripts/toutiao_publish.py --input article.md
python3 scripts/toutiao_publish.py --check        # 只检查登录态
```

**首次使用需要扫码一次**:会弹出一个独立 profile 的 Chrome 窗口,扫码后登录态长期保存在
`integrations.toutiao.profile_dir`,之后可无人值守。

工作方式:启一个带独立 profile 的 Chrome,用 CDP 在页面上下文里调头条的内部接口。
之所以必须过浏览器,是因为头条的发布接口强制 `msToken`/`a_bogus` 签名,由页面内的
风控 SDK 劫持 `window.fetch` 现算 —— 实测未签名请求返回 `7050 保存失败`。
CDP 的 `Runtime.evaluate` 默认就在 MAIN world,因此能白嫖签名,不需要浏览器扩展。

几条必须知道的平台约束:

- **头条会丢弃所有内联样式**,只保留结构标签。所以头条走 `toutiao_render.py` 单独渲染,
  不复用微信那套主题排版 —— 微信的渐变高亮、自定义列表圆点在头条一律失效
- **`<a>` 会被吃掉**,正文链接一律降级成纯文本
- **`##` 和 `###` 都会被头条归一成同一级标题**,层级差别在头条不体现
- **图片必须先传到头条 CDN**,正文里出现外链图片会被拒(`7115 图片uri非法`);
  本 skill 已自动处理,每张图会在头条侧再传一遍
- **标题限 2~30 字**,超长直接报错中止,不静默截断
- 只进草稿箱(`save=0`),不直接发布;不支持贴图(newspic)和 `--html` 模式

接口细节、调研过程与踩过的坑,详见 [references/toutiao-publish-research.md](references/toutiao-publish-research.md)。

---

## 贴图模式(newspic / 图片消息,与文章模式并列)

和上面 7 阶段的"图文"(news)流程**并列**的第二种发布形态。对标微信公众号的"图片消息":5-10 张图的**卡片墙** + 一段 100-300 字的**短描述**,适合拆卡式讲解 / 金句观点串 / 图片清单等"文字偏少、靠图主导"的内容。

- 默认风格:高密度手绘水彩信息图,账号 `newspic_image_style` → 兜底 `infographic-warm`,**不需要在 brief.md 里写 `image_style`**
- 4 步流程:`brief.md → newspic_build.py 拆卡 → scripts/generate_image.py 批量生图 → publish.py --type newspic`
- 短文本必须过精简版 AI 味 gate(phrases + vocab + punctuation,`ai_score.py --mode newspic`)
- 限制:最多 20 张图(建议 5-10);不支持多平台同步和行内标色;每张图占永久素材名额

brief.md 字段说明、何时用贴图 vs 图文的判据表、完整 4 步流程与限制,详见 [references/newspic-mode.md](references/newspic-mode.md)。

---

## 文件组织约定

**重要:所有生成的文件必须直接放在项目目录内,不要放在 `~/.claude/` 下。**

`~/.claude/` 是 Claude Code 的敏感目录,即使开了 bypass permissions,写入该目录也会弹确认框。直接写到项目路径可以避免这个问题,同时"工作目录"和"归档目录"合二为一,少一步搬运。

所有生成的文件(包括中间产物和最终归档)都放在:

**图文(news)布局**:
```
mp-articles/<main|tech>/<YYYY-MM-DD>-<slug>/
  ├── brief.md            # 阶段一的需求摘要
  ├── research.md         # 阶段二的搜索素材
  ├── article.md          # 阶段三/3.5 的文章(最终发布源)
  ├── article.html        # 阶段五转换的 HTML(临时)
  ├── images/             # 所有生成的配图
  ├── cover.jpg           # 封面图
  └── ai_score.json       # 阶段 5.5 的检测报告
```

**贴图(newspic)布局**:
```
mp-articles/<main|tech>/<YYYY-MM-DD>-<slug>/
  ├── brief.md            # 话题 + 要点 + 短文本(发布源)
  ├── card_plan.json      # newspic_build.py 产出的每张卡的 prompt + 目标文件名
  └── images/
      ├── 01.png          # 按顺序编号,01 = 封面
      ├── 02.png
      └── ...
```

- `<main|tech>` 按目标账号选:`main` 账号 → `main/` 文件夹,`tech` 账号 → `tech/` 文件夹
- `<YYYY-MM-DD>-<slug>` 格式:日期 + 短横线 + 语义化 slug(纯小写英文短横线分隔)
- 各阶段的命令和路径都要相应调整,例如:
  ```bash
  python3 scripts/ai_score.py mp-articles/main/<slug>/article.md --threshold 45
  python3 scripts/publish.py --account main \
    --input mp-articles/main/<slug>/article.md \
    --cover mp-articles/main/<slug>/cover.jpg \
    --title "..."
  ```

**历史遗留**:如果看到 `~/.claude/skills/wechat-publisher/generated/` 下还有老文件,可以整体 `mv` 到项目路径下对应的 `main/` 或 `tech/` 文件夹,然后清空 `generated/`。新文章不要再往 `generated/` 写。

**不要**把 `article.md` / `article.html` 写到 wechat-publisher 根目录(那些是临时产物,不应污染 skill 目录)。

---

## 脚本说明

| 脚本 | 用途 |
|---|---|
| `publish.py` | 完整发布流程(一键,含 AI 味 gate)。支持 `--type news\|newspic` 双模式 |
| `generate_image.py` | **统一生图入口** —— 根据 `wechat-publisher.yaml` 选择 `baoyu-image-gen` 或 `baoyu-danger-gemini-web` |
| `newspic_build.py` | **贴图拆卡器** —— brief.md → card_plan.json(Claude 再按 prompt 生图) |
| `wechat_api.py` | **facade** —— 重导出下述模块 + 提供 CLI |
| `config.py` | (内部)`wechat-publisher.yaml` + 配图风格加载 + `set_account` / `get_config` / `resolve_image_style` |
| `wechat_token.py` | (内部)`get_access_token`,本地文件缓存 |
| `api.py` | (内部)图片上传(3 种:封面 / 正文 / newspic 素材)/ 草稿 / 发布 |
| `html_converter.py` | Markdown → 微信 HTML(多主题 + 行内标色) |
| `image_handler.py` | 图片下载 / 上传 / 替换 |
| `ai_score.py` | **反 AI 检测自检**,支持 `--mode news\|newspic` 两种检测策略 |
| `multi_publish.py` | **多平台同步**(阶段七,基于 @wechatsync/cli,默认不启用) |
| `toutiao_publish.py` | **发布到今日头条**(`--platform toutiao`),入口 + CLI |
| `toutiao_render.py` | Markdown → 头条裸 HTML(无内联样式,头条会全部清洗) |
| `toutiao_cdp.ts` | (内部)头条浏览器侧命令:upload / publish / check |
| `toutiao_cdp_client.ts` | (内部)CDP 传输层:WebSocket + Chrome 启动 + 登录态 |

老代码中的 `from wechat_api import ...` 保持可用 —— `wechat_api.py` 现在只是 facade,把 `config.py` / `wechat_token.py` / `api.py` 的公共 API 重新导出。CLI `python3 scripts/wechat_api.py ...` 也继续工作。

## 错误处理

| 错误 | 原因 | 解决 |
|---|---|---|
| `ConfigError` | `wechat-publisher.yaml` 缺失或账号不存在 / 字段不全 | 检查文件是否存在、default 字段、app_id/app_secret |
| `40164 IP 不在白名单` | 机器 IP 未加白名单 | `curl ifconfig.me` 取 IP → 公众平台加白名单 |
| `40001 access_token 无效` | token 过期或凭证错 | 检查 `wechat-publisher.yaml` 的 app_id/app_secret |
| `40009 图片大小超限` | 图片超 10MB | 压缩或换图 |
| `48001 接口未授权` | 公众号类型不支持 | 需要已认证的服务号 / 订阅号 |
| `ai_score.py` 返回 FAIL | AI 味太重 | 按命中清单重写段落;或 `--skip-ai-score` 临时绕过 |

## 注意事项

- 文章始终发布到**草稿箱**,不自动群发
- 默认 `main` 账号(飞哥),`tech` 账号用 `--account tech` 切换
- 两个账号的 voice 和 theme 差异是反 AI 检测策略的一部分,**不要让两个号的写作风格趋同**
- access_token 有效期 2 小时,脚本自动管理
- 微信 API 频率限制:每日 100 次素材上传
- 正文图片通过 `uploadimg` 接口上传,不占永久素材名额
- 如无封面图,使用文章第一张配图作为封面
- 所有配图统一使用项目内置 `scripts/generate_image.py` 生成的手绘蓝色信息图(不混用实拍图)
- **不要调用 `baoyu-post-to-wechat` skill**,一律用本 skill 的 publish.py
