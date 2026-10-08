---
name: wechat-publisher
description: |
  微信公众号文章自动创作与发布工具。给定参考文章、文字或文档,自动搜索整理全网相关信息,使用项目内置 generate_image 生图入口生成手绘风格配图,生成图文并茂的公众号文章,并发布到微信公众号草稿箱。特别强调去 AI 味(反 AI 味写作),读起来像本人写的。

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

> **⚠️ 不要使用 `baoyu-post-to-wechat` skill。** 本 skill 是自研的完整发布管线,和 `baoyu-post-to-wechat` 功能有重合但行为不同(本 skill 带多账号 / 主题排版 / 去 AI 味改稿流程与 gate)。如果 Claude 路由时同时看到两者,**明确选本 skill(`wechat-publisher`)**,不要调用 `baoyu-post-to-wechat`。

## 账号与人格

目前配置了 2 个账号(见 `wechat-publisher.yaml`):

| key | 公众号名 | 作者 | 主题 | 人格(voice) |
|---|---|---|---|---|
| `main`(默认) | 刷屏AI | **飞哥** | `refined-blue` | 热情来自具体判断和读者能用上的东西;类比只在难懂处用。面向 AI 产品 / 提示工程 / Agent / 个人生产力 |
| `tech` | 蒜是哪根葱 | **葱哥** | `minimal-mono` | 冷静,吐槽对准具体对象,不用感叹号。面向工程实践 / SDK / CLI / 底层原理 |

**默认作者**:不指定 `--account` 时用 `main`(飞哥 + refined-blue)。使用 `--account tech` 时自动切到葱哥 + minimal-mono 主题。

写作按当前账号 voice 的**取舍原则**来(见阶段三「写作风格」),两个号写出来要有明显差异。目标是读者读着像这个人写的,不是骗过检测器。

- **voice 优先级**:`wechat-publisher.yaml` 的 voice 字段只是描述;里面出现的口头禅、惯用语不是插入指令。冲突时以本文件和 `references/anti-ai-checklist.md` 为准。
- **声音锚点**:`assets/voices/<account>/samples.md` 存在且是用户本人写的文字时,以样本为准,本文件的 voice 描述作废。没有样本就是没有声音锚点,不要拿 `mp-articles/` 里的旧稿(Claude 写的)冒充样本;可以请用户提供几段本人写的文字。`mp-articles/<account>/edits.md`(用户通读时的改稿记录,见 3.5f)存在时,写稿前先读。

---

## 前置条件检查

### 首次使用必须先配置

`wechat-publisher` 现在优先使用一个统一配置文件:

```bash
cp wechat-publisher.yaml.example wechat-publisher.yaml
```

真实配置文件名是 `wechat-publisher.yaml`,已被 `.gitignore` 忽略。这是唯一支持的配置文件。

#### 1) 统一配置文件位置

固定放在 skill 根目录 `wechat-publisher/wechat-publisher.yaml`(`scripts/config.py` 只查这里;每个账号必须有 `app_id` 和 `app_secret`;`image_generation` / `integrations` 会写入环境变量)。

字段(`accounts.<key>` 的 app_id / app_secret / author / theme / image_style / newspic_image_style / voice,以及 `image_generation`、`integrations`)见 `wechat-publisher.yaml.example`。

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

与早期版本相比,多了**阶段 3.5(改稿 pass)** 和 **阶段 5.5(AI 味 gate)**。**阶段 7(多平台同步)** 默认不启用,显式传参才触发。

---

### 阶段一:理解需求与收集素材

目标:搞清楚用户要什么,拿到可核对的材料、用户确认的立场和用户本人的经历。

1. **分析用户输入**
   - 用户给了参考文章/文档:Read 工具读完,提取核心事实、立场、目标受众
   - 用户只给话题:确认发哪个号(main / tech)、"我"口吻还是机构口吻
   - **必须追问一次**:有没有用户亲身做过、可以写进文章的事(时间、动作、结果,以及用户自己说的当时反应)。用户本机跑出来的日志、截图、实测,对应的动作就是用户的亲历。问不出来就把 experiences 记为"无",并把 `scene-first`、`field-notes` 从候选里去掉。写稿的是 Claude,没有亲历,不许替用户补经历
   - 问清用户在这个话题上的全文立场 / 主张(stance);用户没有明确主张时,stance 写"无",正文不硬造全文立场
   - 定下 focus:这篇最想让读者带走的一件事,和作者最在意的一点(为什么在意)。写稿者可以根据 materials 提出,能问用户就请用户确认。focus 决定正文的轻重,没有 focus 的稿子会写成素材的逐条转述

2. **识别目标账号**:按话题自动选账号(AI 产品类 → main,技术工程类 → tech),也可由用户显式指定。

3. **选择文章结构**:先跑 `python3 scripts/fingerprint.py --account <main|tech> --last 3`,读出最近 3 篇的结构、开头、结尾、标题形状,写进 brief 的 `recent` 字段;再按 [references/article-structures.md](references/article-structures.md) 的规则选 `article_structure` / `opening_hook`,避开最近 3 篇的组合。

4. **产出**:写入 `mp-articles/<main|tech>/<YYYY-MM-DD>-<slug>/brief.md`(这个目录下文记作 `<dir>`)。字段固定为下面的 YAML front matter,这是 brief 格式的唯一真源(`ai_score.py --brief`、`fingerprint.py`、`fidelity_check.py` 都读它):

```yaml
---
topic: "<话题>"
account: main                 # main | tech
keywords: [<3-5 个关键词>]
article_structure: <结构库里的值>
opening_hook: <钩子库里的值>
recent: "<fingerprint 读出的最近 3 篇结构 / 开头 / 结尾>"
series: <可选,固定栏目名;不是栏目就删掉这行>
# series_ending 只在栏目有固定结尾时填,原样写;多段结尾写成列表一段一项,每段至少 6 个汉字。lint 不把它当金句或号召
series_ending: "<可选,栏目固定结尾原文>"
stance: "<用户确认过的全文立场 + 成立理由;没有写 无>"
focus: "<读者要带走的一件事;作者最在意的一点 + 理由>"
# experiences 只收用户亲口提供的经历,一条一行;没给写 - 无
experiences:
  - "<时间> | <动作> | <结果> | <用户说的当时反应,没有就省略这一栏>"
# materials 是可核对材料,一条一行,必须带来源
materials:
  - "<事实或数字> | <URL 或文件路径>"
---
```

   - 旧 brief 里的「一手真实细节」等同 `experiences`,「核心立场」等同 `stance`;改旧稿时先迁移到上面的字段
   - front matter 之后可以加一节 `## 结构规划`,每行写这一节讲哪条信息;大纲行同样不用功能性小标题(开篇 / 写在最后之类),不用否定对照句式。3.5a 带 `--brief` 跑 lint 时这些行也会被检查(清单里标 `brief`),命中就回 brief 改,并看正文对应小节有没有带出同样的写法
   - materials 撑不起计划篇幅时,继续调研、追问用户,或者把文章写短

---

### 阶段二:全网信息搜索与整理

目标:拿到可核对、带来源的材料。

1. **权威层**(WebSearch):最新资讯 + 数据(优先 6 个月内)、相关案例、官方报告 / Release Notes / 当事人原文

2. **真人层**:Reddit / HackerNews / V2EX / 即刻 / 少数派 / X / 知乎 / issue / commit 里的一线讨论。**只作为可以引用的材料**:原话 + 链接写进 research.md。不作为模仿句式的对象(会把别人的口头禅搬进来),也不写没有链接的转述。

3. **筛选与交叉验证**:关键数据多源交叉,具体到数字 / 名字 / 时间 / 版本号。

4. **产出**:`<dir>/research.md`(和 brief.md 同目录,fidelity_check 按这个位置找),每条素材标来源;把要用的材料同步进 brief 的 `materials`。

---

### 阶段三:撰写成稿

目标:根据 brief 的 stance、materials、experiences 和账号 voice,直接写出成稿。**写稿时不读 `references/anti-ai-checklist.md`**:禁令留到 3.5 再用,写稿时读会被换个说法写回稿子里。

#### 结构选择规则与结构库(概览)

- `article_structure` 共 8 种:data-first / question-led / contrarian / teardown / field-notes / timeline-news / playbook / case-file
- `opening_hook` 共 7 种:hard-number / sharp-question / contradiction / quote-first / artifact-first / timeline-first / scene-first
- 选择规则(含 fingerprint 去重、experiences 为"无"时的限制)、每种结构的可选要素、每种钩子的写法与避免项,见 [references/article-structures.md](references/article-structures.md)

#### 默认骨架(Markdown)

> Markdown 中的第一个 `# 标题` 会被 html_converter 自动跳过(微信顶部已显示标题,不重复)。

```markdown
# 标题(15-25 字;把最反常的那个事实或冲突放进去,让没读过正文的人想点开;不用情绪钩子词、否定对照、价值宣告)

> 摘要(1-2 句白话,写给没读过正文的人:出了什么事、后果是什么;少用术语,不堆数字;同样不用否定对照和三连加转折)

(第一段直接进正文,不加小标题)

## <这一节讲的具体内容>

……

(全文停在自然的停止点,不设结尾小标题)
```

- 不用功能性小标题(开篇、引言、导语、写在前面 / 最后、结语、总结、尾声这一类)
- 小标题宁少勿多;`timeline-news`、`field-notes` 可以不分节
- 不用序数小标题序列和数量模板;编号只留给真实的操作步骤
- 小标题里不放否定对照、价值宣告、替读者立靶;写数据式长小标题只是可选写法之一,不要每篇都用
- 标题和摘要也过 lint(`publish.py --title` / `--digest` 传入的同样检查),但机器只稳定抓否定对照、价值宣告和少数钩子词;三连加转折、冒号揭晓这类要在 3.5b 对照上面骨架里的标题、摘要要求人工看一遍,清单没列也要看
- **规模**:小节按话题决定,长短不均是正常的,不凑对称;配图跟信息点走,不为配图凑小节;总字数常见 2500-5000 字,材料撑不起就写短

#### 写作原则(只写原则,不给例句)

**作者在场**(正向要求,和禁令同样重要;去掉套路后稿子最容易滑成素材的逐条转述):
- 按 focus 定轻重:正文围绕读者要带走的那件事组织,顺序按读者想知道的走(出了什么事、为什么要在乎、怎么办),不按素材或官方文档的章节顺序转述;和 focus 关系不大的材料舍得不用
- 有态度:觉得一个设计好、一个数字吓人、一个做法别扭,就直接说出来,紧挨着写让你这么想的那个事实。表态放在它该在的地方,不是每段都要,也不固定挂在段尾;大部分段落让事实自己说话,表态的方式别全文一个样
- 有经过:experiences 里的动作用第一人称、按发生顺序讲,写清做了什么、看到了什么、为什么接着这么做;experiences 记了当时反应的可以写,没记的不补
- 讲给人听:把读者当成坐在对面的同行;读者大概率没见过、靠字面又看不懂的机制,用读者经历过的东西帮他理解,不是每处都要类比,同一篇里引出方式别重复;一节里连续摊开字段、定义、清单时,与本文重点无关的项不展开,展开的说清为什么

**读得下去**(手机上读):段落按一屏控制长度,一段讲一件事;数字成串、三个以上并列的对象就换成表格或列表;读者大概率不认识、后文又要用的术语,第一次出现时顺着句子说清是什么(不是每个都挂括号或「也就是」);能用中文说的不用英文。

**真实与克制**:
- 判断要有材料支撑,材料放在段内哪里不限
- 每段只做一件事;读者已经知道的不复述
- 动词靠前,少用话题壳和很长的前置定语
- 原文已有的具体数据不换成泛指;不编数字、引语、经历;比例、倍数、百分比这类派生数字用原始数字复算一遍再写
- 第一人称亲历只来自 brief.experiences;全文立场只来自 brief.stance。作者对局部的评价、取舍和比较(哪个设计好、哪一步容易卡住、适合谁)随时可以写,写清依据;材料不够时写清证据缺在哪,不硬下结论
- 真问句、普通比喻、两项并列、长句流水句、被动句、反复用同一专名,都可以放心用
- **开头**:按 brief.opening_hook 起,开头的事实出自 materials;不预告后文,不替读者设定错误认知;开头类型避开 fingerprint 里最近 3 篇
- **结尾**:停在任何自然的停止点,一句带理由的普通判断也可以;不用格言收束、回扣标题的呼应句、加粗结论段、行动号召模板;结尾类型避开最近几篇的重复

#### 写作风格(按账号 voice 区分,只写取舍原则)

**main(飞哥 / 刷屏AI)**
- 判断从哪来:从材料里的对比和后果来,它让谁省了哪一步、让谁多花了多少
- 热情靠什么体现:好恶直接说出来,紧跟着写是哪个设计或数字让你这么觉得;替读者挑出能直接拿去用的部分,写到能照着做。偶尔一句感叹可以有,不靠口头禅撑场
- 类比针对什么:这个号不少读者不写代码,机制绕的地方用读者自己做过的事帮他理解;喻体要贴切,同一个不反复用,引出方式别每次一样,不拿类比代替机制
- 口语感来自短动词和自然衔接;给建议用平常商量的语气,不对读者喊话

**tech(葱哥 / 蒜是哪根葱)**
- 判断从哪来:从能复现的东西来,报错原文、配置项、版本差异、源码或文档里的某个设计决定;好坏直接下判断,给出依据
- 冷感靠什么体现:靠精确,条件、版本、边界写清楚,不确定的地方直说不确定在哪;语气平,不用感叹号,不加渲染性的形容词
- 冷幽默从哪来:从反差来,用平淡的语气把一个荒诞的事实或数字摆出来,不解释笑点,不靠口头禅
- 吐槽针对什么:针对某条报错、某行配置、某个设计决定、文档和实际行为的出入,吐槽要带上原因或绕过办法;不针对人,不泛泛骂整个行业
- 命令、版本号、日志只在说明问题需要时出现,不当装饰;结尾形式不固定

两个号共用:不插口头禅和装坦诚的插入语,两个号的写法不要趋同。有真人样本时以样本为准(见「账号与人格」)。

#### 排版增强标记(行内标色)

行内标记只用来标可以检索的事实:数字、命令、产品名、版本号。标记跨度不超过一个名词短语,不含逗号、句号;不整句高亮,不加粗结论句,小标题里不用标记,同一段不堆多个。用多了会被 `style` 维度计分。

| 标记 | 效果 | 语义 |
|---|---|---|
| `**文本**` | 主加粗(深色 + 黄下划线) | 关键数字 / 名称(一处) |
| `==文本==` | 黄色背景高亮 | 关键数据 |
| `++文本++` | 蓝色背景高亮 | 概念名 / 工具名 / 平台名 |
| `%%文本%%` | 粉色背景高亮 | 易错的命令 / 配置项 / 报错原文 |
| `&&文本&&` | 绿色背景高亮 | 正向数字(提升、节省的量) |
| `!!文本!!` | 红色强调(不加背景) | 负面数字(下降、损失的量) |
| `@@文本@@` | 蓝色强调(不加背景) | 术语 / 专有名词 / 产品名 |
| `^^文本^^` | 橙色强调 | 次要数字 / 日期 |
| `> ...` | 引用块 | 不传 `--digest` 时,全文第一个 `>` 就是发布摘要:摘要写在 H1 下面,作者自己写(规则同骨架);正文里的 `>` 只放有出处的原话,并注明来源 |
| `===` 或 `[SEC]` 单独一行 | 分节符(主题自带字符,如 `● ● ●` / `— — —` / `§ § §`) | 大段之间的分隔 |

改稿规则见阶段 3.5,写稿时不读。

---

### 阶段 3.5:改稿 pass

成稿写完后作为独立 pass 执行,不和阶段三混在一起,也不逐段输出"原文 → 改写"对照(那会把全文级要求变成段级执行,形成新的规律)。现在才读 [references/anti-ai-checklist.md](references/anti-ai-checklist.md)(改稿清单:A 层规则表、B 层材料与亲历、C 层豁免、D 层改法与冷读模板)。

以下命令在 skill 根目录执行(`<dir>` 见阶段一)。每一步只有一条命令或一个动作。

**3.5a 快照 + lint**(先存初稿快照,之后只重跑第二条;lint 一条命令看全)

```bash
cp <dir>/article.md <dir>/article.draft.md
python3 scripts/ai_score.py <dir>/article.md --advisory --brief <dir>/brief.md --account <acct> \
  --save-lint --log-template
```

输出 advisory 清单(带行号;「整体减少这种写法」的是超量规则,按规则处理,其余逐条处理)、artifacts 命中、brief 结构规划行的命中;同目录写出 `ai_lint.json`,生成或补全 `humanize_log.md` 骨架。不传 `--digest` 时 lint 和 `publish.py` 取同一份摘要:全文第一个引用块,没有引用块就取正文前 120 字(会带上标题文字)。发布时传了 `--title` / `--digest`,或文章没有 H1,这里也传同样的值。

**3.5b 定点改**:按改稿清单 D 层的顺序(先看这句在干什么:套路句换成具体的判断或事实,纯复述才删,衔接、态度、类比、经过照留),不新增事实,不做同义替换,不整段重写。artifacts 直接改,不进 log;`position` 条目(含标题、摘要、小标题、图注)逐条改,确需保留就逐条写保留行(一行只覆盖一条命中,原文对得上)和理由,`unsourced_*` 的理由还要带可核对的出处;`density` 条目按规则处理,改到不再报出,或给这条规则写一行保留(原文填 `*`)。清单是下限:自己读到的同类动作同样处理。改完重跑 3.5a 的 lint 命令(不要再 cp)。log 填法见改稿清单 D 层。

**3.5c 冷读**:另开一个全新上下文、只读的 pass,只标不改,分两遍,prompt 模板在改稿清单 D 层:

1. 只给 `article.md` 和本文件阶段三「写作风格」里当前账号那段原文(有 samples.md 时附样本),问哪句话这个人不会在群聊里这样说、哪段读着像说明书。不用 `wechat-publisher.yaml` 的 voice 字段:用户改之前它不作数
2. 只给 `article.md` 和改稿清单 A 层(规则表加表下的读感项),逐段标命中

有 Agent 工具就开本地子代理(禁止 `isolation: "remote"`);没有(或 Agent 会继承当前对话)就另起一个独立的新会话,每遍只读 `article.md` 加该遍那一样输入(第 2 遍就是 `article.md` + A 层表);都做不到就请用户来读。标出的句子按 3.5b 处理。

**3.5d 保真**:逐条处理无出处的数字和引语、改写过度;报缩水时,按阶段三「作者在场」从材料里往回补态度、经过和对照,不是接着删。

```bash
python3 scripts/fidelity_check.py <dir>/article.draft.md <dir>/article.md --research <dir>/research.md --brief <dir>/brief.md
```

**3.5e 跨篇**:`python3 scripts/fingerprint.py <dir>/article.md --account <acct>`,标题、开头、结尾、小标题和最近几篇重复的就改。

**3.5f 用户通读**:请用户读一遍;用户改过的段落(原句 → 用户改法)追加到 `mp-articles/<acct>/edits.md`,阶段一和阶段三存在该文件就先读。

**退出条件**:重跑 lint 后 advisory 清零,或剩余每条都被 log 里的保留行覆盖(删 / 改过的条目重跑后自然消失)。用 `python3 scripts/ai_score.py <dir>/article.md --brief <dir>/brief.md --account <acct> --check-log` 离线核对,退出码 0 才算过;`publish.py` 发布前跑的是同一项检查(见阶段 5.5);冷读、fidelity_check、fingerprint、用户通读都不设门禁,跳过哪一步就在 `humanize_log.md` 末尾写明原因。

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

- 文章内联默认 `hand-drawn-blue`;`marker-lime`(+pink/sky/coral/violet)适合刷体大字单信息点卡;另有 `illustrated-warm` / `xiaohongshu-colorful` / `magazine-editorial` / `knowledge-card` / `data-chart` / `meme-illustration`
- **`infographic-warm/blue/dark/mint`** 手绘水彩信息图系列(v4):高密度中文信息图 + 手绘水彩墨线,9:16 竖版,**贴图模式默认**(warm)
- 要点里有具体数字 / 对比 / 多层信息 → 用 `infographic-*`;单一信息点、大字留白 → 用 `marker-*`(卡面放事实,不放格言)
- 全部风格的适用场景、卡面密度、共享视觉原则与选择判据,详见 [references/image-styles-guide.md](references/image-styles-guide.md)
- 每种风格的预览图、完整 prompt 模板、适用场景见 [`assets/image-styles/README.md`](assets/image-styles/README.md)

#### 排版卡(typeset-card)—— 代码渲染的排版海报卡(手绘之外的第二条路)

`generate_image` 的手绘水彩会把中文和数字糊掉。**只要图里有必须一字不差的文字**(新闻 changelog、数据、
带出处的原话、@handle、对比),或题材偏严肃(讣告、争议、反网暴),就改走排版卡:手写 HTML/CSS → 无头
Chrome 2× 截图,文字精确、能上品牌色。四套配色:`ink`(挽联)/ `signal`(广播)/ `terminal`(终端新闻)/ `versus`(对比)。

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=2 \
  --window-size=1080,1350 --screenshot=out.png "file:///abs/card.html"
python3 scripts/image_handler.py upload out.png   # 拿 CDN URL;封面走 publish.py --cover
```

起手式 `assets/typeset-card/template.html`;完整设计系统 + 坑(**渲染后必看,溢出会静默裁掉来源行**)见
[`references/typeset-card.md`](references/typeset-card.md)。适合封面、newspic 单信息点 / 新闻首卡、需要精确数据的文内图。

#### 配图数量与类型

**优先使用项目内置 `scripts/generate_image.py` 生成**。配图跟信息点走,不跟小节数量走。类型按内容选:概念解释、流程 / 架构、对比(before/after、A vs B)、数据可视化、场景示意。

#### 图注与图内文字(读者看得到,生成后改不了)

- **图注**:alt 文本会渲染成图片下方的图注,按零容忍位置 lint。写成描述画面的短语:画的是什么对象、哪两样在对比、数据来自哪里;不复述论点,不放否定对照、价值宣告和三项排比。`aphorism_end` 只在两种情况下报图注:带结论、总结、启示、教训、金句、N 个坑这类标签词;或者以句号 / 叹号结尾、同时带论断词(才是、本质、真正、永远这一类)。纯描述的图注带不带句号都不报
- **排版卡 / 封面图 / 生图 prompt 里要画进图的文字**:hero 放一条具体信息(数字、命令、产品名、对象名),不放格言、对仗、否定对照;kicker 写分类、日期、来源,不用功能性标签。渲染或生图前分两步查:① 把全部文字逐行写成 `## <这行文字>` 存进临时 `.md`(按小标题的零容忍口径查),跑 `python3 scripts/ai_score.py <tmp.md> --advisory --digest ""`,它只稳定覆盖否定对照和价值宣告(真正 / 最这类),写成单行的格言、金句它不报;② lint 抓不到的逐行人工核对:功能性 kicker(含用 `//`、`/` 分隔的写法)、数量模板、前后两半对称的对仗 hero、格言式或判断句式的 hero(靠才是、即是这类判断词撑起来的)。lint 没报不等于合规。详见 [references/typeset-card.md](references/typeset-card.md)

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

从已生成的图里挑一张信息最明确的,或用同一 prompt 模板 / 排版卡单独生成;图上的文字遵守上面的图内文字规则。推荐尺寸 **900×383**(2.35:1)。

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

转换器把阶段三标记表里的自定义标记替换为内联 style。主题文件在 `assets/themes/*.json`:`styles`(标签样式)+ `highlights`(行内标色)+ `section_divider_text`(分节符字符)+ `list_style`(序号 / 项目符号样式)。

#### 自定义

要改配色 / 字号 / 间距,编辑 `assets/themes/<theme>.json`,修改 `styles` 或 `highlights` 字段。
要改有序列表的序号样式(如阿拉伯数字 / 中文 / 罗马数字 / 圆圈数字),改 `list_style.num_formatter`(可选 `decimal` / `padded` / `chinese` / `roman_upper` / `roman_lower` / `circled` / `circled_filled`)。

---

### 阶段 5.5:AI 味 gate(publish.py 自动拦截)

`ai_score.py` 的定位是**负向模式 lint**:只能证明没踩已知的坑,不能证明像人。`publish.py` 在调用草稿接口之前自动做三道检查:

1. **总分**:`check_ai_score()` 总分 ≥ 阈值(默认 45)→ 拒发
2. **对抗字符**:同形字(长得像拉丁字母的西里尔 / 希腊字母紧挨汉字或混在英文词里,`hard_fail`)→ 拒发;零宽字符不拦,`publish.py` 在转换前自动清除(`--skip-ai-score` 时也清)并打印「已清除 N 个零宽字符」,`ai_score.py` 里记为 artifacts 的 `zero_width`;同形字在清掉零宽字符之后判定,夹零宽绕不过去
3. **humanize_log 覆盖检查**:advisory 非空时读文章目录的 `humanize_log.md`;没被保留行覆盖的条目、理由过短或只是占位、`unsourced_*` 的理由缺出处、保留行数超上限 → 列出并 exit 1

三道检查查的都是最终发布的标题和摘要:`--title` / `--digest` 传入的先清零宽再查;没传时标题取第一个 H1,没有 H1 就取正文第一行(不读 front matter 的 title),摘要按 3.5a 说的同一口径取。

```bash
python3 scripts/publish.py --account main --input article.md --cover cover.jpg --title "..." --digest "..."
python3 scripts/publish.py ... --ai-score-threshold 35   # 自定义阈值(更严)
python3 scripts/publish.py ... --skip-ai-score           # 跳过以上全部检查(零宽字符照常清除)
```

`--skip-ai-score` 只用于用户本人写的稿子:真人文本同样会命中这些规则,逐条写保留理由没有意义。Claude 写的稿子必须走完阶段 3.5 和这道门。

#### 手动检查

```bash
python3 scripts/ai_score.py <dir>/article.md --threshold 45
python3 scripts/ai_score.py <dir>/article.md --advisory --brief <dir>/brief.md --account <acct>
```

完整报告给出总分与 verdict、各维度分数和权重(以 `ai_score.py` 的 `WEIGHTS_NEWS` 为准)、artifacts 命中和 advisory 清单;`--advisory` 只打印 artifacts、advisory 和同形字硬门。人读的输出只显示"全文 N 处"。格式以实际输出为准。

#### 阈值约定(verdict 由阈值派生,默认 45 → 35 / 45)

- **< 阈值 − 10** 🟢 PASS(低分不等于没有 AI 味);**阈值 − 10 ~ 阈值** 🟡 WARN,建议再改一轮;**≥ 阈值** 🔴 FAIL,`publish.py` 拒发,回阶段 3.5 定点改

#### 脚本命中时怎么做

1. **advisory 是改稿的主要依据,总分只是下限检查。** 逐条按阶段 3.5b 处理,保留的写进 `humanize_log.md`
2. phrases / vocab 命中:重写整句,换成具体的动作或事实,不做同义替换
3. artifacts 命中(功能性小标题、指令回声、对读者喊话、破折号两侧空格、半角标点漂移、零宽等粘贴残留):确定性问题,直接改,不进 log
4. `hard_fail`:删掉同形字,通常是粘贴残留

分数第一次就低于阈值很常见,这不说明稿子没问题;不要为了压分数改稿。

#### 可选:第三方检测器

朱雀(https://matrix.tencent.com/ai-detect/)、GPTZero 等只作参考。各平台之间差异很大,规范的人类文本也会被误判,不因某个平台的百分比去重写;只改能指出具体句子和原因的地方。

---

### 阶段六:发布到草稿箱

目标:上传到微信公众号草稿箱(不会自动群发)。

**一键发布**(推荐):
```bash
python3 scripts/publish.py \
  --account <main|tech> \
  --input <dir>/article.md \
  --cover <dir>/cover.jpg \
  --title "文章标题" \
  --digest "120 字以内摘要"
```

`publish.py` 会自动:
1. 从 `wechat-publisher.yaml` 读取对应账号的 `author` 和 `theme`
2. 按 theme 加载对应主题排版
3. 处理图片 → HTML 转换 → 封面上传 → 创建草稿
4. 返回 `media_id`

**不需要手动传 `--theme` 或 `--author`** —— 账号配置会自动带入。

**`--html`(例外,不是常规方式)**:直接发已排版的 HTML,不过阶段 5.5 的 gate,运行时会打印警告。只用于 Markdown 已经走完阶段 3.5(lint 与 humanize_log 都已过)、之后只手工调过排版的 HTML;稿子一律用上面的 `--input` 发。

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

# 独立入口(等价,同样过阶段 5.5 的 gate)
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
- **标题限 2~30 字**,超长直接报错中止,不静默截断(这项校验在 AI 味 gate 之前)
- 只进草稿箱(`save=0`),不直接发布;不支持贴图(newspic)和 `--html` 模式

接口细节、调研过程与踩过的坑,详见 [references/toutiao-publish-research.md](references/toutiao-publish-research.md)。

---

## 贴图模式(newspic / 图片消息,与文章模式并列)

和上面 7 阶段的"图文"(news)流程**并列**的第二种发布形态。对标微信公众号的"图片消息":5-10 张图的**卡片墙** + 一段 100-300 字的**短描述**,适合拆卡式讲解 / 信息点串 / 图片清单等"文字偏少、靠图主导"的内容。

- 默认风格:高密度手绘水彩信息图,账号 `newspic_image_style` → 兜底 `infographic-warm`,**不需要在 brief.md 里写 `image_style`**
- 4 步流程:`brief.md → newspic_build.py 拆卡 → scripts/generate_image.py 批量生图 → publish.py --type newspic`
- 一卡一个具体信息点(数字 / 步骤 / 命令),不写格言;卡面文字画进图里后改不了,要点和短文本都按改稿清单 A 层处理。lint 不查格言收束和功能性标签(写在最后、记住这 N 件事这类),生图前逐条人工核对
- 预检:`newspic_build.py` 把要点的命中写进 `card_plan.json` 的 `warnings`,**生图前**先看,有命中先改要点;`python3 scripts/ai_score.py brief.md --newspic-brief --advisory` 检查 brief 的 title、要点和短文本(短文本按 newspic 权重打分;title 含同形字时和 publish 一样报硬门)
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
  ├── article.draft.md    # 3.5a 的初稿快照(fidelity_check 对照用)
  ├── article.md          # 改稿后的文章(最终发布源)
  ├── ai_lint.json        # 3.5a `--save-lint` 写出的规则命中计数 + advisory
  ├── humanize_log.md     # 3.5 逐条处理记录(publish.py 覆盖检查读它)
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
- 各阶段命令里的路径都要相应调整(见阶段 3.5 的 `<dir>` 约定)

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
| `ai_score.py` | **AI 味 lint + 打分**(负向模式,只能证明没踩已知的坑)。`--mode news\|newspic`;`--advisory` / `--brief` / `--account` / `--title` / `--digest` / `--log-template` / `--save-lint` / `--newspic-brief` |
| `zh_text.py` | (内部)中文文本工具:front matter、Markdown 遮罩、切句、文本单元(标题 / 摘要 / 小标题 / 图注) |
| `zh_tells.py` | (内部)advisory 规则与计分伪影;规则数据在 `zh_rules.py`,结构类 / 出处类检测在 `zh_finders.py` / `zh_sources.py`,字符层在 `zh_chars.py`,标记位置在 `zh_markers.py` |
| `source_check.py` | (内部)`unsourced_*` 保留理由的出处核对:亲历只认 brief 里对得上的那一行 |
| `article_meta.py` | (内部)标题 / 摘要提取,`publish.py` 与 `ai_score.py` 共用同一口径 |
| `humanize_log.py` | (内部)`humanize_log.md` 骨架生成与覆盖检查(publish.py 调用) |
| `fingerprint.py` | 跨篇指纹:同账号最近几篇的标题 / 开头 / 结尾 / 小标题 / 口头禅族重复。不给文章时只列历史特征;读不了的历史稿跳过并在注里警告 |
| `fidelity_check.py` | 初稿 vs 终稿保真核对:数字 / 引语 / 专名差异、无出处数字、改写过度、删得过多;显式指定的 research / brief 不存在时会提示 |
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
| 总分超限 / `ai_score.py` 返回 FAIL | 命中已知 AI 模式过多 | 回改稿 pass(阶段 3.5)定点改;humanize_log 的保留不抵总分;`--skip-ai-score` 只用于用户本人写的稿子 |
| 同形字硬门 | 正文 / 标题 / 摘要混进西里尔、希腊字母或康熙部首 | 换回正常字符,不能靠保留 |
| humanize_log 未覆盖 / 「保留」过多 | 条目没被保留行覆盖 / 理由过短、是占位或缺出处 / 保留超上限 | 按列出的条目改稿,或补保留行(填法见改稿清单 D 层) |
| 缺文章路径 | gate 找不到同目录的 humanize_log.md / brief.md | 带上 article.md 的路径重跑 |

## 注意事项

- 文章始终发布到**草稿箱**,不自动群发
- 默认 `main` 账号(飞哥),`tech` 账号用 `--account tech` 切换
- 两个号的写作取舍要保持差异,**不要趋同**;目标是读者读着像本人写的,不要为了检测器分数改稿
- access_token 有效期 2 小时,脚本自动管理
- 微信 API 频率限制:每日 100 次素材上传
- 正文图片通过 `uploadimg` 接口上传,不占永久素材名额
- 如无封面图,使用文章第一张配图作为封面
- 配图按账号 `image_style` 生成(手绘或排版卡),一篇内不混用风格,不用实拍图
- **不要调用 `baoyu-post-to-wechat` skill**,一律用本 skill 的 publish.py
