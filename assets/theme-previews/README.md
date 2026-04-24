# Theme previews

同一篇样例文章 ([`sample.md`](sample.md)) 用 16 套主题渲染出的静态 HTML,打开 [`index.html`](index.html) 可以手机宽度 frame 并排对比。

## 文件

| 文件 | 说明 |
|---|---|
| `index.html` | 主题对比总览(带手机 frame + CLI 提示) |
| `sample.md` | 样例文章源(含 h1~h3 / 列表 / 引用 / 代码块 / 表格 / 7 种行内高亮 / 分节符) |
| `refined-blue.html` | main 账号默认主题预览 |
| `minimal-mono.html` | tech 账号默认主题预览 |
| `<theme>.html`(× 14) | 14 套可选主题预览,与 `../themes/*.json` 一一对应 |

## 主题定义

在 [`../themes/*.json`](../themes/),共 16 套:`academic-paper` · `business-navy` · `cyber-neon` · `elegant-ink` · `girly-pink` · `ink-wash` · `magazine-grid` · `minimal-bw` · `minimal-mono` · `mint-fresh` · `news-bold` · `refined-blue` · `sage-premium` · `sunset-coral` · `warm-editorial` · `warm-orange`。

## 改了主题后重新生成全部预览

```bash
cd wechat-publisher
for theme in academic-paper business-navy cyber-neon elegant-ink girly-pink \
             ink-wash magazine-grid minimal-bw minimal-mono mint-fresh \
             news-bold refined-blue sage-premium sunset-coral warm-editorial \
             warm-orange; do
  python3 scripts/html_converter.py assets/theme-previews/sample.md \
    --theme "$theme" \
    -o "assets/theme-previews/${theme}.html"
done
```

`index.html` 里通过 `<iframe src="${theme}.html">` 引用,文件名需要保持与 `--theme` 值一致。
