# 配图风格库(image-styles)

本目录下的每个 `<style>.json` 定义一种配图风格。风格用于两处:

1. **文章模式**(`publish.py --input article.md`)—— 文章内联图的视觉风格
2. **贴图模式**(`publish.py --type newspic --brief brief.md`)—— 贴图卡片的视觉风格

所有预览图都用**同一个样例主题 "Claude Code /rewind 命令"** 渲染,方便你横向比较风格差异。

---

## 风格选择流程

1. 先看下面的**速查表**决定用哪一种风格
2. 预览图只是样例 —— 实际生成时会用你自己的内容
3. 在 `accounts.yaml` 的账号下配 `image_style: <name>`(全局默认)
4. 单篇要覆盖:`--image-style <name>`(CLI)或 brief.md frontmatter `image_style: <name>`

**优先级**:CLI `--image-style` > brief/article frontmatter `image_style` > `accounts.yaml` 账号默认 > `hand-drawn-blue`(全局兜底)。

---

## 风格速查表

| 风格 | 视觉关键词 | 最适合的话题 | 贴图 | 文章 |
|---|---|---|---|---|
| [`tech-card-blue`](#tech-card-blue) | 浅蓝底 + 大字 + 极简 | 技术技巧、命令讲解、短观点 | ✅ | ✅ |
| [`hand-drawn-blue`](#hand-drawn-blue) | 手绘线条 + 蓝点缀 | 概念解释、架构图、流程图(全能选手) | ✅ | ✅ 默认 |
| [`illustrated-warm`](#illustrated-warm) | 暖橙 + 卡通人物 + 气泡 | 体验讲解、使用指南、亲切感强的技巧 | ✅ | ✅ |
| [`xiaohongshu-colorful`](#xiaohongshu-colorful) | 暖色渐变 + emoji + 大字 | 生活提示、上手指南、清单类 | ✅ | ✅ |
| [`quote-card-minimal`](#quote-card-minimal) | 黑白 + 衬线 + 留白 | 金句、观点、哲思 | ✅ | ❌ |
| [`magazine-editorial`](#magazine-editorial) | 米色 + 衬线 + 栏位感 | 深度评论、专栏、长篇随笔 | ✅ | ✅ |
| [`knowledge-card`](#knowledge-card) | 白底 + 编号 + 结构化 | 教程、方法论、清单、复习卡 | ✅ | ✅ |
| [`data-chart`](#data-chart) | 白底 + 图表 + 数字 | 数据观察、行业报告、对比 | ✅ | ✅ |
| [`meme-illustration`](#meme-illustration) | 黄底 + 卡通 + 对话气泡 | 吐槽、段子、行业梗 | ✅ | ✅ |

---

## 风格详细说明

### tech-card-blue

浅蓝底 + 深蓝大字 + 极少装饰。**对标微信示例文章 [Claude Code /rewind](https://mp.weixin.qq.com/s/erEF74HRGkrBPxTGsKDsSQ)**。
每张卡一个观点或一条命令,字体占视觉主导,留白充足。

<table>
<tr><td width="300">
<img src="previews/tech-card-blue.webp" alt="tech-card-blue preview" />
</td><td>

- **主题色**:`#f4f7ff` 底 / `#2e5bff` 蓝 / `#0b1530` 墨
- **排版**:正方 1:1,思源黑体 Heavy
- **账号绑定**:`tech`(蒜是哪根葱)默认
- **最适合**:技术命令讲解、开发者 tips、短观点
- **别用在**:长文深度解析(信息密度不够)

</td></tr></table>

---

### hand-drawn-blue

手绘速写风 + 蓝色点缀 + 白底,像工程师的笔记本。擅长画流程、架构、对比、概念示意。
**main 号默认**,视觉一致度高,话题适配最广。

<table>
<tr><td width="300">
<img src="previews/hand-drawn-blue.webp" alt="hand-drawn-blue preview" />
</td><td>

- **主题色**:`#ffffff` 底 / `#4a6cf7` 蓝 / `#ff8c42` 橙
- **排版**:支持 1:1 贴图 / 16:9 文章,手写风字体
- **账号绑定**:`main`(刷屏AI)默认
- **最适合**:AI / 产品 / 工程话题的全能默认
- **别用在**:纯数据报告(换 `data-chart`)、纯金句(换 `quote-card-minimal`)

</td></tr></table>

---

### illustrated-warm

暖橙 / 桃色渐变底 + 卡通人物场景 + 大白气泡 + 手绘装饰。每张卡像一页小漫画,讲一个小故事。
**对标公众号示例文章 [Claude Code /rewind](https://mp.weixin.qq.com/s/erEF74HRGkrBPxTGsKDsSQ)**。视觉有温度、带情绪、有人物在场,适合"给你讲一件事"感觉的内容。

<table>
<tr><td width="300">
<img src="previews/illustrated-warm.webp" alt="illustrated-warm preview" />
</td><td>

- **主题色**:`#ffd9b3 → #ffa07a` 暖橙渐变 / `#4ecdc4` 青 / `#a78bfa` 紫 / `#fde047` 黄
- **排版**:3:4 竖图(贴图)/ 4:3(文章),粗圆体 + 手写感
- **账号绑定**:(main 号讲使用体验时首选)
- **最适合**:工具使用讲解、体验分享、故事卡、亲切感强的"指南"
- **别用在**:冷话题(数据、架构、协议),情绪不匹配时看着反而跳

</td></tr></table>

---

### xiaohongshu-colorful

暖色渐变背景 + emoji + 大字 + 黄色笔刷高亮,典型的小红书 / Instagram 封面感。
活泼、友好、转化率高。

<table>
<tr><td width="300">
<img src="previews/xiaohongshu-colorful.webp" alt="xiaohongshu-colorful preview" />
</td><td>

- **主题色**:`#ffecd2 → #fcb69f` 渐变 / `#ff6b6b` 红 / `#ffd93d` 黄
- **排版**:3:4 竖图(贴图)/ 16:9(文章)
- **账号绑定**:(可选,main 号做生活类时用)
- **最适合**:上手指南、清单盘点、生活提示、轻话题
- **别用在**:tech 号葱哥(冷幽默和彩色完全不搭)

</td></tr></table>

---

### quote-card-minimal

黑白极简 + 衬线大字 + 留白极致。一张卡一句金句,像美术馆墙上的引文。
**只推荐贴图模式**,文章内联用会太冷清。

<table>
<tr><td width="300">
<img src="previews/quote-card-minimal.webp" alt="quote-card-minimal preview" />
</td><td>

- **主题色**:`#f7f5f0` 米白 / `#1a1a1a` 墨黑 / `#8a8a8a` 灰
- **排版**:1:1,思源宋体 Heavy
- **账号绑定**:(tech 号葱哥最适合)
- **最适合**:观点金句、哲思、收尾页、单独一句话
- **别用在**:多信息卡(一张塞不下超过 15 字的会崩)

</td></tr></table>

---

### magazine-editorial

米色暖底 + 衬线大标题 + 栏位感 + 栗色点缀。像杂志内页,有温度也有距离感。
文章开头配一张,全文格调瞬间提一档。

<table>
<tr><td width="300">
<img src="previews/magazine-editorial.webp" alt="magazine-editorial preview" />
</td><td>

- **主题色**:`#f5efe6` 米色 / `#7a2e2e` 栗 / `#4a5d3a` 墨绿
- **排版**:4:5 竖图(贴图)/ 16:9(文章),思源宋体 Heavy
- **账号绑定**:(深度评论专栏用)
- **最适合**:深度观察、行业评论、文化思考、长篇随笔
- **搭配主题**:`sage-premium` / `warm-editorial` 效果最好

</td></tr></table>

---

### knowledge-card

白底 + 浅灰栅格 + 蓝色编号徽章 + 琥珀色小结。结构化学习卡的标准模板。
信息密度高,视觉识别度高,读者一眼就知道"这是要记的"。

<table>
<tr><td width="300">
<img src="previews/knowledge-card.webp" alt="knowledge-card preview" />
</td><td>

- **主题色**:`#ffffff` 底 / `#2563eb` 蓝 / `#f59e0b` 琥珀
- **排版**:3:4(贴图)/ 16:9(文章),思源黑体 Bold
- **账号绑定**:(工具教程、方法论类用)
- **最适合**:教程步骤、方法框架、清单、概念拆解
- **别用在**:情绪型内容、纯金句(两者都换 `quote-card-minimal`)

</td></tr></table>

---

### data-chart

白底 + 栅格 + 柱图 / 折线 / 饼图 + 等宽数字。FiveThirtyEight / Bloomberg 数据图美学。
**只有真实数字才用这个风格** —— 编数据会掉粉比 AI 味还严重。

<table>
<tr><td width="300">
<img src="previews/data-chart.webp" alt="data-chart preview" />
</td><td>

- **主题色**:`#fafbfc` 底 / `#0ea5e9` 蓝 / `#ef4444` 红 / `#10b981` 绿
- **排版**:1:1(贴图)/ 16:9(文章),JetBrains Mono 等宽数字
- **账号绑定**:(有数据的文章通用)
- **最适合**:趋势分析、榜单、行业报告、benchmark 对比
- **硬要求**:必须有真实可引用的数据源

</td></tr></table>

---

### meme-illustration

黄底 + 卡通人物 + 对话气泡 + 夸张表情。互联网 meme 风格,专治严肃。
**慎用**:meme 有保鲜期,过时的梗比没梗还尴尬。

<table>
<tr><td width="300">
<img src="previews/meme-illustration.webp" alt="meme-illustration preview" />
</td><td>

- **主题色**:`#fff9e6` 黄底 / `#ff5e5e` 红 / `#4ecdc4` 青 / `#2d2d2d` 黑线
- **排版**:1:1(贴图)/ 4:3(文章),粗黑体 + 手写风
- **账号绑定**:(tech 号文末吐槽)
- **最适合**:吐槽、行业段子、相亲相爱型梗、程序员幽默
- **别用在**:严肃观点、首图、跟客户 / 品牌合作的文章

</td></tr></table>

---

## 新增一种风格

1. 在 `assets/image-styles/` 下复制一个现有 `.json` 作模板
2. 改 `style_name`(文件名同步改)、`display_name`、`description`
3. 设计 `prompt_template.newspic_card` 和 `prompt_template.article_inline`(占位符:`{topic}` / `{card_main}` / `{card_sub}` / `{image_subject}`)
4. 用 `baoyu-danger-gemini-web` 按 `newspic_card` prompt 生成一张 1:1 预览图,然后 `cwebp -q 85 src.png -o previews/<style_name>.webp`(PNG 在 repo 里会占 10-20 倍空间)
5. 在本 README 加一行速查表 + 一个详细块
6. `python3 scripts/wechat_api.py list-image-styles` 验证能读出

---

## 调试

```bash
# 列出所有已注册风格
python3 scripts/wechat_api.py list-image-styles

# 看某个风格的完整 JSON
cat assets/image-styles/tech-card-blue.json | python3 -m json.tool

# 单独跑拆卡 + 出图计划(不实际生图)
python3 scripts/newspic_build.py brief.md --dry-run
```
