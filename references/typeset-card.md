# 排版卡 / typeset-card —— 代码渲染的排版海报卡

一套**手写 HTML/CSS → 无头 Chrome 截图**产出的图片风格,和本 skill 默认的 `generate_image.py`
生图(手绘水彩信息图 / infographic 系列)是**两条完全不同的路**。

**一句话**:排版卡不是"生成"的,是"排"出来的。核心优势是 AI 生图做不到的——**文字精确、可控、不糊**,
还能上品牌色、真实数字、@handle、logo 文字。

## 什么时候用排版卡(而不是 generate_image 手绘生图)

| 用排版卡 | 用 generate_image(手绘信息图) |
|---|---|
| 严肃 / 沉重题材(讣告、网暴、争议),手绘调性不对 | 轻松 / 生活 / 故事向、常规文章配图 |
| 信息要**精确**:新闻 changelog、数据、对比、带出处的原话、@handle、版本号 | 氛围 / 场景 / 有角色的信息图 |
| 要品牌色 / 官方视觉(OpenAI 黑、Claude 陶土橙) | 统一账号手绘水彩指纹 |
| 单信息点卡:一个事实或数字放大(封面或 newspic 首卡) | 文章内高密度多卡信息图 |

**判据**:图里有**必须一字不差**的文字(新闻、数据、引用、对比)就走排版卡;`generate_image` 的 gemini
会把中文和数字糊掉。

## 在 wechat-publisher 里怎么用

- **封面图**:排版卡做封面(尺寸 `1200×510` ≈ 2.35:1,或直接 4:5 竖版再裁),视觉冲击强、标题精确。
- **贴图(newspic)卡**:代替 / 混入手绘信息图,尤其"单信息点 / 新闻 / 对比"类首卡(`1080×1350` 或 `1080×1920`)。
- **文内插图**:需要精确数据 / 对比 / 引用的那一两张。
- 渲染出 PNG 后,和普通配图一样走 `scripts/image_handler.py upload <png>` 上传,拿 CDN URL 替换 placeholder;
  封面走 `publish.py --cover <png>`。

## 语法(每张卡的固定骨架)

- **画布**:写死 `html,body` 尺寸 + `overflow:hidden`。常用 `1080×1350`(4:5)/ `1080×1920`(9:16 贴图)/ `1200×510`(封面)。
- **结构**(上→下):kicker(等宽小标签)→ hero(大号标题,放事实或数字,只给一个词上强调色)→ body(要点行 / 卡片)→ footer / 来源(等宽暗色;**新闻类必须署来源 + @handle**)。
- **一个底色 + 一个强调色**,克制装饰,大留白。
- **字体**(macOS 自带):sans `"PingFang SC"` · serif `"Songti SC"`(庄重)· mono `"SF Mono","Menlo"`(kicker/footer)。

## 四套配色变体(按情绪选)

| 变体 | 底色 / 字体 / 强调 | 适合 |
|---|---|---|
| `ink` 挽联 | 墨黑渐变 · Songti · 暖白字 · 暗红强调 | 沉重 / 人文 / 讣告 / 反网暴 |
| `signal` 广播 | 深蓝渐变 · PingFang · 白字 · X 蓝 + 广播环 | 公告 / 号召 / 涨粉 |
| `terminal` 终端 | 近黑 + 淡网格 · PingFang+SF Mono · 一个强调色 · 带色标记的 changelog 行 | 产品新闻 / release note / 开发工具 |
| `versus` 对比 | 深底 · 两张品牌色卡叠 + 中间连接 pill | A vs B / 同日对比 / 双方并列 |

## 渲染(核心机制)

```bash
# 手写 card.html(html,body 尺寸 = 画布尺寸,overflow:hidden),然后:
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --disable-gpu --hide-scrollbars \
  --force-device-scale-factor=2 --window-size=1080,1350 \
  --screenshot=out.png "file:///abs/path/card.html"
# → 2160×2700 的 2× retina PNG,再 image_handler.py upload
```

(装了 bun 的话,new-x-skill 里有个 `scripts/render-card.ts` 封装了同一条命令,可直接拷来用。)

## 坑(都是踩过的)

- **必看渲染图再发**:内容超出画布会**静默裁掉 footer / 来源行**。修法:调小 padding / 字号,或把
  `margin-top:auto` 换成固定 margin(auto 会把元素顶到底,内容一高就溢出)。
- `html,body{width:Wpx;height:Hpx;overflow:hidden}` 必须和 `--window-size` **完全一致**。
- 中文换行:避免 `" / "`(带空格),会在斜杠处尴尬断行。
- **发前逐字核对文字**——排版卡的全部意义就在于文字精确、能被信任;新闻类还要先核实事实源。

## 卡面文字规则(渲染前检查,渲染后改不了)

- hero 放一条具体信息(数字、命令、产品名、对象名),不放格言、对仗句、否定对照、价值宣告。
- kicker 写分类、日期、来源这类标签,不用功能性标签(开篇 / 写在最后之类),不用数量模板。
- 文字和正文一样受改稿清单(`references/anti-ai-checklist.md` A 层)约束。渲染前分两步查:
  1. 把卡上全部文字(kicker / hero / body / footer)逐行写成 `## <这行文字>` 存进一个临时 `.md`(按小标题的零容忍口径查;写成普通段落会漏报),跑 `python3 scripts/ai_score.py <tmp.md> --advisory --digest ""`,命中就改。它只稳定覆盖否定对照和价值宣告(真正 / 最这类);写成单行的格言、金句它不报。
  2. lint 抓不到的逐行人工核对:功能性 kicker(包括用 `//`、`/` 分隔的写法)、数量模板、前后两半对称的对仗 hero、格言式或判断句式的 hero(靠才是、即是这类判断词撑起来的)。lint 没报不等于合规。
- 来源行写真实出处,没有出处的数据不上卡。

## 模板

`assets/typeset-card/template.html` 是带注释的通用起手式(terminal 变体)。复制它,改配色/结构/文字,
渲染即可。四套变体差异主要在 `body` 背景、字体栈、强调色这几个变量。
