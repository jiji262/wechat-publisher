"""字符层检测:排版伪影(空格破折号/半角漂移)、零宽与双向控制字符(可清洗)、同形字(硬门)。

D2:硬门只认同形字;零宽/双向控制字符是 artifacts 计分项 zero_width,并在打分与发布前剥离。
"""
from __future__ import annotations

import re

import zh_text as T

# ---------- 排版伪影 ----------
# 署名行(—— 鲁迅 / -- 作者);单个 ASCII "-" 是列表标记,不算署名破折号
ATTRIB_LINE = re.compile(r"(?m)^[^\S\n]*(?:>[^\S\n]*)*(?:—{1,2}|--)[^\S\n]*\S.*$")
SPACED_DASH = re.compile(r"[^\S\n]\u2014{1,2}|\u2014{1,2}[^\S\n]|(?<=[\u4e00-\u9fff])[^\S\n]?--[^\S\n]?(?=[\u4e00-\u9fff])")
HALF_DRIFT = re.compile(r"(?m)[一-鿿][,:;?!](?=[一-鿿A-Za-z \t]|$)")
FULL_PUNCT = re.compile(r"[\uff0c\uff1a\uff1b\uff1f\uff01]")
DASH_CONTEXT = 3                    # 破折号前后 3 字内有汉字才算(英文引文里的 — 不算)

# ---------- 零宽 / 双向控制(可清洗,计分不拦截) ----------
_EMOJI = "\U0001F000-\U0001FAFF\u2600-\u27bf\ufe0f\U0001F3FB-\U0001F3FF"
ZERO_WIDTH = re.compile(
    "[\u00ad\u180e\u200b\u200c\u200e\u200f\u2060-\u2064\u202a-\u202e\u2066-\u2069\u3164\ufeff]"
    f"|(?<![{_EMOJI}])\u200d|\u200d(?![{_EMOJI}])"     # emoji 组合里的 ZWJ 合法
)

# ---------- 同形字(硬门) ----------
# 与拉丁字母视觉上不可分的西里尔/希腊字母;α β μ π 等不在内(科技文里常与汉字相邻,合法)
LOOKALIKE = set("\u0430\u0435\u043e\u0440\u0441\u0443\u0445\u0456\u0458\u0455\u0501\u04bb"
                "\u0410\u0412\u0415\u041a\u041c\u041d\u041e\u0420\u0421\u0422\u0425\u0406\u0408\u0405"
                "\u0391\u0392\u0395\u0396\u0397\u0399\u039a\u039c\u039d\u039f\u03a1\u03a4\u03a5\u03a7\u03bf")
_FOREIGN = re.compile("[\u0370-\u03ff\u0400-\u052f]")
_TOKEN = re.compile("[A-Za-z\u0370-\u03ff\u0400-\u052f]+")
_HAN = re.compile("[\u4e00-\u9fff]")
GRK_SAND = re.compile("(?<=[A-Za-z])[\u0370-\u03ff](?=[A-Za-z])")
RADICAL = re.compile("[\u2e80-\u2eff\u2f00-\u2fdf]")
LOOKALIKE_WORD_MIN = 2              # 整词由形似字母组成、长度 ≥2 即判同形字
HARD_RADICAL_MIN = 3                # 康熙部首(汉字同形)≥3 处才判硬,零星的多是 PDF 复制残留


def _line(t: str, pos: int) -> int:
    return T.line_offset(t, pos) + 1


def strip_zero_width(md: str) -> tuple[str, int]:
    """剥离零宽/双向控制字符(不含 emoji ZWJ),返回 (清洗后文本, 剥离个数;文首 BOM 不计)。"""
    lead = md.startswith("\ufeff")
    clean, n = ZERO_WIDTH.subn("", md)
    return clean, n - lead


def zero_width_hits(md: str) -> list[dict]:
    """零宽/双向控制字符位置(文首 BOM 除外),供 artifacts.zero_width 计分。"""
    t = md[1:] if md.startswith("\ufeff") else md
    return [{"id": "zero_width", "line": _line(t, m.start()),
             "excerpt": f"U+{ord(m.group(0)):04X} 于「{' '.join(t[max(0, m.start() - 6):m.start()].split())}」之后"}
            for m in ZERO_WIDTH.finditer(t)]


def _homoglyph_token(t: str, m: re.Match) -> bool:
    """词里有形似拉丁的西里尔/希腊字母,且没有其他外文字母,并夹在拉丁词里或紧邻汉字。"""
    tok = m.group(0)
    foreign = _FOREIGN.findall(tok)
    if not foreign or any(c not in LOOKALIKE for c in foreign):
        return False
    if len(tok) >= LOOKALIKE_WORD_MIN and len(foreign) == len(tok):
        return True                 # 整词都是形似拉丁的字母(空格隔开的 ΑΙ):正常希腊字母多是单字 α/λ/Δ
    near_han = bool(_HAN.match(t[m.start() - 1:m.start()] or " ") or _HAN.match(t[m.end():m.end() + 1] or " "))
    return bool(re.search(r"[A-Za-z]", tok)) or near_han


def find_homoglyphs(text: str) -> list[dict]:
    """同形字命中:混入拉丁词/紧邻汉字的形似字母;康熙部首 ≥ HARD_RADICAL_MIN 处时全部列出。"""
    out = [{"type": "homoglyph", "line": _line(text, m.start()), "excerpt": m.group(0),
            "codepoint": " ".join(f"U+{ord(c):04X}" for c in m.group(0) if _FOREIGN.match(c))}
           for m in _TOKEN.finditer(text) if _homoglyph_token(text, m)]
    radicals = list(RADICAL.finditer(text))
    if len(radicals) >= HARD_RADICAL_MIN:
        out += [{"type": "radical", "line": _line(text, m.start()), "excerpt": text[max(0, m.start() - 4):m.end() + 4],
                 "codepoint": f"U+{ord(m.group(0)):04X}"} for m in radicals]
    return out


def typography(md: str, *, drift_min: int, drift_ratio: float) -> list[dict]:
    """空格包围的破折号(署名行除外)、半角标点漂移、零星的希腊夹心/康熙部首(疑似粘贴残留)。"""
    t = ATTRIB_LINE.sub("", T.mask_markdown(md, fill="█"))
    out = [{"id": "spaced_dash", "line": _line(t, m.start()), "excerpt": T.excerpt(t, m.start(), m.end())}
           for m in SPACED_DASH.finditer(t)
           if T.han_count(t[max(0, m.start() - DASH_CONTEXT):m.end() + DASH_CONTEXT])]
    h, f = len(HALF_DRIFT.findall(t)), len(FULL_PUNCT.findall(t))
    if h >= drift_min and h / (h + f) >= drift_ratio and "。" in t:
        out.append({"id": "halfwidth_drift", "line": 0, "excerpt": f"半角标点 {h} 处 / 全角 {f} 处"})
    soft = list(GRK_SAND.finditer(md)) + list(RADICAL.finditer(md))
    if soft and len(list(RADICAL.finditer(md))) < HARD_RADICAL_MIN:
        out.append({"id": "soft_adversarial", "line": _line(md, soft[0].start()), "excerpt": "疑似粘贴残留,建议删除或 NFKC 归一"})
    return out
