"""行内标记的位置计算:命中是否"整句被高亮",按位置判断,不按文字(只标了产品名不算)。"""
from __future__ import annotations

from zh_text import _ITALIC_RE, MARK_RES

_OPEN, _CLOSE = "\ue000", "\ue001"      # 私用区哨兵,标出标记内容在去标记文本里的位置
MARKER_COVER_MIN = 0.5                   # 命中至少一半落在某个标记里,才算"整句被高亮"


def marker_ranges(marked: str) -> list[tuple[int, int]]:
    """行内标记内容在 strip_markers(marked) 坐标系里的区间。"""
    s = marked
    for _ in range(2):  # 与 strip_markers 同样处理一层嵌套
        for rx in MARK_RES:
            s = rx.sub(lambda m: _OPEN + m.group(1) + _CLOSE, s)
    s = _ITALIC_RE.sub(r"\1", s)
    out, stack, removed = [], [], 0
    for i, ch in enumerate(s):
        if ch == _OPEN:
            stack.append(i - removed)
            removed += 1
        elif ch == _CLOSE:
            if stack:
                out.append((stack.pop(), i - removed))
            removed += 1
    return out


def in_marker(span: tuple[int, int], ranges: list[tuple[int, int]]) -> bool:
    """命中区间是否有一半以上落在某个行内标记里(按位置,不按文字:只标了产品名不算)。"""
    s, e = span
    length = max(1, e - s)
    return any((min(e, re_) - max(s, rs)) / length >= MARKER_COVER_MIN for rs, re_ in ranges)
