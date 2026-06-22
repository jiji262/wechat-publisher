# generated/

本目录是**所有运行时产物的统一输出位置**,内容不会进入 git。

## 里面会有什么

- `article.html` / `article_preview.html` —— `html_converter.py` 的 HTML 输出
- `<slug>/` —— 单篇文章的配图 / 封面 / 中间产物
- 其它临时导出

## 为什么 gitignore

- 生成物体积大且易变(PNG / 渲染 HTML),跟踪会让仓库膨胀
- 每次重新运行脚本都会覆盖,历史无追溯价值
- 可能包含尚未发布的草稿内容,不适合公开

## 需要持久化时怎么办

- 需要归档的成稿请提到仓库外(例如 `mp-articles/<main|tech>/<slug>/`)
- 需要作为 skill / 文档一部分的静态资源请放到 `assets/` 或 `references/`
- 主题对比预览已入库,见 [`assets/theme-previews/`](../assets/theme-previews/)(本目录只有 `README.md` 例外保留)
