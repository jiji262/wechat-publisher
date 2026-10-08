"""
指令回声守卫:写给写作者看的文档里,不得出现可以照抄的口头禅/例句。

旧清单和旧 voice 里的示例句(zh_tells.INSTRUCTION_ECHO)与口头禅族(zh_tells.TICS)
曾被逐字复用成跨篇指纹。这里锁死它们不再写回指令文件,口径与检测器一致:
- 口头禅族按 zh_rules.TIC_PATTERNS 的正则认(带排除,「用起来很顺手」不算);
- 指令回声按原句 + zh_rules.ECHO_RE(检测器用的变体正则,「其实也挺简单」也算);
- 研究者动作族(TICS 里没有专门正则的部分)按字面认。
- SKILL.md / README.md / brief.md.example / wechat-publisher.yaml.example /
  references/*.md / assets/**/*.md 一律不得出现;
- references/anti-ai-checklist.md 例外:只允许出现在以 "✗" 开头的反例行上
  (允许前导空白、"- "、"| ")。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import zh_rules
import zh_tells

ROOT = Path(__file__).resolve().parent.parent
TOP_FILES = ("SKILL.md", "README.md", "brief.md.example", "wechat-publisher.yaml.example")
CHECKLIST = "references/anti-ai-checklist.md"
NEGATIVE_LINE = re.compile(r"^\s*(?:[-|]\s*)?✗")

# 已知、尚未修复的命中(文件不在本轮任何改动范围内)。修好后删掉对应条目即可;
# 守卫只拦"新增",不因这里的条目被修掉而失败。
KNOWN = {
    ("assets/theme-previews/sample.md", "说实话"),   # 主题预览样稿,待改写
}


def _guarded_files() -> list[Path]:
    files = [ROOT / f for f in TOP_FILES]
    files += sorted((ROOT / "references").glob("*.md"))
    files += sorted((ROOT / "assets").glob("**/*.md"))
    return [f for f in files if f.is_file()]


def _norm(s: str) -> str:
    """去空白、全角逗号归一,防止换个标点/空格就绕过。"""
    return re.sub(r"\s+", "", s).replace("，", ",")


LITERALS = tuple(dict.fromkeys(_norm(p) for p in (*zh_tells.INSTRUCTION_ECHO, *zh_tells.TICS)
                               if p not in zh_rules.TIC_PATTERNS))
PATTERNS = (*zh_rules.TIC_PATTERNS.items(), ("指令回声变体", zh_rules.ECHO_RE))


def _hits(flat: str) -> set[str]:
    """一行(已归一)里命中的短语;正则命中报词族名,便于在 KNOWN 里登记。"""
    found = {p for p in LITERALS if p in flat}
    return found | {name for name, rx in PATTERNS if rx.search(flat)}


def _violations(path: Path, root: Path = ROOT) -> list[tuple[str, int, str]]:
    rel = path.relative_to(root).as_posix()
    out = []
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if rel == CHECKLIST and NEGATIVE_LINE.match(line):
            continue
        out += [(rel, no, p) for p in sorted(_hits(_norm(line))) if (rel, p) not in KNOWN]
    return out


def test_phrase_lists_are_loaded():
    assert zh_tells.INSTRUCTION_ECHO and zh_tells.TICS
    assert ROOT.joinpath(CHECKLIST).is_file()


def test_guard_covers_expected_files():
    rels = {f.relative_to(ROOT).as_posix() for f in _guarded_files()}
    assert {"SKILL.md", "README.md", CHECKLIST} <= rels


@pytest.mark.parametrize("path", _guarded_files(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_no_instruction_echo(path):
    hits = _violations(path)
    assert not hits, "指令文件里出现了可照抄的口头禅/例句:\n" + "\n".join(
        f"  {rel}:{no}  「{p}」" for rel, no, p in hits)


def test_checklist_exemption_only_on_negative_lines(tmp_path):
    """守卫自测:checklist 里 ✗ 行放行,普通行照拦;换全角逗号/加空格也拦得住。"""
    phrase = next(p for p in zh_tells.INSTRUCTION_ECHO if "," in p)
    variant = phrase.replace(",", "， ")
    (tmp_path / "references").mkdir()
    doc = tmp_path / CHECKLIST
    doc.write_text(f"- ✗ {phrase}\n| ✗ {phrase} |\n  ✗{phrase}\n普通说明:{variant}\n", encoding="utf-8")
    other = tmp_path / "SKILL.md"
    other.write_text(f"✗ {phrase}\n", encoding="utf-8")
    assert {no for _, no, _ in _violations(doc, tmp_path)} == {4}
    assert {no for _, no, _ in _violations(other, tmp_path)} == {1}, "✗ 豁免只对 checklist 生效"


def test_guard_follows_detector_patterns(tmp_path):
    """守卫自测:变体照拦(ECHO_RE),检测器排除的正常用法放行(TIC_PATTERNS 的排除),研究者动作族按字面拦。"""
    research = next(t for t in zh_tells.TICS if t not in zh_rules.TIC_PATTERNS)
    doc = tmp_path / "SKILL.md"
    doc.write_text(f"其实也挺简单的\n这个快捷键用起来很顺手\n{research}三份日志\n他没说实话\n", encoding="utf-8")
    assert [(no, p) for _, no, p in _violations(doc, tmp_path)] == [(1, "指令回声变体"), (3, _norm(research))]
