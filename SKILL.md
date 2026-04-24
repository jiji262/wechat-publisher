---
name: wechat-publisher
description: |
  微信公众号文章自动创作与发布工具。给定参考文章、文字或文档,自动搜索整理全网相关信息,使用 baoyu-danger-gemini-web 生成手绘风格配图,生成图文并茂的公众号文章,并发布到微信公众号草稿箱。特别强调反 AI 检测写作。

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

目前配置了 2 个账号(见 `accounts.yaml`):

| key | 公众号名 | 作者 | 主题 | 人格(voice) |
|---|---|---|---|---|
| `main`(默认) | 刷屏AI | **飞哥** | `refined-blue` | 热情、类比、北京口语、爱讲踩坑经历。面向 AI 产品 / 提示工程 / Agent / 个人生产力 |
| `tech` | 蒜是哪根葱 | **葱哥** | `minimal-mono` | 技术直男味、冷幽默、不用感叹号、爱命令行和 commit hash。面向工程实践 / SDK / CLI / 底层原理 |

**默认作者**:不指定 `--account` 时用 `main`(飞哥 + refined-blue)。使用 `--account tech` 时自动切到葱哥 + minimal-mono 主题。

写作时**必须按当前账号的 voice 字段改写语气**,不同账号写出来要有明显的风格差异 —— 这本身就是反 AI 检测的关键(平台会对每个号建立历史文风基线,突然风格统一化就是 AI 信号)。

---

## 前置条件检查

**第一步:确认账号配置**

`accounts.yaml` 已预配置 `main` / `tech` 两个账号,直接使用。如需新增账号,参照 `accounts.yaml.example`。

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

3. **产出**:写入 `/Users/crimson/codes/0.docs/mp-articles/<main|tech>/<YYYY-MM-DD>-<slug>/brief.md`,包含话题、目标账号、3-5 个关键词、用户提供的真实细节清单。

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

4. **产出**:`/Users/crimson/codes/0.docs/mp-articles/<main|tech>/<slug>/research.md`,每个素材标来源,区分"权威层"和"真人层"。

---

### 阶段三:撰写骨架稿(第一轮)

目标:按结构写出初稿。**允许这一稿有 AI 味**,下一阶段专门负责"人味化"。

#### 文章结构模板(Markdown)

> Markdown 中的第一个 `# 标题` 会被 html_converter 自动跳过(微信顶部已显示标题,不重复)。

```markdown
# 标题(抓眼球,15-25 字)

> 摘要引言(1-2 句话,会显示在分享卡片中)

## 开篇
(用一个具体场景 / 具体数字 / 具体人物 / 具体对话切入,3-5 行抓住注意力。
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

**main(飞哥 / 刷屏AI)**:热情,类比多,偶尔北京口语("这事儿"、"说实话"、"我跟你讲"),爱用"我踩过的坑"开头,情绪有起伏,可以用破折号和感叹号。

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

#### 反 AI 检测强制清单(写完后逐条过)

**① Burstiness(句长抖动)**
- 相邻三句的字数差必须出现至少一次 **>15 字**。
- 每写 3-4 个长句,强制插入一个 **5-12 字的短句**。例如:"对。""我当时愣住了。""这事挺离谱。""先别急。"
- 禁止连续 4 句都是 25-40 字的"标准长句"。

**② 句式多样性 —— 禁用词清单**
在最终稿中全文搜索以下词,**命中 >1 次必须替换或删除**:
```
首先/其次/最后   不仅...而且   一方面...另一方面
值得一提的是     不可否认       毋庸置疑
综上所述         总而言之       由此可见
众所周知         不难发现       显而易见
在...的背景下    随着...的发展  站在...的角度
让我们一起来     归根结底       无论如何
```

**③ AI 高频词黑名单**
全文搜索以下词,**命中 >2 次必须替换**:
```
赋能 / 打造 / 聚焦 / 深度融合 / 生态 / 闭环 / 链路 / 抓手 /
价值链 / 护城河 / 方法论 / 底层逻辑 / 生态位 / 结构化思维 /
提升效率 / 助力 / 全链路 / 一站式 / 端到端 / 量变到质变 /
引领 / 颠覆 / 革命性 / 前所未有 / 核心竞争力 / 范式 /
降本增效 / 数字化转型 / 产业升级 / 破局 / 出圈 / 沉淀 /
深耕 / 蓝图 / 新篇章
```

**④ 开头破冰规则**
第一段**禁止**从宏观背景切入("近年来..."、"随着...的发展...")。改为:
- 一个具体场景("上周三下午 4 点,我正在...")
- 一个具体数字("我给一篇 5000 字的稿子配图花了 2 小时 47 分...")
- 一句具体的话("同事昨天跟我说:'你这个工具能开源吗?'")
- 一个具体的人物("OpenAI 的 Greg Brockman 在周六凌晨发了一条 tweet...")

**⑤ 人称和立场**
- 全文**必须**出现 ≥3 次第一人称("我")的主观表达,包含:个人经历 / 判断 / 失败 / 困惑。
- 允许不确定表达:"我可能说错了"、"我还没完全想明白"、"这只是我的感觉"、"存疑"。
- 禁止全程"全知冷静陈述"。

**⑥ 事实密度**
每 500 字内必须有 **≥1 个具体数字或专有名词**(时间 / 金额 / 版本号 / 人名 / 产品名 / 地名)。禁止"很多"、"大量"、"据说"、"相关研究表明"。

**⑦ 标点多样性**
全文必须出现:
- 破折号 `——` ≥1 次(用于插入语或强调)
- 问号 ≥2 次(包括设问句)
- 括号插入 `(...)` ≥1 次
- 省略号 `...` ≤3 次(多了也是 AI 味)
禁止整篇只有句号和逗号。

**⑧ 结构的"不完美"**
允许并鼓励:
- 在某一小节末尾补"扯远了,回到主题"
- 反悔句:"上面这点我收回,想了一下其实..."
- 自嘲:"写到这里我自己都怀疑我在扯淡"
- 小节长度明显不对称
这些是真人写作的天然痕迹,AI 默认不会产生。

**⑨ 按账号 voice 做语气再一次过滤**
按当前账号的 voice 字段,把句子整体语气再过一遍:
- main(飞哥):增加"我跟你讲"、"这事儿"、"说实话"等北京口语
- tech(葱哥):删除所有感叹号,增加"这破玩意"、"讲真"、"其实挺简单的"等冷吐槽

#### 执行方式

Claude 明确说:"现在进入人味化改写 pass"。对骨架稿**逐段**过一遍,每段输出"原文 → 改写"对照,确保覆盖了上面 9 条。可以直接在 `article.md` 文件中原地改。

---

### 阶段四:生成配图

**通过可选的 `image_style` 配图风格库控制视觉**。默认 `hand-drawn-blue`(手绘蓝调),保持 skill 原有视觉指纹;需要其他感觉时可换风格。

#### 风格选择

1. 不指定 → 用账号的 `image_style`(`main` = `hand-drawn-blue`,`tech` = `tech-card-blue`)→ 兜底 `hand-drawn-blue`
2. 单篇覆盖:article frontmatter 加 `image_style: <name>`,或 CLI `--image-style <name>`
3. 可用风格列表:
   ```bash
   python3 scripts/wechat_api.py list-image-styles
   ```

| 风格 | 最适合 |
|---|---|
| `hand-drawn-blue` | AI / 产品 / 工程类通用(默认) |
| `tech-card-blue` | 技术技巧 / 命令讲解 / 短观点 |
| `illustrated-warm` | 工具使用体验 / 讲故事 / 暖色指南 |
| `xiaohongshu-colorful` | 生活提示 / 清单 / 轻话题 |
| `quote-card-minimal` | 金句卡(只支持贴图模式) |
| `magazine-editorial` | 深度评论 / 专栏长文 |
| `knowledge-card` | 教程 / 方法论 / 复习卡 |
| `data-chart` | 数据观察 / 行业报告 / 对比 |
| `meme-illustration` | 吐槽 / 行业段子(慎用) |

每种风格的预览图、完整 prompt 模板、适用场景见 [`assets/image-styles/README.md`](assets/image-styles/README.md)。

#### 配图数量

**优先使用 `baoyu-danger-gemini-web` skill 生成**。一篇完整文章 6-10 张配图,每个小节至少 1 张。

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

替换 `{image_subject}` 占位符为你这张图的具体主题,喂给 `baoyu-danger-gemini-web`。

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

**主题一般不用手动指定** —— 后面 `publish.py` 会根据 `--account` 自动从 `accounts.yaml` 里读 theme 字段。但如果你想预览某个主题:
```bash
python3 scripts/html_converter.py article.md --list-themes
python3 scripts/html_converter.py article.md --theme refined-blue -o preview.html
```

对比全部主题的可视化预览:打开 `assets/theme-previews/index.html`,16 套主题用同一篇文章渲染在手机宽度 frame 里并排对比。

#### 主题说明(共 16 套 · v2026)

按文章气质分类挑选,不确定就用 main 默认的 `refined-blue`:

| 类别 | 推荐主题 |
|---|---|
| **AI / 产品 / 深度分析** | `refined-blue` **(main 默认)** · `business-navy` · `sage-premium` |
| **技术 / SDK / 工程** | `minimal-mono` **(tech 默认)** · `minimal-bw` · `academic-paper` · `cyber-neon` |
| **新闻 / 热点 / 速读** | `news-bold` · `warm-editorial` |
| **人文 / 随笔 / 文化** | `ink-wash` · `elegant-ink` · `magazine-grid` |
| **生活 / 美食 / 旅行** | `warm-orange` · `mint-fresh` · `sunset-coral` |
| **时尚 / 美妆 / 情感** | `girly-pink` · `sunset-coral` |

逐套视觉简介:

| 主题 | 视觉 | 默认绑定 |
|---|---|---|
| `refined-blue` | 蓝调极简 + 精致层次 / 数字标号 / 渐变高亮 | **main**(刷屏AI) |
| `minimal-mono` | 极简黑白 + 等宽字,工程师风 | **tech**(蒜是哪根葱) |
| `minimal-bw` | 瑞士现代主义 · Helvetica,只用粗细 / 留白做层级 | (可选) |
| `academic-paper` | 论文格式 + 衬线正字,章节编号式层级 | (可选) |
| `business-navy` | 深蓝 + 金色点缀,权威克制的金融感 | (可选) |
| `cyber-neon` | 深色底 + 霓虹青紫,赛博科技感 | (可选) |
| `news-bold` | 红黑强对比 + 快节奏,信息密度高 | (可选) |
| `warm-editorial` | 栗色暖调,衬线杂志风 | (可选) |
| `ink-wash` | 米黄纸 + 朱砂宋体,中式留白美学 | (可选) |
| `elegant-ink` | 墨黑 + 朱砂红,衬线现代宋体 | (可选) |
| `magazine-grid` | 衬线大标题 + 大留白,杂志内页感 | (可选) |
| `warm-orange` | 暖橙生活号,亲切日常感 | (可选) |
| `mint-fresh` | 薄荷绿 + 圆角卡片,轻盈透气 | (可选) |
| `sunset-coral` | 夕阳珊瑚,暖橙 + 奶白 | (可选) |
| `sage-premium` | 鼠尾草墨绿,克制专业 | (可选) |
| `girly-pink` | 粉紫渐变 + 可爱风,少女向 | (可选) |

**通过主题名选择**:在 `accounts.yaml` 里修改对应账号的 `theme:` 字段即可切换。例如把 main 账号换到 `sunset-coral`:

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
python3 scripts/ai_score.py /Users/crimson/codes/0.docs/mp-articles/<main|tech>/<slug>/article.md --threshold 45
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
  --input /Users/crimson/codes/0.docs/mp-articles/<main|tech>/<slug>/article.md \
  --cover /Users/crimson/codes/0.docs/mp-articles/<main|tech>/<slug>/cover.jpg \
  --title "文章标题" \
  --digest "120 字以内摘要"
```

`publish.py` 会自动:
1. 从 `accounts.yaml` 读取对应账号的 `author` 和 `theme`
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

#### 前置一次性安装

底层基于 [Wechatsync](https://github.com/wechatsync/Wechatsync),复用 Chrome 扩展里各平台已登录的 Cookie,不经过任何第三方服务器。

1. 装 Chrome 扩展「Wechatsync」,并分别登录知乎 / 掘金 / CSDN 等目标平台
2. 扩展设置里打开「MCP 连接」,生成一个 Token 拷出来
3. 装 CLI:
   ```bash
   npm install -g @wechatsync/cli
   ```
4. 在 `.env` 里加一行:
   ```
   WECHATSYNC_MCP_TOKEN=<第二步拷出的 Token>
   ```
5. 自检:
   ```bash
   python3 scripts/multi_publish.py --check
   ```
   两项都打 `✓` 说明就绪。

#### 触发方式

**方式 A:命令行显式指定平台(最常用)**
```bash
python3 scripts/publish.py --account main \
  --input /Users/crimson/codes/0.docs/mp-articles/main/<slug>/article.md \
  --cover /Users/crimson/codes/0.docs/mp-articles/main/<slug>/cover.jpg \
  --sync zhihu,juejin,csdn
```

**方式 B:从账号配置读默认平台列表**

先在 `accounts.yaml` 对应账号下加:
```yaml
accounts:
  main:
    ...
    sync_platforms: [zhihu, juejin]
```
然后发布时加 `--sync-from-config`:
```bash
python3 scripts/publish.py --account main --input x.md --cover x.jpg --sync-from-config
```

**方式 C:独立跑(不发微信,只同步)**
```bash
python3 scripts/multi_publish.py --input x.md --platforms zhihu,juejin
```

#### 图片注意事项

微信 CDN(`mmbiz.qpic.cn`)有严格防盗链,其他平台加载时会显示「此图片来自微信公众平台」占位图。
因此同步走的是**原始 markdown**(`article.md`),不是已处理过的版本。

- 外部 URL 图片(HTTPS):wechatsync 自动转存到各平台,通常没问题
- 本地路径图片(比如 `/Users/crimson/codes/0.docs/mp-articles/main/<slug>/images/fig1.png`):wechatsync 的文档未明确是否支持
  - `multi_publish.py` 会扫出并提示有多少张本地图
  - 如果目标平台发现图加载不出来,需要把本地图先传到公开图床(或任何无防盗链的 CDN)、改成 URL 后再跑同步

#### 失败处理

- 同步失败**不回滚**微信草稿(微信草稿已在阶段六成功创建)
- 告知用户:微信草稿 OK,但某平台同步失败 → 可以登录 Chrome 扩展手动重试
- 各平台同步后都是「草稿」状态,**不会**直接公开发布,需要用户登录各平台二次确认

---

## 贴图模式(newspic / 图片消息,与文章模式并列)

和上面 7 阶段的"图文"(news)流程**并列**的第二种发布形态。对标微信公众号的"图片消息":5-10 张图的**卡片墙** + 一段 100-300 字的**短描述**,适合:

- 单一主题的"拆卡"式讲解(示例:[Claude Code /rewind](https://mp.weixin.qq.com/s/erEF74HRGkrBPxTGsKDsSQ))
- 金句 / 观点串
- 图片清单 / 作品合集
- 任何"文字偏少、靠图主导"的内容

### 何时用贴图,何时用图文

| 判据 | 图文(news) | 贴图(newspic) |
|---|---|---|
| 正文字数 | 2500-5000 字 | 100-300 字短描述 |
| 图数 | 6-10 张内联 | 5-10 张卡片墙 |
| 主载体 | 文字 | 图片 |
| 结构 | 开篇/小节/结尾 | 拆卡,一卡一要点 |
| 适合 | 深度观察 / 教程长文 | 观点串 / 技巧卡 / 金句 |
| AI 味 gate | 完整 5 维 | 精简(phrases + vocab + punctuation) |

### 4 步流程

```
brief.md → newspic_build.py 拆卡 → baoyu-danger-gemini-web 批量生图 → publish.py --type newspic
```

#### 1. 写 brief.md

```markdown
---
topic: "Claude Code /rewind 命令"
image_style: tech-card-blue    # 可选,不写读账号默认
card_count: 6                  # 可选,不写按要点数
title: "Claude Code 里,最有用的命令之一"
account: main
---

# 要点

1. /rewind 厉害的地方不是"撤销一下",而是给你一个更对的工作流
2. 你可以输入 /rewind,也可以连续按两次 Esc,快速回滚代码
3. AI 解决不好问题,常常不是因为它不够会写,而是你不敢让它放手试
4. /rewind 的价值,就是把"试错"这件事真正变得可控

# 短文本

/rewind 厉害的地方,不是"撤销一下",而是给你一个更对的工作流:
先大胆尝试,再快速回退。
真正值得的不是它的撤销力,而是它给你的"敢试"。
```

**frontmatter 字段**:
- `topic`(必填):整个贴图的核心主题,用于给 Claude 提供语境
- `image_style`(可选):配图风格,优先级最低,会被 CLI `--image-style` 覆盖
- `card_count`(可选):卡片数量,不填按要点数,必须 ≤ 要点数,≤ 20
- `title`(可选):贴图标题,不填也行
- `account`(可选):发到哪个账号

**正文**至少要有 `# 要点` 小节,每行一条要点;`# 短文本` 可选(不填就让 Claude 根据要点写)。

#### 2. 拆卡 + 生成计划

```bash
python3 scripts/newspic_build.py brief.md
# → 同目录写出 card_plan.json,列出每张卡的主副文字 + 完整 Gemini prompt + 目标文件名
```

Claude 读 `card_plan.json`,按每张卡的 `prompt` 字段调 `baoyu-danger-gemini-web` 生图,保存到 `brief.md` 同目录的 `images/01.png`、`02.png` ...

#### 3. 写 / 检验短文本

如果 `brief.md` 的 `# 短文本` 还是空的,Claude 根据要点写一段 100-300 字,填回去。

**短文本必须通过 AI 味 gate**(newspic 模式权重:phrases 55% + vocab 35% + punctuation 10%,跳过 burstiness / structural):

```bash
# publish.py 会自动在发送前跑一次,这里是手动预检
python3 scripts/ai_score.py brief.md --mode newspic --threshold 45
```

命中 AI 套话或高频词 → 回去改短文本,重跑直到通过。

#### 4. 发布

```bash
python3 scripts/publish.py --account main --type newspic --brief brief.md
# 或显式覆盖风格
python3 scripts/publish.py --account main --type newspic --brief brief.md --image-style knowledge-card
```

`publish.py` 做的事:
1. 从 brief.md 读 frontmatter + 短文本
2. 跑 AI 味 gate(newspic 模式),不过就停
3. 扫 `brief.md 同目录/images/*.{png,jpg,jpeg,webp}`,按文件名排序作为展示顺序
4. 逐张上传为微信永久素材(每张占一个永久素材名额,5000 上限)
5. 调 `draft/add` 建 newspic 草稿

⚠️ **永久素材成本提醒**:贴图每张都走 `add_material`,5-10 张贴图每次发布占 5-10 个永久素材名额。文章模式的正文图走 `uploadimg` 不占名额,但**封面图**和**贴图图片**都要占。

### newspic 的限制

- 微信最多 20 张图,建议 5-10 张,低于 2 张会警告
- 不支持多平台同步(`--sync` / `--sync-from-config`)
- 不支持行内标色、HTML 主题 —— 短文本只是一段纯文本
- 不建议配 `quote-card-minimal` 以外的过重装饰 + 长句,**卡面字数超过 20 字会影响阅读**

---

## 文件组织约定

**重要:所有生成的文件必须直接放在项目目录内,不要放在 `~/.claude/` 下。**

`~/.claude/` 是 Claude Code 的敏感目录,即使开了 bypass permissions,写入该目录也会弹确认框。直接写到项目路径可以避免这个问题,同时"工作目录"和"归档目录"合二为一,少一步搬运。

所有生成的文件(包括中间产物和最终归档)都放在:

**图文(news)布局**:
```
/Users/crimson/codes/0.docs/mp-articles/<main|tech>/<YYYY-MM-DD>-<slug>/
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
/Users/crimson/codes/0.docs/mp-articles/<main|tech>/<YYYY-MM-DD>-<slug>/
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
  python3 scripts/ai_score.py /Users/crimson/codes/0.docs/mp-articles/main/<slug>/article.md --threshold 45
  python3 scripts/publish.py --account main \
    --input /Users/crimson/codes/0.docs/mp-articles/main/<slug>/article.md \
    --cover /Users/crimson/codes/0.docs/mp-articles/main/<slug>/cover.jpg \
    --title "..."
  ```

**历史遗留**:如果看到 `~/.claude/skills/wechat-publisher/generated/` 下还有老文件,可以整体 `mv` 到项目路径下对应的 `main/` 或 `tech/` 文件夹,然后清空 `generated/`。新文章不要再往 `generated/` 写。

**不要**把 `article.md` / `article.html` 写到 wechat-publisher 根目录(那些是临时产物,不应污染 skill 目录)。

---

## 脚本说明

| 脚本 | 用途 |
|---|---|
| `publish.py` | 完整发布流程(一键,含 AI 味 gate)。支持 `--type news\|newspic` 双模式 |
| `newspic_build.py` | **贴图拆卡器** —— brief.md → card_plan.json(Claude 再按 prompt 生图) |
| `wechat_api.py` | **facade(向后兼容)** —— 重导出下述模块 + 提供 CLI |
| `config.py` | (内部)`accounts.yaml` + 配图风格加载 + `set_account` / `get_config` / `resolve_image_style` |
| `wechat_token.py` | (内部)`get_access_token`,本地文件缓存 |
| `api.py` | (内部)图片上传(3 种:封面 / 正文 / newspic 素材)/ 草稿 / 发布 |
| `html_converter.py` | Markdown → 微信 HTML(多主题 + 行内标色) |
| `image_handler.py` | 图片下载 / 上传 / 替换 |
| `ai_score.py` | **反 AI 检测自检**,支持 `--mode news\|newspic` 两种检测策略 |
| `multi_publish.py` | **多平台同步**(阶段七,基于 @wechatsync/cli,默认不启用) |

老代码中的 `from wechat_api import ...` 保持可用 —— `wechat_api.py` 现在只是 facade,把 `config.py` / `wechat_token.py` / `api.py` 的公共 API 重新导出。CLI `python3 scripts/wechat_api.py ...` 也继续工作。

## 错误处理

| 错误 | 原因 | 解决 |
|---|---|---|
| `ConfigError` | `accounts.yaml` 缺失或账号不存在 / 字段不全 | 检查文件是否存在、default 字段、app_id/app_secret |
| `40164 IP 不在白名单` | 机器 IP 未加白名单 | `curl ifconfig.me` 取 IP → 公众平台加白名单 |
| `40001 access_token 无效` | token 过期或凭证错 | 检查 `accounts.yaml` 的 app_id/app_secret |
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
- 所有配图统一使用 `baoyu-danger-gemini-web` 生成的手绘蓝色信息图(不混用实拍图)
- **不要调用 `baoyu-post-to-wechat` skill**,一律用本 skill 的 publish.py
