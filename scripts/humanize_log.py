"""humanize_log.md:advisory 处理留痕的覆盖检查(D1:按规则记录)。

- density 条目(某规则全文超量):log 里一行 `规则=<id>`、`处理=保留`、原文填 `*` 或任一命中原文,即覆盖该规则全部命中;
- position 条目(零容忍位置/零容忍规则):逐条一行,同 id 且原文匹配(去空白互为子串,且不短于 min(4 个汉字, 命中全长));
  一行最多覆盖一条命中(贪心一对一,优先原文长度最接近的行),拼接多段原文只顶一条(E2);
- 处理必须恰好是「保留」;理由去空白 ≥6 字符且不是占位;保留上限 max(3, 汉字数 // 1000):density 按行、position 按条计;
- unsourced_* 的保留理由由 source_check 核对:指向的 brief 行 / 字段 / research 必须存在且对得上,不占上限。
这是文件/结构层面的确定性检查,不做语言判断(DR-3)。brief 解析在 zh_sources,这里转出以兼容旧调用。
"""
from __future__ import annotations

import re

from pathlib import Path

from source_check import source_ok
from zh_sources import covered, parse_brief  # noqa: F401  旧调用方(fidelity_check)从这里取
from zh_text import han_count, mask_markdown

LOG_NAME = "humanize_log.md"
KEEP_MIN, KEEP_HAN_PER = 3, 1000     # 保留上限 = max(3, 汉字数 // 1000)
REASON_MIN = 6                       # 理由去空白后至少 6 个字符
EXCERPT_MIN_HAN = 4                  # position 行原文至少 4 个汉字(或等于命中全长)
ANY = "*"                            # density 行原文通配
UNCOUNTED_PREFIX = "unsourced_"      # 出处核对类:保留理由由 source_check 核对出处,不占保留上限
_PLACEHOLDER = re.compile(r"(?:无|没有|暂无|-|—|同上|见上|略|n/?a|none|待补|待定|todo|tbd|x|\.|。|…|/)+", re.I)
_HEADER = "| 规则 | 行 | 原文 | 处理 | 理由/出处 |\n|---|---|---|---|---|"
_INTRO = ("# humanize_log\n\n处理列填「保留」才算覆盖;改掉的条目重跑后自动消失。"
          "原文为 * 的行按规则处理(一行覆盖该规则全部命中);理由写清为什么保留,有出处附上 URL 或 brief 行。\n\n")


def _cell(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ").strip()


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _skeleton(advisory: list[dict]) -> list[tuple[tuple, int]]:
    """骨架行 ((id, 行, 原文), 代表条目下标):density 规则每条一行(原文 *),position 每条一行。"""
    out, seen = [], set()
    for n, a in enumerate(advisory):
        if a.get("scope") != "density":
            line = f"brief L{a.get('line', '')}" if a.get("kind") == "brief" else str(a.get("line", ""))
            out.append(((a["id"], line, a.get("excerpt", "")), n))
        elif a["id"] not in seen:
            seen.add(a["id"])
            out.append(((a["id"], f"全文 {a.get('count', '')} 处", ANY), n))
    return out


def _row(r: tuple[str, str, str]) -> str:
    return f"| {_cell(r[0])} | {_cell(r[1])} | {_cell(r[2])} |  |  |"


def render_template(advisory: list[dict]) -> str:
    return _INTRO + _HEADER + "\n" + "".join(_row(r) + "\n" for r, _ in _skeleton(advisory))


def parse_log(text: str) -> list[dict]:
    rows = []
    for ln in (text or "").splitlines():
        cells = [c.replace("\\|", "|").strip() for c in re.split(r"(?<!\\)\|", ln.strip())[1:-1]]
        if len(cells) < 5 or cells[0] in ("规则", "") or set(cells[0]) <= set("-: "):
            continue
        rows.append({"id": cells[0], "line": cells[1], "excerpt": cells[2], "action": cells[3], "reason": cells[4]})
    return rows


def _same(log_ex: str, hit_ex: str) -> bool:
    """去空白后互为子串,且 log 原文不短于 min(4 个汉字, 命中全长)——防单字原文糊弄。"""
    a, b = _norm(log_ex), _norm(hit_ex)
    return bool(a and b) and (a in b or b in a) and (han_count(a) >= EXCERPT_MIN_HAN or len(a) >= len(b))


def _reason_ok(reason: str) -> bool:
    r = _norm(reason)
    return len(r) >= REASON_MIN and not _PLACEHOLDER.fullmatch(r)


def _position_row(item: dict, rows: list[dict], taken: set[int], *, ctx: dict | None) -> int | None:
    """还没被别的命中占用、原文匹配的行里,取原文长度最接近命中的一行。ctx 为 None 时不核对出处(补骨架用)。"""
    ex = item.get("excerpt", "")
    cands = [i for i, r in enumerate(rows) if i not in taken and r["id"] == item["id"] and _same(r["excerpt"], ex)
             and (ctx is None or source_ok(item, r["reason"], **ctx))]
    return min(cands, key=lambda i: abs(len(_norm(rows[i]["excerpt"])) - len(_norm(ex))), default=None)


def _density_row(item: dict, rows: list[dict], taken: set[int], *, advisory: list[dict]) -> int | None:
    """density 行可用 * 或该规则任一命中原文;已被 position 命中占用的行不算。"""
    same_rule = [a.get("excerpt", "") for a in advisory if a["id"] == item["id"] and a.get("scope") == "density"]
    return next((i for i, r in enumerate(rows) if i not in taken and r["id"] == item["id"]
                 and (r["excerpt"].strip() == ANY or any(_same(r["excerpt"], e) for e in same_rule))), None)


def _assign(advisory: list[dict], rows: list[dict], *, ctx: dict | None) -> list[int | None]:
    """每条 advisory 对应的 log 行下标:position 先贪心一对一分配(E2),density 再按规则共用剩下的行。"""
    out: list[int | None] = [None] * len(advisory)
    taken: set[int] = set()
    for n, item in enumerate(advisory):
        if item.get("scope") != "density":
            out[n] = _position_row(item, rows, taken, ctx=ctx)
            if out[n] is not None:
                taken.add(out[n])
    for n, item in enumerate(advisory):
        if item.get("scope") == "density":
            out[n] = _density_row(item, rows, taken, advisory=advisory)
    return out


def keep_cap(han: int | None) -> int:
    return max(KEEP_MIN, (han or 0) // KEEP_HAN_PER)


def uncovered(advisory: list[dict], log_text: str, han: int | None = None, *,
              brief_text: str | None = None, research_text: str | None = None) -> list[dict]:
    """返回未被 log 覆盖的 advisory 条目;保留行数超上限时追加一条 id=_keep_overflow 的说明。

    unsourced_* 的保留理由由 source_check 核对:指向的 brief 行 / 字段 / research 必须存在且和命中对得上。
    """
    keeps = [r for r in parse_log(log_text) if _norm(r["action"]) == "保留" and _reason_ok(r["reason"])]
    ctx = {"brief_text": brief_text, "research_text": research_text}
    out, rows_used, n_pos = [], set(), 0
    for item, i in zip(advisory, _assign(advisory, keeps, ctx=ctx)):
        if i is None:
            need = "带可核对出处的理由" if item["id"].startswith(UNCOUNTED_PREFIX) else "有效理由"
            out.append({**item, "message": f"humanize_log 缺少这条的「保留」行或{need}:{item.get('message', '')}"})
        elif item["id"].startswith(UNCOUNTED_PREFIX):
            continue
        elif item.get("scope") == "density":
            rows_used.add(i)
        else:
            n_pos += 1
    count, cap = len(rows_used) + n_pos, keep_cap(han)
    if count > cap:
        out.append({"id": "_keep_overflow", "label": "保留过多", "line": 0, "kind": "", "excerpt": "", "count": count,
                    "cap": cap, "scope": "position", "message": f"保留 {count} 处,超过上限:请改写,不要靠保留过关"})
    return out


def merge_template(advisory: list[dict], existing: str | None) -> str:
    """生成或补全 log 骨架:已有行不动,只追加尚未覆盖(不论处理列填了什么)的条目。"""
    if not existing or not existing.strip():
        return render_template(advisory)
    assigned = _assign(advisory, parse_log(existing), ctx=None)
    new = [r for r, n in _skeleton(advisory) if assigned[n] is None]
    if _HEADER.split("\n")[0] not in existing:
        existing = existing.rstrip("\n") + "\n\n" + _HEADER
    return existing.rstrip("\n") + "\n" + "".join(_row(r) + "\n" for r in new)


def _read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


def check_article(md_path: str, advisory: list[dict], md_content: str) -> tuple[list[dict], Path]:
    """读文章同目录的 humanize_log.md / brief.md / research.md 做覆盖检查(publish 门禁与 ai_score --check-log 共用)。"""
    base = Path(md_path).parent
    log_path = base / LOG_NAME
    gaps = uncovered(advisory, _read(log_path) or "", han=han_count(mask_markdown(md_content)),
                     brief_text=_read(base / "brief.md"), research_text=_read(base / "research.md"))
    return gaps, log_path
