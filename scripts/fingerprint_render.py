"""fingerprint.py 的人读输出:历史特征表、当前篇与 advisory 列表(从 fingerprint.py 拆出,保持主文件 ≤300 行)。"""
from __future__ import annotations


def _join(v) -> str:
    return "+".join(v) if v else "-"


def _line(f: dict) -> str:
    return (f"{f['name']} | 结构 {f['structure'] or '-'} | 钩子 {f['hook'] or '-'} | 开头 {f['opening']} | "
            f"结尾 {_join(f['ending'])} | 标题 {_join(f['title_shape'])} | 摘要 {_join(f['digest_shape'])} | "
            f"小标题 {f['heading_shape']} {_join(f['heading_keys'])}"
            + (f" | 口头禅族 {_join(sorted(f['tics']))}" if f["tics"] else ""))


def render(res: dict) -> str:
    out = [f"fingerprint · {res['account']} · 历史 {len(res['history'])} 篇", "", "历史特征:"]
    out += [f"  {_line(f)}" for f in res["history"]] or ["  (无)"]
    out += (["", "当前:", f"  {_line(res['current'])}"] if res["current"] else []) + [f"  注:{n}" for n in res["notes"]]
    if res["current"]:
        advs = res["advisories"]
        out += ["", f"advisory {len(advs)} 条" + (":" if advs else "(未发现跨篇重复)")]
        out += [f"  - [{a['id']}] {a['message']}({', '.join(a['articles'])})" for a in advs]
    return "\n".join(out)
