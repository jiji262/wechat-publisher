# 贴图模式(newspic / 图片消息)完整流程

和 7 阶段"图文"(news)流程**并列**的第二种发布形态。对标微信公众号的"图片消息":5-10 张图的**卡片墙** + 一段 100-300 字的**短描述**,适合:

- 单一主题的"拆卡"式讲解(示例:[Claude Code /rewind](https://mp.weixin.qq.com/s/erEF74HRGkrBPxTGsKDsSQ))
- 信息点串(一卡一个具体信息点:数字、步骤、命令、对比)
- 图片清单 / 作品合集
- 任何"文字偏少、靠图主导"的内容

### 贴图默认就是高密度手绘信息图

**不需要在 brief.md 里写 `image_style`**,贴图模式的默认兜底是 `infographic-warm`。默认要求是:

- **高密度中文信息图**,不是普通插画、不是大字海报
- **手绘水彩 + 墨线**,不是 flat vector、不是 3D
- 9:16 竖版,每张卡都要承载足够信息
- 配色、布局、设计组件和画面元素按主题自适应,不要固定成同一套版式
- 机器人、小男孩、终端条、2×2 网格、胶囊标签等都是可选元素,只在内容合适时使用

想换整体氛围就在 brief.md 写 `image_style: infographic-blue` / `infographic-dark` / `infographic-mint`(见 [`assets/image-styles/README.md`](../assets/image-styles/README.md))。即使用这些风格,也只是给一个视觉方向,不是强制固定布局。

**账号级别**:`wechat-publisher.yaml` 里每个账号可以配 `newspic_image_style`,与文章模式的 `image_style` 分开(因为文章线条手绘和贴图水彩信息图是两种完全不同的视觉语言)。当前默认:
- main 账号 → `newspic_image_style: infographic-warm`(参考图同款)
- tech 账号 → `newspic_image_style: infographic-blue`(冷蓝变体)

### 何时用贴图,何时用图文

| 判据 | 图文(news) | 贴图(newspic) |
|---|---|---|
| 正文字数 | 2500-5000 字 | 100-300 字短描述 |
| 图数 | 6-10 张内联 | 5-10 张卡片墙 |
| 主载体 | 文字 | 图片 |
| 结构 | 按信息分节 | 拆卡,一卡一要点 |
| 适合 | 深度观察 / 教程长文 | 信息点串 / 技巧卡 / 清单 |
| AI 味检查 | 完整打分 + advisory + humanize_log 覆盖检查 | 短文本按 newspic 权重打分;标题 + 要点 + 短文本跑 advisory(只打印) |

### 4 步流程

```
brief.md → newspic_build.py 拆卡 → `scripts/generate_image.py` 批量生图 → publish.py --type newspic
```

#### 1. 写 brief.md

下面是**格式示例**(带完整注释的版本见仓库根的 `brief.md.example`):尖括号里是占位说明,内容必须来自真实素材,不要照抄说明文字的措辞。说明只写在 front matter 的 `#` 注释里,`# 要点` 和 `# 短文本` 两节的内容会被画进卡片或原样发布。

```markdown
---
topic: "<贴图的核心主题>"
image_style: infographic-warm  # 可选,不写用账号 newspic_image_style,再兜底 infographic-warm
card_count: 4                  # 可选,不写按要点数
title: "<写具体对象或事实的标题>"
account: main
---

# 要点

1. <一个功能或事实 + 一个数字、命令或版本号>
2. <一个操作步骤:在哪里做什么,做完看到什么>
3. <一个具体的限制或坑:什么条件下会出什么问题>
4. <一个可核对的对比:A 与 B 在某个指标上的差别,带来源>

# 短文本

```

**frontmatter 字段**:
- `topic`(必填):整个贴图的核心主题,用于给 Claude 提供语境
- `image_style`(可选):配图风格。不填就走 **账号 `newspic_image_style` → 全局 `infographic-warm`** 兜底。贴图模式默认就是高密度手绘水彩信息图,正常情况下这行留空。
- `card_count`(可选):卡片数量,不填按要点数,必须 ≤ 要点数,≤ 20
- `title`(可选):贴图标题,不填也行
- `account`(可选):发到哪个账号

**正文**至少要有 `# 要点` 小节,每行一条要点;`# 短文本` 可选,整节原样作为短描述发布,只放要发布的 100-300 字(不填就留空,让 Claude 根据要点写)。

**要点和短文本的写法**:一卡一个具体信息点(数字 / 步骤 / 命令 / 对比),不写格言,不为了压到 20 字以内把事实压缩成口号。卡面文字会被画进图片,生成后改不了,所以要点和短文本都要先过 `references/anti-ai-checklist.md` 的 A 层(否定对照、价值宣告、格言收束、三连排比等在卡面上同样是问题)。`newspic_build.py` 会对每条要点跑 lint,命中写进 `card_plan.json` 每张卡的 `warnings`,生图前先处理。lint 只稳定覆盖否定对照和价值宣告;格言收束和功能性标签(写在最后、记住这 N 件事这类)它不报,生图前逐条人工核对。

#### 2. 拆卡 + 生成计划

```bash
python3 scripts/newspic_build.py brief.md
# → 同目录写出 card_plan.json,列出每张卡的主副文字 + 完整 Gemini prompt + 目标文件名
```

生图前先看 `card_plan.json` 每张卡的 `warnings`(`newspic_build.py` 控制台也会提示),有命中先改要点、重跑拆卡,再生图。

Claude 读 `card_plan.json`,按每张卡的 `prompt` 字段调项目内置 `scripts/generate_image.py` 生图,保存到 `brief.md` 同目录的 `images/01.png`、`02.png` ...

#### 3. 写 / 检验短文本

如果 `brief.md` 的 `# 短文本` 还是空的,Claude 根据要点写一段 100-300 字,填回去。

**短文本要过 AI 味检查**:短文本按 newspic 权重打分(不计 burstiness / structural,具体权重以 `scripts/ai_score.py` 的 `WEIGHTS_NEWSPIC` 为准);标题、要点和短文本都跑 advisory lint:

```bash
# publish.py 会自动在发送前跑一次,这里是手动预检
# brief 里的 title 自动读出,按零容忍位置检查(含同形字硬门,和 publish 一致);要点逐条按零容忍位置检查
python3 scripts/ai_score.py brief.md --newspic-brief --advisory
```

分数超阈值 → 改短文本。advisory 是主要依据:逐条按改稿清单的 D 层顺序处理(先看这句在干什么:套路换成具体的,纯复述才删),分数低不代表没问题。

#### 4. 发布

```bash
python3 scripts/publish.py --account main --type newspic --brief brief.md
# 或显式覆盖风格
python3 scripts/publish.py --account main --type newspic --brief brief.md --image-style knowledge-card
```

`publish.py` 做的事:
1. 从 brief.md 读 frontmatter + 短文本
2. 跑 AI 味 gate(短文本按 newspic 模式打分,超阈值就停);标题含同形字直接拒发;标题、要点、短文本的 advisory 只打印,不阻断
3. 扫 `brief.md 同目录/images/*.{png,jpg,jpeg,webp}`,按文件名排序作为展示顺序
4. 逐张上传为微信永久素材(每张占一个永久素材名额,5000 上限)
5. 调 `draft/add` 建 newspic 草稿

⚠️ **永久素材成本提醒**:贴图每张都走 `add_material`,5-10 张贴图每次发布占 5-10 个永久素材名额。文章模式的正文图走 `uploadimg` 不占名额,但**封面图**和**贴图图片**都要占。

### newspic 的限制

- 微信最多 20 张图,建议 5-10 张,低于 2 张会警告
- 不支持多平台同步(`--sync` / `--sync-from-config`)
- 不支持行内标色、HTML 主题 —— 短文本只是一段纯文本
- 选了 `marker-*` 大字卡风格时:卡面字数超过 20 字会影响阅读,但卡面优先放事实,不要为了压字数把信息改写成格言
