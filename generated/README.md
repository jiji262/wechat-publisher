# generated/

本目录是**所有运行时产物的统一输出位置**,内容不会进入 git。

## 里面会有什么

- `article.html` / `article_preview.html` —— `html_converter.py` 的 HTML 输出
- `<slug>/` —— 单篇文章的配图 / 封面 / 中间产物
- `Theme Showcase.html` + `_theme_*.html` —— 主题预览对比页(`assets/themes/` 每套主题的渲染示例)
- 其它临时导出

## 为什么 gitignore

- 生成物体积大且易变(PNG / 渲染 HTML),跟踪会让仓库膨胀
- 每次重新运行脚本都会覆盖,历史无追溯价值
- 可能包含尚未发布的草稿内容,不适合公开

## 需要持久化时怎么办

- 需要归档的成稿请提到仓库外(例如 `mp-articles/<main|tech>/<slug>/`)
- 需要作为 skill / 文档一部分的静态资源请放到 `assets/` 或 `references/`
- 仅 `generated/README.md` 例外保留在 git 中

## 重新生成主题预览

```bash
python3 scripts/html_converter.py generated/_theme_sample.md --theme refined-blue -o generated/_theme_refined-blue.html
# 或者参考 Theme Showcase.html 里记录的命令批量重跑
```
