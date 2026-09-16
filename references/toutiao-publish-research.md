# 头条号（mp.toutiao.com）发文技术方案调研

> 调研日期：2026-09-16。所有标注「实测」的结论都是在真实登录的头条号后台亲手验证过的，
> 标注「来源」的是公开资料。两者区分开看 —— 头条接口变更频繁，实测结论也有保质期。

---

## 一、结论（先看这段）

| 路线 | 可行性 | 推荐度 |
|---|---|---|
| 官方开放平台 API | ❌ 不可行 | — |
| 纯 Python HTTP（导出 cookie 直接打接口） | ❌ 发布被拒（图片上传可以） | — |
| **CDP 直连 + 独立 profile，页面上下文调内部接口** | ✅ 实测端到端跑通 | ⭐ 首选 |
| 浏览器扩展（wechatsync 路线） | ✅ 可用 | 多一层依赖，且无封面 |
| 浏览器 UI 自动化（模拟粘贴 + 点按钮） | ✅ 可行 | 兜底 |
| 半自动（自动填充 + 人工点发布） | ✅ 可行 | 最稳，但不能无人值守 |

**一句话**：必须跑一个真实浏览器，但**不需要浏览器扩展**。用 CDP 启一个带独立 profile 的
Chrome，在页面上下文里直接 `fetch` 头条的内部接口 —— `Runtime.evaluate` 默认就在 MAIN world，
页面的风控 SDK 会自动帮你把请求签好名。见第八节（含可运行的 spike 验证记录）。

---

## 二、为什么官方 API 不行

1. **抖音开放平台的「头条内容发布」明确排除图文**
   原文：「仅支持小视频格式，暂不支持发布头条文章、微头条等」
   来源：https://open.douyin.com/platform/resource/docs/ability/content-management/toutiao-publish-solution

2. **唯一的官方图文通道是 RSS 内容源，且只对新闻媒体 / 国家机构开放**
   原文：「目前仅支持【新闻媒体、国家机构】类账号接入网站内容源」
   机制是平台定期来拉你的 RSS，不是你 push。
   来源：https://mp.toutiao.com/docs/baike/2789/20623/

个人号 / 普通企业号两条都拿不到。

---

## 三、为什么纯 HTTP 不行（这是本次最关键的发现）

### 实测过程

我在页面里直接 `fetch('/mp/agw/article/publish', {credentials:'include'})`，**成功**，返回 `{code:0, message:"保存成功"}`。
一度以为纯 cookie 就够了。但检查实际发出的 URL 后发现：

```
实际请求：/mp/agw/article/publish?source=mp&type=article&aid=1231
                                  &mp_publish_ab_val=0&msToken=...&a_bogus=...
                                                       ^^^^^^^^^^^^^^^^^^^^^^
                                                       我没写，是被自动加上的
```

原因：页面加载了字节的风控 SDK，它**劫持了 `window.fetch` 和 `XMLHttpRequest.prototype.open`**：

```js
window.fetch.toString().includes('[native code]')            // → false（已被改写）
XMLHttpRequest.prototype.open.toString().includes('[native code]')  // → false
// 劫持者：bdms.js / secsdk-lastest.umd.js / runtime-v1.0.0.js（lf-security.bytegoofy.com）
```

**所以"cookie 就够了"是假象** —— 任何在页面里发的请求都被 SDK 免费签好了名。
从 Python / curl 发同样的请求，缺 `a_bogus` 就会被拒。`a_bogus` 是 JSVMP 现算的，
要么补浏览器环境，要么还原虚拟机字节码，都不是能长期维护的东西。

### 旁证

Wechatsync（6.3k star，同类工具里最成熟的）在源码注释里写：

> content script 的 fetch 不会自动注入 msToken/a_bogus，需要通过 background 使用
> `chrome.scripting.executeScript` 在 MAIN world 执行

他们掌握全部接口细节，最后仍然选择挂一个真实 tab 借页面的签名能力。
来源：https://github.com/wechatsync/Wechatsync

### ⚠️ 关于 Wechatsync 的完整调查（本 skill 的 `--sync toutiao` 依赖它）

**结论：源码拿不到，但编译好的扩展仍然能用（且不带封面）。**

#### 源码：头条适配器已私有化

`packages/core/src/adapters/platforms/` 下公开 19 个适配器 ——
`zhihu / juejin / csdn / baijiahao / sohu / weibo / bilibili / cnblogs / oschina /
segmentfault / cto51 / douban / xueqiu / yuque / weixin / woshipm / imooc / eastmoney / zip-download`。
**头条不在其中**，它被移进了私有 submodule（commit `34d41ce`，2026-03-12）：

```
[submodule "private-adapters"]
	path = packages/core/src/adapters/platforms/private
	url = git@github.com:wechatsync/wechatsync-private-adapters.git   ← 私有仓库，不可访问
```

而且 `@wechatsync/core` / `@wechatsync/mcp-server` **都没发到 npm**，所以从源码自建也走不通。
（README 的支持表里仍写「头条号 | toutiao | ✅」，是过期信息。）

#### Fork：全部 1042 个都没有

v2 适配器 `packages/extension/src/adapters/toutiao.ts` 的存活窗口只有 **8 天**
（`2cf6027` 2026-01-07 建立 → `6750bf5` 2026-01-15 删除），窗口太短，没有任何 fork 抓到。

- 2026-01 之后的 fork（占绝大多数）：adapters 目录只有 `cms, index.ts`
- 2021 年的老 fork：有 v1 的 `packages/@wechatsync/drivers/src/toutiao.js`，
  但那套接口（`tools/catch_picture/` + `upload_picture`）**实测已死**（返回 `1053 无效图片数据`）

**但不需要 fork** —— 父仓库自己的 git 历史里就能取回完整的 346 行源码：

```bash
git clone --filter=blob:none https://github.com/wechatsync/Wechatsync.git /tmp/ws
cd /tmp/ws && git show 6750bf5^:packages/extension/src/adapters/toutiao.ts > /tmp/toutiao-adapter.ts
```

#### 编译产物：头条适配器还在 ✅

手动安装包 `wechatsync-2.0.9.zip`（2026-03-24 构建，README 里给的链接）解包后：

```
assets/index.ts-Bw-475TG.js   ← 含完整头条适配器
命中：agw/article/publish · spice/image · ttwid/check · pgc-img
      pgc_feed_covers · article_ad_type · world:"MAIN" · executeScript
表单字段 24 个，与本文 4.2 的最小字段集完全一致
```

**但封面是关掉的**：包里 `coverType:3`（无封面）硬编码，且搜不到
`20020003` / `need_cover_url` / `tplv-tt-cover` —— 即它不给头条传封面。

#### 三条路怎么选

| 路径 | 可用 | 代价 |
|---|---|---|
| 装 Chrome 扩展 2.0.9 + `@wechatsync/cli` | ✅ | 依赖第三方扩展常驻登录 + MCP Token；**无封面**；随时可能再次变更 |
| 从源码自建扩展 | ❌ | `@wechatsync/core` 未发 npm，头条适配器在私有仓库 |
| 拿历史源码当蓝本，自己实现 | ✅ | 要写代码，但可带封面、无外部依赖 |

源码与本文第四节的实测结论 **1:1 吻合**（同样的 endpoint、同样的 24 个字段、同样靠
MAIN world 拿签名），可以放心照着实现 —— 而且实测已经把它没做的封面打通了。

`@wechatsync/cli` 1.1.0 本身只是个 WebSocket 瘦客户端（包内 `toutiao` 命中数为 **0**），
真正干活的是扩展，所以 CLI 版本高低不影响头条能力。

---

## 四、接口蓝图（全部实测通过）

### 4.1 图片上传

```
POST https://mp.toutiao.com/spice/image
     ?upload_source=20020002&aid=1231&device_platform=web
Content-Type: multipart/form-data
字段名: image          ← 注意不是 upfile（那是已废弃的老接口）
credentials: include

→ { code: 0, data: {
      image_uri,        // 形如 tos-cn-i-6w9my0ksvp/<32位hex>，正文 img 的 web_uri 用它
      image_url,        // 带签名的 CDN 地址，正文 img 的 src 用它
      image_width, image_height, image_format, image_size,
      image_mime_type, image_type, origin_image_uri, origin_image_url } }
```

封面换参数：`?upload_source=20020003&aid=1231&device_platform=web&need_cover_url=1`

已废弃：`/mp/agw/article_material/photo/upload_picture`（实测返回 `1053 无效图片数据`）。

### 4.2 发布 / 存草稿

```
POST https://mp.toutiao.com/mp/agw/article/publish
     ?source=mp&type=article&aid=1231&mp_publish_ab_val=0
Content-Type: application/x-www-form-urlencoded
```

**实测可用的最小字段集**（照搬浏览器抓到的完整 payload 反而失败，见 4.4）：

```
pgc_id=0                    # 0=新建；传已有 id=更新该草稿
source=29                   # PC 编辑器来源标识
title=<标题，2~30 字>
content=<HTML 正文>
save=0                      # 0=存草稿，1=直接发布
search_creation_info={"searchTopOne":0,"abstract":"","clue_id":""}
title_id=<Date.now()>_<16位随机数>
mp_editor_stat={}
is_refute_rumor=0
timer_status=0
timer_time=
educluecard=
draft_form_data={"coverType":1}     # 1=单图封面，3=无封面
pgc_feed_covers=<JSON 数组，见下>
article_ad_type=3
is_fans_article=0
govern_forward=0
praise=0
disable_praise=0
tree_plan_article=0
activity_tag=0
trends_writing_tag=0
claim_exclusive=0
extra={"content_source":100000000402,"content_word_cnt":<正文长度>,
       "is_multi_title":0,"sub_titles":[],
       "gd_ext":{"entrance":"","from_page":"publisher_mp",
                 "enter_from":"PC","device_platform":"mp","is_message":0}}
```

`pgc_feed_covers`（单图封面）：

```json
[{"url":"<image_url>","uri":"<image_uri>","web_uri":"<image_uri>","ic_uri":"",
  "width":960,"height":540,"thumb_width":960,"thumb_height":540,"id":0,"pos":0}]
```

响应：`{code:0, err_no:0, message:"保存成功", data:{pgc_id, content, pgc_feed_covers}}`

草稿回链：`https://mp.toutiao.com/profile_v4/graphic/publish?pgc_id=<pgc_id>`

### 4.3 正文 HTML 的硬约束

**图片必须先上传，正文里不能出现外链图片。** 实测直接塞 `<img src="https://外站/x.jpg">`：

```
→ { code: 7115, message: "图片uri非法,请重新上传" }
```

正确的图片标记（`web_uri` / `img_width` / `img_height` 三个属性缺一不可）：

```html
<div class="pgc-img">
  <img src="<image_url>" class="" ic-uri="" image_type="image/jpeg" mime_type=""
       web_uri="<image_uri>" img_width="960" img_height="540">
  <p class="pgc-img-caption"></p>
</div>
```

**头条只保留结构标签，内联样式全部丢弃。** 实测存入后回读，保留下来的标签：

```
P  DIV  IMG  H3  STRONG  UL  LI  BLOCKQUOTE  PRE
```

被吃掉的：`<section>`、`<a>`（头条不允许外链）、`<em>`、以及**所有 `style=""`**。

**标题层级会被压平**：实测把 `<h2>` 和 `<h3>` 一起写进去,编辑器回读时全部变成 `H1` ——
头条只有一级标题,`##` 和 `###` 的层级差别在头条不体现。渲染端照常输出 h2/h3 即可,
但排版时不要指望靠标题层级传达结构。

> 这意味着 `html_converter.py` 那套内联样式排版（渐变高亮、自定义列表圆点、box-shadow）
> 在头条会 100% 失效，而且 `refined-blue` 这类主题的列表符号是用 `<span>` 画的，
> 样式一清洗就变成看不见的空格 —— **头条必须另走一条渲染分支，不能复用微信的 HTML**。

### 4.4 踩过的坑

| 现象 | 原因 | 对策 |
|---|---|---|
| `7113 发布失败，请重试` | 照搬浏览器抓包的完整 payload（含 `mp_editor_stat` / `draft_form_data` 等运行态字段）会被拒 | 用 4.2 的最小字段集，自己构造 |
| `7115 图片uri非法` | 正文含外链图片 | 先走 `/spice/image` 拿 `image_uri` |
| `1053 无效图片数据` | 用了废弃的 `upload_picture` 接口 | 改用 `/spice/image` |
| 从 Python 发请求被拒 | 缺 `a_bogus` 签名 | 只能在页面上下文里发 |

---

## 五、编辑器侧的备选路线（UI 自动化）

页面编辑器是 **`syl-editor`**（字节开源的 [Syllepsis](https://github.com/bytedance/syllepsis)，ProseMirror 内核）。

### 实测：HTML 粘贴有效

构造一个 `ClipboardEvent` 带 `text/html` 派发给 `.ProseMirror`，编辑器会按自己的 schema 解析：

```js
const pm = document.querySelector('.ProseMirror');
const dt = new DataTransfer();
dt.setData('text/html', '<h2>标题</h2><p>正文<strong>加粗</strong></p><ul><li>项</li></ul>');
pm.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
```

结果：`h2 / p / strong / blockquote / li / pre` 全部正确落地；`section / a / em` 被丢弃。

### 实测：外链图片会被头条自动转存 ✨

粘贴 `<img src="https://外站/图.jpg">` 时，编辑器自己发了：

```
POST /spice/image?upload_source=20020002&need_enhance=true&aid=1231&device_platform=web&scene=paste
```

图片被拉取并重新托管到头条 CDN，`<img>` 自动补上 `web_uri` / `img_width` / `img_height`。
**走 UI 路线的话，图片问题不用自己处理** —— 前提是图片 URL 公网可达（微信 `mmbiz.qpic.cn` 有防盗链，大概率不行）。

### 标题填充

标题是一个无 class 的 `<textarea>`，React 受控，要用 native setter：

```js
const ta = document.querySelectorAll('textarea')[0];   // placeholder="请输入文章标题（2～30个字）"
const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
setter.call(ta, title);
ta.dispatchEvent(new Event('input', {bubbles: true}));
```

### 两条路线怎么选

| | 接口路线（4.2） | UI 粘贴路线（本节） |
|---|---|---|
| 速度 | 快，一次请求 | 慢，要等编辑器反应 |
| 图片 | 自己传，可控 | 头条代转存，省事但不可控 |
| 失效点 | 接口字段变更 | CSS 选择器 + 编辑器行为变更 |
| 排版保真 | 自己拼 HTML，确定 | 依赖编辑器 schema，确定性略低 |

**建议主用接口路线，UI 路线留作降级兜底。** 两条都在同一个 Playwright 会话里，切换成本很低。

---

## 六、同类开源项目（备查）

| 项目 | star | 最后提交 | 路线 | 图文 |
|---|---|---|---|---|
| [mf-yang/toutiao-ops](https://github.com/mf-yang/toutiao-ops) | 46 | 2026-05 | Playwright + ClipboardEvent 粘贴 | ✅ |
| [wechatsync/Wechatsync](https://github.com/wechatsync/Wechatsync) | 6308 | 2026-05 | 扩展 + MAIN world 调接口 | ⚠️ 源码私有化，装扩展仍可用（无封面） |
| [doocs/cose](https://github.com/doocs/cose) | 746 | 2026-06 | 扩展 DOM 注入，只填不发 | ✅ 但不处理图片 |
| [chemany/toutiao_mcp_server](https://github.com/chemany/toutiao_mcp_server) | 68 | 2025-06 | Selenium + cookie 持久化 | ✅ |
| [JessYan0913/toutiao-mcp](https://github.com/JessYan0913/toutiao-mcp) | 0 | 2026-08 | Puppeteer 扫码登录 | 正文仅纯文本 |

排除：`dreammis/social-auto-upload`（14997★，只做视频，仓库内 `toutiao` 命中数为 0）、
`iniwap/AIWriteX`（1980★，`ToutiaoAdapter.publish_content()` 直接返回 `NOT_IMPLEMENTED`）。

---

## 七、在本 skill 里怎么落地

### 7.1 接入点

现有管线在 `publish.py:369-387` 已经有一个延迟导入的同步块：

```python
from multi_publish import run as sync_run
sync_result = sync_run(md_path=..., platforms=..., title=..., cover_path=..., strict=False)
```

只要新模块的 `run()` 返回同样的 6 键 dict（`success / platforms / stdout / stderr / returncode / parsed`），
`publish.py:380-384` 一行都不用改。把这里换成一个 dispatcher：原生实现的平台走自家模块，其余落到 wechatsync。

### 7.2 渲染分支（关键）

**不要复用 `html_converter.py` 的产物**（理由见 4.3）。头条需要一份「结构化裸 HTML」：

- 只出 `h2/h3 · p · strong · ul/ol · li · blockquote · pre`，不带任何 `style`
- 图片包成 `<div class="pgc-img">` + 带 `web_uri` 的 `<img>`
- 链接转成纯文本（头条会吃掉 `<a>`）

最自然的分叉点是 `publish.py:292`（图片处理）之后、`publish.py:318`（微信 HTML 转换）之前 ——
那时 markdown 已解析、图片还是本地路径，没被微信 CDN URL 污染。

### 7.3 建议的文件结构

```
scripts/
  toutiao_render.py     # markdown → 头条裸 HTML（纯函数，好测，优先 TDD）
  toutiao_session.py    # Playwright 持久化 profile + 扫码登录 + 登录态探针
  toutiao_api.py        # 在 page.evaluate() 里调 4.1/4.2 的接口
  toutiao_publish.py    # run() 入口，返回值与 multi_publish.run() 同形
tests/
  test_toutiao_render.py    # 纯函数，no_network fixture
```

`toutiao_session.py` 可以照抄仓库里现成的 CDP 范例
`scripts/baoyu_danger_gemini_web/gemini-webapi/utils/load-browser-cookies.ts`：
它已经实现了「拉起独立 profile 的 Chrome → 轮询调试端口 → 等用户扫码 → 用探针接口判断登录态 → 持久化凭据」
整套流程，换掉目标 URL 和探针接口即可（探针可用 `/mp/agw/media/get_media_info`）。

### 7.4 凭据配置

挂在 `wechat-publisher.yaml` 的 `integrations:` 下，与现有 `gemini_web` 同构：

```yaml
integrations:
  toutiao:
    profile_dir: "~/Library/Application Support/wechat-publisher/toutiao-profile"
    chrome_path: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
```

对应在 `config.py:95-97` 旁边加几行 `_set_env_if_present(...)`。

### 7.5 安全默认值

- **`save=0` 存草稿，永远不要默认 `save=1` 直接发布** —— 与本 skill 微信侧「只进草稿箱」的约定一致
- 标题超 30 字要显式报错，不要静默截断
- 失败不回滚微信草稿，只在结果里标记

---

## 八、不用扩展的方案：CDP 直连（已 spike 验证）

### 8.1 为什么扩展不是必需的

wechatsync 必须做成扩展，是因为 **Chrome 扩展的 content script 跑在 isolated world**，
看不见页面改写过的 `window.fetch`，只能绕道 `chrome.scripting.executeScript({world:'MAIN'})`。
它源码里的注释写得很直白：

> content script 的 fetch 不会自动注入 msToken/a_bogus，需要通过 background 使用
> `chrome.scripting.executeScript` 在 MAIN world 执行

**而 CDP 的 `Runtime.evaluate` 默认就在 MAIN world。** 少一整层扩展。

### 8.2 权威测量（CDP Network 事件，非 performance entries）

在同一个登录态、同一个页面、同一份 payload 下对比两种发起方式，
用 `Network.requestWillBeSent` 读真实发出的 URL：

| 发起方式 | URL 上的签名参数 | 服务端 |
|---|---|---|
| CDP `Runtime.evaluate` → `window.fetch` | `msToken`, `a_bogus` | **`code 0 保存成功`** |
| 同页面 iframe 的原生 `fetch`（绕开 secsdk） | 无 | `code 7050 保存失败` |

两条结论同时成立：
1. **签名是硬要求** —— 所以纯 Python / curl 直接打发布接口不行
2. **CDP 能白嫖签名** —— 所以不需要扩展

> ⚠️ 别用 `performance.getEntriesByType('resource')` 判断有没有签名，
> 资源计时条目未必及时写入，会得到「无签名却成功」的假象。用 CDP Network 事件。

### 8.3 例外：图片上传不需要签名

`/spice/image` 实测**不带签名也返回 `code 0`**，连 `x-secsdk-csrf-token` 都不是必需的。
所以图片可以走纯 Python 上传，只有最后那一下 `/mp/agw/article/publish` 必须过浏览器。
（wechatsync 源码里给图片上传带了 csrf token，看起来是保险起见。）

### 8.4 spike 验证结果

`bun spike.ts <配图>` 端到端跑通，全程零扩展：

```
[1/6] 启动 Chrome（独立 profile）
[2/6] CDP 已连接
[4/6] 检查登录态          ✅ 已登录：shuaping (85164444330)
[5/6] 上传配图与封面       正文图 960x540，封面已上传
[6/6] 写入草稿            ✅ 保存成功
      草稿链接: https://mp.toutiao.com/profile_v4/graphic/publish?pgc_id=...
```

**封面也一起打通了** —— 这是 wechatsync 扩展没做的（它 `coverType:3` 硬编码，不传封面）。

### 8.5 落地形态

零新增依赖，复用仓库现有范式：

```
scripts/toutiao_cdp.ts        # 手写 CDP 客户端（bun/Node 内建 WebSocket，零依赖）
                              # 直接照抄 baoyu_danger_gemini_web/.../load-browser-cookies.ts
scripts/toutiao_render.py     # markdown → 头条裸 HTML（纯函数，优先 TDD）
scripts/toutiao_publish.py    # run() 入口，subprocess 调 bun，返回值与 multi_publish.run() 同形
```

Python → bun 的桥接照 `generate_image.py` 的写法。

关键流程（`toutiao_cdp.ts`）：

```
1. spawn Chrome  --remote-debugging-port=<随机空闲端口>
                 --user-data-dir=<独立 profile>     ← 登录态就靠它持久化
2. 轮询 http://127.0.0.1:<port>/json/version 拿 webSocketDebuggerUrl
3. Target.getTargets → 找 mp.toutiao.com 的 page → Target.attachToTarget{flatten:true}
4. Runtime.enable
5. 探针 /mp/agw/media/get_media_info 判断登录态；未登录就提示用户扫码 + 轮询等待
6. Runtime.evaluate 里跑上传 + 发布（本地图片以 base64 传进页面再转 Blob）
7. finally: Browser.close → SIGTERM → 2s 后 SIGKILL
```

### 8.6 这个方案的代价

- 首次要**人工扫码一次**（之后 profile 复用，可长期无人值守）
- 跑的时候会弹一个 Chrome 窗口（独立 profile，不干扰日常浏览器）
- 登录态过期需要重新扫码 —— 探针失败时要给出清晰提示，不要静默失败

---

## 九、保质期提醒

头条的图片链路换过至少三代接口（`tools/catch_picture/` → `article_material/photo/upload_picture` → `spice/image`），
发布接口路径也从 `profile_v3` 迁到过 `profile_v4`。本文档的接口细节请当作**当前快照**，
实现时把 endpoint 和字段集中放在一个文件里，方便改版后快速修。
