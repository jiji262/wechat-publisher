#!/usr/bin/env python3
"""
微信公众号文章发布 - 主流程脚本

整合所有模块，实现从Markdown文章到微信公众号草稿箱的一键发布：
1. 读取Markdown文章
2. 处理文章中的图片（下载+上传到微信）
3. 转换为微信兼容HTML（内联样式排版）
4. 准备封面图
5. 调用API创建草稿

用法：
    python publish.py --input article.md --author "作者名"
    python publish.py --input article.md --cover cover.jpg --title "自定义标题"
    python publish.py --html article.html --cover cover.jpg --title "标题"   # 只用于已经过阶段 3.5 的 HTML,不做 AI 味检测
"""

import sys
import re
import json
import argparse
import tempfile
from pathlib import Path
from typing import Optional

# 添加脚本目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from wechat_api import (
    publish_article,
    publish_newspic,
    upload_thumb_image,
    get_access_token,
    set_account,
    get_config,
    ConfigError,
    resolve_image_style,
    list_image_styles,
)
from html_converter import (
    convert_markdown_to_wechat_html,
    load_styles,
    load_theme,
)
from article_meta import extract_digest_from_markdown, extract_title_from_markdown  # 标题/摘要唯一口径(E5)
from image_handler import process_article_images, extract_images_from_markdown


# ============================================================
# AI 味门禁
# ============================================================

BRIEF_NAME = "brief.md"          # 文章目录下的 brief,提供 experiences 核对亲历/引语出处
ADVISORY_PRINT_MAX = 30         # 控制台最多逐条列出的条数(完整清单用 ai_score.py --advisory 看)
LINE_SAMPLE_MAX = 8             # 超量规则一组里最多列出的行号
NO_MD_PATH = "_no_md_path"      # 缺口 id:没给文章路径,核对不了 humanize_log.md
KEEP_OVERFLOW = "_keep_overflow"  # humanize_log.uncovered 的汇总缺口 id:「保留」行过多
UNSOURCED_PREFIX = "unsourced_"   # 出处核对类规则 id 前缀(保留理由必须带出处)
STAGE_HINT = "SKILL.md 改稿 pass(阶段 3.5)"
HTML_NO_GATE_WARNING = ("\n" + "!" * 60 + "\n[警告] --html 不做 AI 味检测(总分/同形字硬门/humanize_log 都不查)。\n"
                        "只用于已经过阶段 3.5 改稿 pass 的 HTML;模型写的稿子请用 --input <article.md> 走门禁。\n" + "!" * 60)


def strip_zero_width_chars(text):
    """D2:剥离零宽/双向控制字符(多是粘贴残留),有清除时打印数量。

    这是发布前的文本清洗,不是检测:--skip-ai-score 时照样执行;头条链路也调这里。
    """
    import zh_chars

    clean, n = zh_chars.strip_zero_width(text)
    if n > 0:
        print(f"  已清除 {n} 个零宽字符")
    return clean


def run_ai_score_gate(md_content, threshold=None, mode="news", *,
                      md_path=None, title=None, digest=None, account=None):
    """AI 味检测门禁:总分超阈值、同形字硬门、humanize_log 未覆盖 advisory 任一成立即 SystemExit(1)。

    微信和头条两条发布链路共用 —— 抽出来是为了避免两边各写一份报告打印,
    以及避免两边的阈值默认值漂移。

    Args:
        md_content: Markdown 原文(调用方先过 strip_zero_width_chars)
        threshold: 失败阈值。None 时用 ai_score.DEFAULT_THRESHOLD
        mode: "news"(长文)或 "newspic"(贴图短文本)
        md_path: 文章路径。读同目录 brief.md、核对 humanize_log.md;有 advisory 却没给路径时拒发
        title / digest: 最终要发布的标题/摘要,调用方先确定再传,保证查的就是发出去的那一份;
                        None 时 ai_score 取 front matter title 或 H1 / H1 后的引用块
        account: 账号 key(main/tech),启用账号禁用口头禅检查
    """
    _check_ai_score, _DEFAULT_THRESHOLD = _load_ai_score()

    # 使用 ai_score.DEFAULT_THRESHOLD 作为默认值，保证 CLI 与库行为一致
    _threshold = threshold if threshold is not None else _DEFAULT_THRESHOLD
    ctx = {"title": title, "digest": digest, "account": account, "brief_text": _read_brief(md_path)}
    print("\n[预检] AI 味检测...")
    passed, report = _check_ai_score(md_content, _threshold, mode=mode, **ctx)
    total, hard = report.get("total_score"), report.get("hard_fail")
    print(f"  总分: {total} / 100  (阈值 {_threshold})")
    advisory = report.get("advisory") or []
    _print_advisory(advisory)
    _print_artifacts(report.get("artifacts") or [])
    if hard:
        print(f"  结果: 未通过硬门 {hard}(同形字):{_hard_fail_where(report)}")
    score_failed = not passed and (not hard or total >= _threshold)
    if score_failed:
        _print_score_failure(report, _threshold)
    # 先把三类问题都打印出来再统一拒发,省得改一类、重跑、再撞下一类
    gaps = _humanize_log_gaps(advisory, md_content, md_path, ctx=ctx) if advisory else []
    if passed and not gaps:
        print("  结果: 通过")
        return
    _print_block_hints(hard=hard, gaps=gaps, score_failed=score_failed)
    raise SystemExit(1)


def _hard_fail_where(report):
    """同形字命中位置:标题/摘要写 title/digest,正文写行号,附码位。"""
    return "; ".join(f"{a.get('where') or 'L' + str(a.get('line'))} {a.get('excerpt')}({a.get('codepoint', '')})"
                     for a in report.get("adversarial") or [])


def _load_ai_score():
    """导入检测器;失败就拒发(fail-closed):少拷一个模块不能让三道检查静默跳过。"""
    try:
        from ai_score import check_ai_score, DEFAULT_THRESHOLD
    except ImportError as exc:
        print(f"\n[错误] 无法加载 ai_score 模块({exc}),AI 味门禁无法执行,发布已阻止。")
        print("  检查 scripts/ 下 zh_*.py、humanize_log.py、source_check.py 是否齐全;人自己写的稿子可用 --skip-ai-score 显式跳过")
        raise SystemExit(1) from exc
    return check_ai_score, DEFAULT_THRESHOLD


def _read_brief(md_path):
    """文章同目录的 brief.md 文本;不存在返回 None。"""
    path = Path(md_path).parent / BRIEF_NAME if md_path else None
    return path.read_text(encoding="utf-8") if path and path.exists() else None


def _split_by_scope(items):
    """D1 分组:超量规则 {id: [命中]}(按规则处理,一行覆盖整条规则)与逐条项列表。"""
    groups, single = {}, []
    for a in items:
        if a.get("scope") == "density":
            groups.setdefault(a.get("id"), []).append(a)
        else:
            single.append(a)
    return groups, single


def _row_count(items):
    """对应 humanize_log 的行数:超量规则每条一行,逐条项每处一行。"""
    groups, single = _split_by_scope(items)
    return len(groups) + len(single)


def _print_lines(items):
    for a in items[:ADVISORY_PRINT_MAX]:
        excerpt = " ".join(str(a.get("excerpt", "")).split())   # 摘录可能跨行,压成一行
        where = "brief L" if a.get("kind") == "brief" else "L"   # 结构规划行的行号在 brief.md 里,与 log 骨架写法一致
        print(f"    · [{a.get('id')}] {where}{a.get('line')} {excerpt}")
    if len(items) > ADVISORY_PRINT_MAX:
        print(f"    … 其余 {len(items) - ADVISORY_PRINT_MAX} 条见 ai_score.py --advisory")


def _print_items(items):
    """超量规则成组,只给「全文 N 处」和行号(不显示上限,D3);逐条项逐行列出。"""
    groups, single = _split_by_scope(items)
    for rid, group in groups.items():
        nums = list(dict.fromkeys(f"L{a.get('line')}" for a in group))   # 同一行多处只列一次
        lines = "/".join(nums[:LINE_SAMPLE_MAX])
        more = "/…" if len(nums) > LINE_SAMPLE_MAX else ""
        count = group[0].get("count") or len(group)
        print(f"    · [{rid}] {group[0].get('label', '')}:全文 {count} 处({lines}{more}),按规则处理")
    _print_lines(single)


def _print_advisory(advisory, prefix="advisory",
                    hint="不计分;改掉,或在 humanize_log.md 写「保留」+ 理由,超量规则一行原文填 * 即可"):
    """打印 advisory 清单:超量规则按规则成组,零容忍位置等逐条。"""
    if not advisory:
        return
    print(f"  {prefix}: {len(advisory)} 条({hint})")
    _print_items(advisory)


def _print_artifacts(hits):
    """计分伪影(功能性小标题、空格破折号等):已计入总分,只能直接改,不能在 humanize_log 保留。"""
    if hits:
        print(f"  artifacts: {len(hits)} 处(计分伪影,直接改,不能保留)")
        _print_lines(hits)


def _humanize_log_gaps(advisory, md_content, md_path, *, ctx):
    """humanize_log.md 覆盖检查(D1:超量规则按规则、零容忍位置逐条)。返回缺口,非空即应拒发。"""
    import humanize_log

    if not md_path:   # fail-closed:没有路径就核对不了 log,不能当作已覆盖
        print("  结果: 未提供文章路径,无法核对 humanize_log.md")
        return [{"id": NO_MD_PATH, "line": 0, "excerpt": "", "message": "未提供文章路径"}]
    # 与 ai_score.py --check-log 同一个入口:同目录 brief.md / research.md 用于核对 unsourced_* 的出处
    gaps, log_path = humanize_log.check_article(md_path, advisory, md_content)
    if not gaps:
        print(f"  humanize_log.md: {_row_count(advisory)} 项 advisory 均有「保留」记录")
        return []
    print(f"  结果: humanize_log 覆盖检查未通过({log_path})")
    if not log_path.exists():
        print(f"    文件不存在:需要 {_row_count(advisory)} 行(超量规则每条一行,逐条项每处一行)")
    else:
        _print_gaps(gaps)
    if any(g.get("id") != KEEP_OVERFLOW for g in gaps):   # 只是保留过多时骨架已经齐了,不用再生成
        print("  生成/补全骨架(已有行不动,只追加缺的条目;处理列填「保留」,理由至少 6 个字):")
        print("    " + _log_template_command(md_path, ctx))
    return gaps


def _print_gaps(gaps):
    """未覆盖项:「保留」过多排最前(不显示上限,D3),其余按规则/逐条列出。"""
    overflow = [g for g in gaps if g.get("id") == KEEP_OVERFLOW]
    rest = [g for g in gaps if g.get("id") != KEEP_OVERFLOW]
    print(f"    {len(overflow) + _row_count(rest)} 项未通过(处理列须恰好是「保留」且理由有效;"
          "超量规则原文填 * 可按规则保留;删/改的条目改完重跑会自动消失):")
    for g in overflow:
        print(f"    · 「保留」过多(已有 {g.get('count')} 处):多出的请改写,不要靠保留过关")
    _print_items(rest)
    if any(str(g.get("id", "")).startswith(UNSOURCED_PREFIX) for g in rest):
        print("    · unsourced_experience(亲历)的保留理由只认 brief:brief L<行号>(必须是 experiences 那一行)"
              "或 brief experiences,且要和这句对得上;链接证明不了是用户亲历。brief 里没有就删掉这句")
        print("    · unsourced_quote(引语)另认 URL、issue/PR 号、@用户名;写 research.md / brief materials 时要有一行对得上")


def _print_block_hints(*, hard, gaps, score_failed):
    """拒发时按原因分别给下一步(三类可能同时成立)。"""
    print("\n  发布已阻止:")
    if hard:
        print("    · 同形字硬门:把混进正文/标题/摘要的西里尔、希腊字母或康熙部首换回正常字符"
              "(位置见上面的「未通过硬门」行);这一项不能靠 humanize_log 保留")
    ids = {g.get("id") for g in gaps}
    if NO_MD_PATH in ids:
        print("    · 缺文章路径:带上 article.md 的路径重跑,门禁要核对同目录的 humanize_log.md 与 brief.md")
    if KEEP_OVERFLOW in ids:
        print(f"    · 「保留」过多:回到 {STAGE_HINT},把多出的条目改掉(改掉的重跑后自动消失)")
    if ids - {NO_MD_PATH, KEEP_OVERFLOW}:
        print(f"    · humanize_log 未覆盖:回到 {STAGE_HINT},按上面的清单定点改;确需保留的写「保留」+ 理由")
    if score_failed:
        print(f"    · 总分超限:回到 {STAGE_HINT},按上面的失分维度改;humanize_log 的保留不抵总分")
    print("  人自己写的稿子可用 --skip-ai-score 跳过此检测(模型生成的稿子不要用)。")


def _log_template_command(md_path, ctx):
    """拼出与本次门禁同口径的 ai_score.py --log-template 命令,保证骨架里的条目与这里一致。"""
    import shlex
    import zh_tells

    parts = ["python3", str(Path(__file__).parent / "ai_score.py"), str(md_path), "--advisory", "--log-template"]
    brief_path = Path(md_path).parent / BRIEF_NAME
    if ctx.get("brief_text") is not None:
        parts += ["--brief", str(brief_path)]
    if ctx.get("account") in zh_tells.ACCOUNT_BANNED:   # ai_score CLI 只接受有禁用词表的账号
        parts += ["--account", ctx["account"]]
    for flag in ("title", "digest"):
        if ctx.get(flag):
            parts += [f"--{flag}", ctx[flag]]
    return " ".join(shlex.quote(p) for p in parts)


def _print_score_failure(report, threshold):
    """总分超阈值时的失分明细。"""
    total = report.get("total_score")
    print(f"  结果: 未通过 AI 味检测(总分 {total} >= 阈值 {threshold})")
    dims = report.get("dimensions", {}) or {}
    if dims:
        print("  失分维度:")
        for name, info in dims.items():
            score = info.get("score") if isinstance(info, dict) else info
            print(f"    · {name}: {score}")
    hit_phrases = report.get("hit_phrases") or []
    if hit_phrases:
        print("  命中 AI 套话:")
        for s in hit_phrases[:10]:
            print(f"    · {s}")
    hit_vocab = report.get("hit_vocab") or []
    if hit_vocab:
        print("  命中 AI 高频词: " + ", ".join(str(v) for v in hit_vocab[:15]))


def _account_key(account_name=None):
    """当前账号 key(main/tech…),供账号禁用口头禅检查;没有可用配置时原样返回入参。"""
    try:
        return get_config(account_name).get("account_key") or account_name
    except ConfigError:
        return account_name


# ============================================================
# Markdown 文本处理工具
# ============================================================

def remove_title_from_content(md_content):
    """从内容中移除标题行（避免在正文中重复显示标题）"""
    lines = md_content.split("\n")
    result = []
    title_removed = False
    for line in lines:
        if not title_removed and re.match(r'^#\s+', line.strip()):
            title_removed = True
            continue
        result.append(line)
    return "\n".join(result)


# ============================================================
# 默认临时目录
# ============================================================

def _default_temp_dir() -> str:
    """为本次运行创建一个独立的临时目录,避免并发运行互相覆盖文件。"""
    return tempfile.mkdtemp(prefix="wechat_images_")


# ============================================================
# 发布主流程
# ============================================================

def publish_from_markdown(
    md_path,
    title=None,
    author=None,
    digest=None,
    cover_path=None,
    source_url="",
    temp_dir=None,
    style_path=None,
    theme=None,
    sync_platforms=None,
    account_name: Optional[str] = None,
    ai_score_threshold: float = None,  # None → use ai_score.DEFAULT_THRESHOLD
    skip_ai_score: bool = False,
    allow_missing_images: bool = False,
    debug: bool = False,
):
    """
    从Markdown文件发布文章到微信公众号草稿箱。

    完整流程：
    1. 读取Markdown,剥离零宽字符(D2,不受 skip_ai_score 影响)
    2. 确定最终标题和摘要(手动传入优先,否则从Markdown提取)
    3. AI 味检测(gate,查的就是第 2 步要发布的标题/摘要;可用 skip_ai_score 关闭)
    4. 处理图片（下载+上传微信）
    5. 转换HTML排版
    6. 准备封面图
    7. 创建草稿

    Args:
        md_path: Markdown文件路径
        title: 标题（可选，默认从Markdown提取）
        author: 作者名(默认从账号配置读取,再兜底到 "飞哥")
        digest: 摘要（可选，默认从Markdown提取）
        cover_path: 封面图路径（可选，默认使用文章第一张图）
        source_url: 原文链接
        temp_dir: 临时文件目录(默认为每次运行独立生成)
        style_path: 自定义样式文件路径
        theme: 排版主题名(默认从账号配置读取)
        sync_platforms: 同步到其他平台的列表
        account_name: 若指定,则在函数内部调用 set_account() 切换账号
        ai_score_threshold: AI 味检测阈值,总分 >= 阈值视为不通过(默认 45)
        skip_ai_score: True 时跳过 AI 味检测全部环节(总分/同形字硬门/humanize_log 覆盖检查,默认 False)
        allow_missing_images: True 时允许部分图片上传失败仍继续发布(默认 False,缺图即中止)
        debug: True 时把生成的 HTML 保存到 temp_dir 下方便调试

    Returns:
        dict: 发布结果
    """
    # 如果库调用方指定了账号,立即切换
    if account_name:
        set_account(account_name)

    if temp_dir is None:
        temp_dir = _default_temp_dir()

    print("=" * 60)
    print("微信公众号文章发布")
    print("=" * 60)

    # 1. 读取文章
    md_path = Path(md_path)
    if not md_path.exists():
        raise FileNotFoundError(f"文章文件不存在：{md_path}")

    with open(md_path, "r", encoding="utf-8") as f:
        md_content = f.read()

    print(f"读取文章：{md_path} ({len(md_content)} 字符)")
    md_content = strip_zero_width_chars(md_content)

    # 2. 先定最终标题和摘要:门禁查的必须是要发布的这一份(无 H1 时的回退标题、全文第一个引用块做摘要都算)
    title = strip_zero_width_chars(title or extract_title_from_markdown(md_content))   # --title/--digest 也清(E4)
    digest = strip_zero_width_chars(digest or extract_digest_from_markdown(md_content))

    # 3. AI 味检测(在图片上传前,失败时避免浪费素材库配额)
    if not skip_ai_score:
        run_ai_score_gate(md_content, ai_score_threshold, md_path=md_path, title=title,
                          digest=digest, account=_account_key(account_name))

    print(f"标题：{title}")
    print(f"摘要：{digest[:50]}...")

    # 4. 验证API连接
    print("\n[步骤1] 验证API连接...")
    try:
        token = get_access_token()
        print(f"  API连接正常，token已获取")
    except Exception as e:
        print(f"  API连接失败：{e}")
        print("  请检查 wechat-publisher.yaml 中的 app_id / app_secret 配置")
        sys.exit(1)

    # 5. 处理图片
    print("\n[步骤2] 处理文章图片...")
    # 移除标题后处理（标题不包含在正文中）
    content_md = remove_title_from_content(md_content)
    processed_md, img_mapping, first_img = process_article_images(
        content_md, temp_dir, base_dir=md_path.parent
    )

    # 缺图守卫：引用了但未成功上传的图片,默认中止发布,避免产出缺图草稿
    referenced = {img["url"] for img in extract_images_from_markdown(content_md)}
    missing = sorted(u for u in referenced if u not in img_mapping)
    if missing:
        print(f"\n  错误：{len(missing)} 张图片引用未能上传：")
        for u in missing:
            print(f"    · {u}")
        if allow_missing_images:
            print("  --allow-missing-images 已指定,继续发布(草稿将缺图)。")
        else:
            print(
                "  发布已中止。请检查图片路径(相对路径按 article.md 所在目录解析),\n"
                "  或显式传 --allow-missing-images 接受缺图草稿。"
            )
            raise SystemExit(1)

    # 6. 转换HTML
    print("\n[步骤3] 转换HTML排版...")
    styles, highlights, divider_text, list_style = load_theme(
        theme_name=theme, style_path=style_path
    )
    print(f"  主题: {theme or '(默认)'}")
    html_content = convert_markdown_to_wechat_html(
        processed_md, styles, highlights, divider_text, list_style
    )
    print(f"  HTML生成完成 ({len(html_content)} 字符)")

    # 仅在 debug 模式下持久化中间 HTML(否则会堆满临时目录)
    if debug:
        html_path = Path(temp_dir) / "article_output.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"  [debug] HTML已保存到：{html_path}")

    # 7. 准备封面图
    print("\n[步骤4] 准备封面图...")
    if cover_path and Path(cover_path).exists():
        print(f"  使用指定封面图：{cover_path}")
    elif first_img:
        cover_path = first_img
        print(f"  使用文章第一张图作为封面：{cover_path}")
    else:
        print("  警告：没有封面图！请提供 --cover 参数")
        print("  微信公众号要求每篇文章必须有封面图")
        sys.exit(1)

    # 8. 如未提供 author,从账号配置兜底读取
    if author is None:
        try:
            cfg = get_config(account_name)
            author = cfg.get("author", "") or "飞哥"
        except ConfigError:
            author = "飞哥"

    # 9. 发布到草稿箱
    print("\n[步骤5] 发布到草稿箱...")
    result = publish_article(
        title=title,
        html_content=html_content,
        cover_image_path=cover_path,
        author=author,
        digest=digest,
        source_url=source_url,
    )

    print("\n" + "=" * 60)
    print("发布完成！")
    print(f"  草稿 media_id: {result['media_id']}")
    print("  请登录微信公众平台查看草稿箱")
    print("=" * 60)

    # 可选阶段：同步到其他内容平台(opt-in,失败不影响微信发布结果)
    if sync_platforms:
        print(f"\n[可选] 同步到其他平台: {', '.join(sync_platforms)}")
        try:
            from multi_publish import run as sync_run
            sync_result = sync_run(
                md_path=md_path,
                platforms=sync_platforms,
                title=title,
                cover_path=cover_path,
                strict=False,
            )
            result["sync"] = {
                "platforms": sync_platforms,
                "success": sync_result["success"],
                "returncode": sync_result["returncode"],
            }
        except Exception as e:
            print(f"  同步环节异常(不影响微信发布): {e}")
            result["sync"] = {"platforms": sync_platforms, "success": False, "error": str(e)}

    return result


def publish_from_brief(
    brief_path,
    account_name: Optional[str] = None,
    image_style: Optional[str] = None,
    title: Optional[str] = None,
    author: Optional[str] = None,
    ai_score_threshold: float = None,
    skip_ai_score: bool = False,
):
    """
    从 brief.md 发布贴图(newspic)到草稿箱。

    期望目录布局(brief.md 旁边):
        <dir>/
          brief.md        # 本次输入,含 frontmatter + 要点 + 短文本
          card_plan.json  # (可选)newspic_build.py 生成过就存在
          images/
            01.png
            02.png
            ...

    完整流程:
      1. 解析 brief.md,拿到 topic / title / account / image_style / 短文本
      2. 检查 images/ 下按 NN.png(或其他格式)顺序命名的图片
      3. 标题过同形字硬门;短文本不空时过 AI 味 gate(newspic 模式);短文本/要点/标题的 advisory 只打印
      4. 依次上传图片为永久素材,收到 media_id
      5. 调 draft/add article_type=newspic 建草稿

    Args:
        brief_path: brief.md 路径
        account_name: 覆盖 frontmatter.account
        image_style: 覆盖 frontmatter.image_style(优先级最高,但本函数主要用于发布,
                     真正影响生图的是 newspic_build.py。这里仅记录到返回值里)
        title: 覆盖 frontmatter.title
        author: 覆盖账号默认作者
        ai_score_threshold: AI 味检测阈值(newspic 短文本)
        skip_ai_score: 跳过标题同形字硬门、短文本打分和要点/标题 lint

    Returns:
        dict: 发布结果(同 publish_newspic 返回值),外加 "image_style" / "cards" 信息
    """
    # 延迟导入以避免与 newspic_build 的循环依赖(实际无依赖,但保持对称)
    from newspic_build import parse_brief, card_points

    brief_path = Path(brief_path)
    if not brief_path.exists():
        raise FileNotFoundError(f"brief.md 不存在: {brief_path}")

    parsed = parse_brief(brief_path.read_text(encoding="utf-8"))
    fm = parsed["frontmatter"] or {}
    sections = parsed["sections"]

    # 账号解析: CLI > frontmatter > 全局激活
    final_account = account_name or fm.get("account")
    if final_account:
        set_account(final_account)

    # 标题/作者/风格(贴图模式走 newspic,让兜底用手绘水彩信息图而非文章线条手绘)
    final_title = title or fm.get("title", "") or ""
    style = resolve_image_style(
        cli_value=image_style,
        frontmatter_value=fm.get("image_style"),
        account_name=final_account,
        mode="newspic",
    )

    # 短文本(和标题一样先清掉零宽字符,D2)
    short_text = strip_zero_width_chars((sections.get("短文本") or sections.get("短描述") or "").strip())
    final_title = strip_zero_width_chars(final_title)

    print("=" * 60)
    print("微信公众号贴图(newspic)发布")
    print("=" * 60)
    print(f"brief:    {brief_path}")
    print(f"话题:     {fm.get('topic', '(未填)')}")
    print(f"标题:     {final_title or '(空)'}")
    print(f"风格:     {style['style_name']} ({style.get('display_name','')})")
    print(f"短文本:   {len(short_text)} 字")

    # 收集图片
    images_dir = brief_path.parent / "images"
    if not images_dir.exists():
        raise FileNotFoundError(
            f"找不到图片目录: {images_dir}\n"
            f"请先用 newspic_build.py + scripts/baoyu_image_gen.ts 生成贴图,保存为 {images_dir}/01.png 起。"
        )
    exts = (".png", ".jpg", ".jpeg", ".webp")
    image_paths = sorted(
        [p for p in images_dir.iterdir() if p.suffix.lower() in exts],
        key=lambda p: p.name,
    )
    if not image_paths:
        raise FileNotFoundError(f"{images_dir} 下没有图片,请先生图")
    if len(image_paths) < 2:
        print(f"[警告] 只有 {len(image_paths)} 张图。newspic 建议 5-10 张。")
    if len(image_paths) > 20:
        print(f"[警告] {len(image_paths)} 张超出微信 20 张上限,截取前 20 张")
        image_paths = image_paths[:20]
    print(f"图片:     {len(image_paths)} 张  (首张 {image_paths[0].name} 为封面)")
    print("-" * 60)

    # AI 味 gate(newspic 模式):标题同形字、短文本打分可拒发;短文本/要点/标题的 advisory 只打印
    if not skip_ai_score:
        _newspic_title_gate(final_title)
        if short_text:
            _newspic_short_text_gate(short_text, ai_score_threshold, _account_key(final_account))
        _print_card_advisory(card_points(sections), final_title)

    # 验证 API 连接(fail fast,避免图片上传一半才发现 token 错)
    print("\n[步骤1] 验证 API 连接...")
    try:
        get_access_token()
        print("  API 连接正常")
    except Exception as e:
        print(f"  API 连接失败: {e}")
        raise SystemExit(1)

    # 作者兜底
    if author is None:
        try:
            cfg = get_config(final_account)
            author = cfg.get("author", "") or ""
        except ConfigError:
            author = ""

    # 上传 + 建草稿
    print("\n[步骤2] 上传图片 + 创建贴图草稿...")
    result = publish_newspic(
        title=final_title,
        content=short_text,
        image_paths=image_paths,
        author=author,
    )

    result["image_style"] = style["style_name"]
    result["type"] = "newspic"
    result["cards"] = len(image_paths)
    result["brief_path"] = str(brief_path)

    print("\n" + "=" * 60)
    print("贴图发布完成!")
    print(f"  草稿 media_id: {result['media_id']}")
    print(f"  图片张数: {result['cards']}")
    print(f"  风格: {result['image_style']}")
    print("  请登录微信公众平台查看草稿箱")
    print("=" * 60)

    return result


def _newspic_short_text_gate(short_text, threshold, account):
    """贴图短文本:按 newspic 权重打分,超阈值或命中硬门 → SystemExit(1);advisory 只打印。"""
    check_ai_score, _DEFAULT_THRESHOLD = _load_ai_score()
    _threshold = threshold if threshold is not None else _DEFAULT_THRESHOLD
    print(f"\n[预检] AI 味检测(newspic 模式,阈值 {_threshold})...")
    passed, report = check_ai_score(short_text, _threshold, mode="newspic", account=account)
    print(f"  总分: {report['total_score']} / 100")
    _print_advisory(report.get("advisory") or [], prefix="短文本 advisory", hint="不计分,只提示不阻断")
    if passed:
        print("  结果: 通过")
        return
    if report.get("hard_fail"):
        print(f"  结果: 未通过硬门 {report['hard_fail']}(同形字)")
        fix = "把短文本里混进来的西里尔/希腊字母或康熙部首换回正常字符"
    else:
        print(f"  结果: 未通过(>= 阈值 {_threshold})")
        fix = "重写 brief.md 的『# 短文本』段落,去掉套话"
    hit_phrases = report.get("hit_phrases") or []
    hit_vocab = report.get("hit_vocab") or []
    if hit_phrases:
        print("  命中 AI 套话: " + ", ".join(hit_phrases[:8]))
    if hit_vocab:
        print("  命中 AI 高频词: " + ", ".join(str(v) for v in hit_vocab[:10]))
    print(f"\n  发布已阻止。请{fix}。\n  或用 --skip-ai-score 跳过(不推荐)。")
    raise SystemExit(1)


def _newspic_title_gate(title):
    """贴图标题的同形字硬门(F6):标题不进短文本打分,这里单独查,命中 → SystemExit(1)。"""
    import zh_tells

    hits = zh_tells.find_adversarial_chars(title or "")
    if not hits:
        return
    shown = ", ".join(f"{h.get('excerpt')}({h.get('codepoint', '')})" for h in hits)
    print(f"\n  结果: 标题未通过硬门 adversarial_chars(同形字):{shown}")
    print("\n  发布已阻止。请把标题里的西里尔/希腊字母或康熙部首换回正常字符。\n"
          "  或用 --skip-ai-score 跳过(不推荐)。")
    raise SystemExit(1)


def _print_card_advisory(points, title):
    """贴图标题与卡面要点的 lint:只打印,不阻断(图片已按要点生成,改要点需重新生图)。"""
    try:
        from newspic_build import lint_card_text
    except ImportError as exc:
        print(f"[警告] 无法加载卡面 lint({exc}),跳过。")
        return
    hits = [("标题", w) for w in lint_card_text(title)]
    hits += [(f"要点 {i}", w) for i, p in enumerate(points, 1) for w in lint_card_text(p)]
    if not hits:
        return
    print(f"  卡面/标题 advisory: {len(hits)} 条(只提示,不阻断;卡面改动需重新生图)")
    for where, w in hits:
        print(f"    · [{w['id']}] {where}: {w['excerpt']}")


def publish_from_html(
    html_path,
    title,
    cover_path,
    author=None,
    digest="",
    source_url="",
    account_name: Optional[str] = None,
):
    """从已排版的HTML文件发布文章。只用于已经过阶段 3.5 改稿 pass 的 HTML:不做 AI 味检测(运行时打印警告),
    不支持多平台同步;零宽字符照常清除(HTML、标题、摘要)。

    Args:
        html_path: HTML文件路径
        title: 文章标题（必需）
        cover_path: 封面图路径（必需）
        author: 作者名(默认从账号配置读取,再兜底到 "飞哥")
        digest: 摘要
        source_url: 原文链接
        account_name: 若指定,则在函数内部调用 set_account() 切换账号

    Returns:
        dict: 发布结果
    """
    if account_name:
        set_account(account_name)

    print(HTML_NO_GATE_WARNING)
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = strip_zero_width_chars(f.read())
    title, digest = strip_zero_width_chars(title), strip_zero_width_chars(digest or "")

    # 如未提供 author,从账号配置兜底读取
    if author is None:
        try:
            cfg = get_config(account_name)
            author = cfg.get("author", "") or "飞哥"
        except ConfigError:
            author = "飞哥"

    result = publish_article(
        title=title,
        html_content=html_content,
        cover_image_path=cover_path,
        author=author,
        digest=digest,
        source_url=source_url,
    )
    return result


# ============================================================
# 命令行入口
# ============================================================

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="微信公众号文章一键发布到草稿箱",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 从Markdown发布
  python publish.py --input article.md --author "张三"

  # 指定封面图和标题
  python publish.py --input article.md --cover cover.jpg --title "自定义标题"

  # 从HTML发布(不做 AI 味检测:只用于已经过阶段 3.5 改稿 pass 的 HTML)
  python publish.py --html article.html --cover cover.jpg --title "标题"

  # 跳过 AI 味检测或调整阈值:只用于人自己写的稿子,模型生成的稿子不要用
  python publish.py --input article.md --cover cover.jpg --skip-ai-score
  python publish.py --input article.md --cover cover.jpg --ai-score-threshold 55
        """
    )

    parser.add_argument("--input", "-i", help="Markdown文件路径")
    parser.add_argument("--html", help="HTML文件路径(已排版)。不做 AI 味检测,只用于已经过阶段 3.5 改稿 pass 的 HTML")
    parser.add_argument("--brief", help="贴图(newspic)模式的 brief.md 路径")
    parser.add_argument(
        "--type",
        choices=["news", "newspic"],
        default=None,
        help="发布类型: news(图文,默认) / newspic(贴图/图片消息)。"
             "--brief 存在时自动推断为 newspic",
    )
    parser.add_argument("--title", "-t", help="文章标题（默认从文章提取）")
    parser.add_argument("--cover", "-c", help="封面图路径")
    parser.add_argument("--author", "-a", default=None,
                        help="作者名（默认从账号配置获取，兜底：飞哥）")
    parser.add_argument("--digest", "-d", help="文章摘要（默认从文章提取;手动传入的也会过 AI 味 lint）")
    parser.add_argument("--source-url", default="", help="原文链接")
    parser.add_argument("--style", help="自定义样式JSON路径")
    parser.add_argument("--theme", help="排版主题名(对应 assets/themes/<name>.json,默认从账号配置读取)")
    parser.add_argument(
        "--image-style",
        help="配图风格名(对应 assets/image-styles/<name>.json)。"
             "优先级: CLI > brief/article frontmatter > 账号默认 > hand-drawn-blue。"
             "list: python3 wechat_api.py list-image-styles",
    )
    parser.add_argument(
        "--temp-dir",
        default=None,
        help="临时文件目录(默认每次运行独立生成,避免并发冲突)",
    )
    parser.add_argument("--account", help="指定公众号账号（对应 wechat-publisher.yaml 中的账号名）")
    parser.add_argument(
        "--platform",
        default="wechat",
        help="发布目标平台,逗号分隔: wechat / toutiao(默认 wechat)。"
             "如 --platform wechat,toutiao 一次发两边;--platform toutiao 只发头条。"
             "头条走 CDP 直连,首次使用需在弹出的 Chrome 窗口扫码登录",
    )
    parser.add_argument(
        "--sync",
        help="可选:发到微信后同步到其他平台,逗号分隔(如 zhihu,juejin,csdn)。"
             "覆盖 --sync-from-config。需先装 @wechatsync/cli 并配置 WECHATSYNC_MCP_TOKEN",
    )
    parser.add_argument(
        "--sync-from-config", action="store_true",
        help="可选:同步到账号配置里 sync_platforms 字段指定的平台",
    )
    parser.add_argument(
        "--ai-score-threshold",
        type=float,
        default=None,
        help="AI 味检测阈值(默认与 ai_score.DEFAULT_THRESHOLD 一致)。总分 >= 阈值则阻止发布",
    )
    parser.add_argument(
        "--skip-ai-score",
        action="store_true",
        help="跳过发布前的全部 AI 味检查:总分、同形字硬门、advisory、humanize_log.md 覆盖;贴图模式下跳过"
             "标题同形字、短文本打分和要点/标题 lint(零宽字符照常清除)。只用于人自己写的稿子,"
             "模型生成的稿子仍要走改稿 pass(SKILL.md 阶段 3.5)",
    )
    parser.add_argument(
        "--allow-missing-images",
        action="store_true",
        help="允许部分图片上传失败仍继续发布(默认缺图即中止,避免产出缺图草稿)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="调试模式:把生成的 HTML 保存到 temp_dir 方便排查",
    )
    return parser


def _resolve_config(args):
    """按命令行参数回读账号配置,填充 author/theme/sync_platforms。

    返回 config_sync_platforms(配置里声明的同步平台列表,可能为 None)。
    约定:
      - `--sync-from-config` 显式要求读配置,任何 ConfigError 都应 exit 1。
      - 其他情况(只是兜底 author/theme)下 ConfigError 会被静默吞掉,
        保留原有"没有配置文件也能用 --author 硬写"的行为。
    """
    config_sync_platforms = None
    needs_config = (
        args.author is None or args.theme is None or args.sync_from_config
    )
    if not needs_config:
        return config_sync_platforms

    try:
        config = get_config()
    except ConfigError as e:
        if args.sync_from_config:
            print(f"[配置错误] {e}", file=sys.stderr)
            print("--sync-from-config 需要有效的 wechat-publisher.yaml 配置。", file=sys.stderr)
            sys.exit(1)
        if args.author is None:
            args.author = "飞哥"
        return config_sync_platforms

    if args.author is None:
        args.author = config.get("author", "") or "飞哥"
    if args.theme is None:
        args.theme = config.get("theme", "") or None
    config_sync_platforms = config.get("sync_platforms") or None
    return config_sync_platforms


def _resolve_sync_platforms(args, config_sync_platforms):
    """解析最终要同步的平台列表: --sync 显式指定 > 配置里的 sync_platforms。"""
    if args.sync:
        return [p.strip() for p in args.sync.split(",") if p.strip()]
    if args.sync_from_config and config_sync_platforms:
        if isinstance(config_sync_platforms, str):
            return [p.strip() for p in config_sync_platforms.split(",") if p.strip()]
        return [str(p).strip() for p in config_sync_platforms if str(p).strip()]
    return None


SUPPORTED_TARGET_PLATFORMS = ("wechat", "toutiao")


def _resolve_target_platforms(args, parser):
    """解析 --platform。保留顺序并去重,未知平台直接报错。"""
    raw = [p.strip().lower() for p in (args.platform or "").split(",") if p.strip()]
    if not raw:
        parser.error("--platform 不能为空,可选: " + " / ".join(SUPPORTED_TARGET_PLATFORMS))
    unknown = [p for p in raw if p not in SUPPORTED_TARGET_PLATFORMS]
    if unknown:
        parser.error(
            f"未知平台: {', '.join(unknown)}。可选: {' / '.join(SUPPORTED_TARGET_PLATFORMS)}。"
            "（--platform 是发布目标;同步到知乎/掘金等请用 --sync）"
        )
    platforms = list(dict.fromkeys(raw))

    # --sync 走的是"微信发完再同步"那条链路,没有微信就无处可同步。
    # 静默忽略会让用户以为同步了,所以显式报错。
    if args.sync and "wechat" not in platforms:
        parser.error(
            "--sync 依赖微信发布链路,但 --platform 里没有 wechat。"
            "请改成 --platform wechat,toutiao,或去掉 --sync。"
        )
    return platforms


def _publish_to_toutiao(args, already_gated):
    """调用头条发布链路。already_gated=True 表示微信侧已经跑过 AI 味门禁,不重复;
    只发头条时由 toutiao_publish 带文章路径和头条最终标题跑同一个 run_ai_score_gate。"""
    print("\n" + "=" * 60)
    print("发布到今日头条")
    print("=" * 60)
    from toutiao_publish import run as toutiao_run
    return toutiao_run(
        md_path=args.input,
        title=args.title,
        cover_path=args.cover,
        temp_dir=args.temp_dir,
        ai_score_threshold=args.ai_score_threshold,
        skip_ai_score=args.skip_ai_score or already_gated,
        allow_missing_images=args.allow_missing_images,
        account=_account_key(args.account),
    )


def main():
    parser = _build_parser()
    args = parser.parse_args()
    platforms = _resolve_target_platforms(args, parser)

    # 设置全局账号
    if args.account:
        set_account(args.account)

    # 从账号配置回读 author / theme / sync_platforms
    config_sync_platforms = _resolve_config(args)

    # 解析最终要同步的平台列表
    sync_platforms = _resolve_sync_platforms(args, config_sync_platforms)

    # 头条只支持 markdown 图文一条路径
    if "toutiao" in platforms and (args.brief or args.type == "newspic" or args.html):
        parser.error(
            "头条只支持 --input <markdown> 图文模式,"
            "不支持贴图(newspic)和 --html(那是微信专用排版)。"
        )

    # --brief 存在 或 --type newspic 走贴图分支
    if args.brief or args.type == "newspic":
        if not args.brief:
            parser.error("--type newspic 需要同时指定 --brief <brief.md>")
        if args.sync or args.sync_from_config:
            parser.error("贴图(newspic)模式不支持多平台同步")
        result = publish_from_brief(
            brief_path=args.brief,
            account_name=args.account,
            image_style=args.image_style,
            title=args.title,
            author=args.author,
            ai_score_threshold=args.ai_score_threshold,
            skip_ai_score=args.skip_ai_score,
        )
    elif args.html:
        if not args.title or not args.cover:
            parser.error("使用 --html 模式时，必须提供 --title 和 --cover")
        if args.sync or args.sync_from_config:
            parser.error(
                "--html 模式不支持多平台同步(HTML 已是微信专用排版)。"
                "如需同步请改用 --input <markdown>。"
            )
        result = publish_from_html(
            html_path=args.html,
            title=args.title,
            cover_path=args.cover,
            author=args.author,
            digest=args.digest or "",
            source_url=args.source_url,
        )
    elif args.input:
        result = {}
        if "wechat" in platforms:
            result = publish_from_markdown(
                md_path=args.input,
                title=args.title,
                author=args.author,
                digest=args.digest,
                cover_path=args.cover,
                source_url=args.source_url,
                temp_dir=args.temp_dir,
                style_path=args.style,
                theme=args.theme,
                sync_platforms=sync_platforms,
                ai_score_threshold=args.ai_score_threshold,
                skip_ai_score=args.skip_ai_score,
                allow_missing_images=args.allow_missing_images,
                debug=args.debug,
            )
        if "toutiao" in platforms:
            result["toutiao"] = _publish_to_toutiao(
                args, already_gated="wechat" in platforms
            )
    else:
        parser.error("请提供 --input (Markdown) / --html / --brief(贴图)参数")

    # 输出JSON结果
    print("\n" + json.dumps(result, ensure_ascii=False, indent=2))

    # 头条失败要反映在退出码上,否则脚本调用方看不出问题
    toutiao_result = result.get("toutiao") if isinstance(result, dict) else None
    if toutiao_result and not toutiao_result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
