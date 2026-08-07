# -*- coding: utf-8 -*-
"""_paper_figures_audit3.py — 对 _paper_figures_gen3.py 做几何自检（不产出图片）。

做法：monkeypatch Canvas 的 box / line / polyline / text，记录本次绘制的
所有矩形节点与线段，然后做两类硬校验：

  A. 框-框重叠：任意两个矩形节点不得有实质重叠面积。
  B. 线穿框    ：任意线段不得穿过任意矩形节点的“内部”。
     （端点贴在框边沿属正常连线，故把框内缩 INSET 后再判交。）

另外报告画布越界（图元跑到画布外）。
用法：python _paper_figures_audit3.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _paper_figures_lib as LIB  # noqa: E402

INSET = 5.0          # 框内缩量：端点贴边不算穿框
MIN_OVERLAP = 4.0    # 框-框重叠面积阈值（px^2 方向上的边长）


# --------------------------------------------------------------------------
# 记录器
# --------------------------------------------------------------------------
class Rec:
    def __init__(self) -> None:
        self.boxes: list[tuple[tuple[float, float, float, float], str]] = []
        self.segs: list[tuple[tuple[float, float], tuple[float, float]]] = []
        self.texts: list[tuple[tuple[float, float, float, float], str]] = []
        self.canvas_size: tuple[float, float] = (0.0, 0.0)


REC = Rec()

_orig_init = LIB.Canvas.__init__
_orig_box = LIB.Canvas.box
_orig_line = LIB.Canvas.line
_orig_polyline = LIB.Canvas.polyline
_orig_text = LIB.Canvas.text
_orig_save = LIB.Canvas.save


def _init(self, w, h, *a, **k):
    REC.canvas_size = (float(w), float(h))
    return _orig_init(self, w, h, *a, **k)


_IN_BOX = [0]   # 再入计数：box() 内部画的分隔线/虚线边框不算“连线”


def _box(self, rect, lines, *a, **k):
    label = k.get("header") or (lines[0] if isinstance(lines, (list, tuple)) and lines else str(lines))
    REC.boxes.append((tuple(float(v) for v in rect), str(label)[:28]))
    _IN_BOX[0] += 1
    try:
        return _orig_box(self, rect, lines, *a, **k)
    finally:
        _IN_BOX[0] -= 1


def _line(self, p0, p1, *a, **k):
    if not _IN_BOX[0]:
        REC.segs.append(((float(p0[0]), float(p0[1])), (float(p1[0]), float(p1[1]))))
    return _orig_line(self, p0, p1, *a, **k)


def _polyline(self, pts, *a, **k):
    pts = list(pts)
    if not _IN_BOX[0]:
        for i in range(len(pts) - 1):
            REC.segs.append(((float(pts[i][0]), float(pts[i][1])),
                             (float(pts[i + 1][0]), float(pts[i + 1][1]))))
    return _orig_polyline(self, pts, *a, **k)


def _text(self, x, y, s, *a, **k):
    """记录游离文本（非 box 内部文本）的真实包围盒，用于检测压字。"""
    if not _IN_BOX[0] and str(s).strip():
        size = k.get("size", 13)
        anchor = k.get("anchor", "mm")
        f = LIB.font(int(size * self.ss), bold=k.get("bold", False), mono=k.get("mono", False))
        try:
            l, t, r, b = self._d.textbbox((0, 0), str(s), font=f, anchor="la")
            tw, th = (r - l) / self.ss, (b - t) / self.ss
        except Exception:
            tw, th = len(str(s)) * size * 0.7, size * 1.2
        ax = {"l": 0.0, "m": -tw / 2, "r": -tw}.get(anchor[0], -tw / 2)
        ay = {"t": 0.0, "a": 0.0, "m": -th / 2, "s": -th, "b": -th}.get(
            anchor[1] if len(anchor) > 1 else "m", -th / 2)
        REC.texts.append(((x + ax, y + ay, tw, th), str(s)[:26]))
    return _orig_text(self, x, y, s, *a, **k)


def _save(self, path):
    return path  # 审计模式不落盘


def _wrap_node(orig, kind):
    """ellipse_node / diamond / stadium / cylinder 也按矩形节点纳入审计。"""
    def _f(self, rect, lines=None, *a, **k):
        lab = lines if isinstance(lines, str) else (
            lines[0] if isinstance(lines, (list, tuple)) and lines else kind)
        REC.boxes.append((tuple(float(v) for v in rect), str(lab)[:28]))
        _IN_BOX[0] += 1
        try:
            return orig(self, rect, lines, *a, **k) if lines is not None else orig(self, rect, *a, **k)
        finally:
            _IN_BOX[0] -= 1
    return _f


LIB.Canvas.__init__ = _init
LIB.Canvas.box = _box
for _kind in ("ellipse_node", "diamond", "stadium", "cylinder"):
    if hasattr(LIB.Canvas, _kind):
        setattr(LIB.Canvas, _kind, _wrap_node(getattr(LIB.Canvas, _kind), _kind))
LIB.Canvas.line = _line
LIB.Canvas.polyline = _polyline
LIB.Canvas.text = _text
LIB.Canvas.save = _save


# --------------------------------------------------------------------------
# 几何判定
# --------------------------------------------------------------------------
def rect_overlap(a, b):
    ax0, ay0, ax1, ay1 = a[0], a[1], a[0] + a[2], a[1] + a[3]
    bx0, by0, bx1, by1 = b[0], b[1], b[0] + b[2], b[1] + b[3]
    ox = min(ax1, bx1) - max(ax0, bx0)
    oy = min(ay1, by1) - max(ay0, by0)
    if ox > MIN_OVERLAP and oy > MIN_OVERLAP:
        return ox, oy
    return None


def seg_rect_cross(p0, p1, rect, inset=INSET):
    """线段是否穿过矩形内部（内缩 inset 后）。用 Liang-Barsky 裁剪。"""
    x0, y0, w, h = rect
    rx0, ry0 = x0 + inset, y0 + inset
    rx1, ry1 = x0 + w - inset, y0 + h - inset
    if rx1 <= rx0 or ry1 <= ry0:
        return False
    px, py = p0
    qx, qy = p1
    dx, dy = qx - px, qy - py
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, px - rx0), (dx, rx1 - px), (-dy, py - ry0), (dy, ry1 - py)):
        if abs(p) < 1e-12:
            if q < 0:
                return False
            continue
        r = q / p
        if p < 0:
            if r > t1:
                return False
            if r > t0:
                t0 = r
        else:
            if r < t0:
                return False
            if r < t1:
                t1 = r
    # 需要有实质长度的穿越段，避免浮点擦边
    seg_len = ((dx * dx + dy * dy) ** 0.5) * max(0.0, t1 - t0)
    return seg_len > 2.0


def audit(name, fn):
    REC.boxes.clear()
    REC.segs.clear()
    REC.texts.clear()
    fn()
    W, H = REC.canvas_size
    problems = []

    # A. 框-框重叠
    for i in range(len(REC.boxes)):
        for j in range(i + 1, len(REC.boxes)):
            ra, la = REC.boxes[i]
            rb, lb = REC.boxes[j]
            ov = rect_overlap(ra, rb)
            if ov:
                problems.append(f"框重叠 {la} x {lb} -> {ov[0]:.0f}x{ov[1]:.0f}px")

    # B. 线穿框
    cross = {}
    for (p0, p1) in REC.segs:
        for rect, lab in REC.boxes:
            if seg_rect_cross(p0, p1, rect):
                cross[lab] = cross.get(lab, 0) + 1
    for lab, n in sorted(cross.items(), key=lambda kv: -kv[1]):
        problems.append(f"线穿框 {lab} <- {n} 条线段")

    # C. 游离文本压框（BUG#3 类问题：箭头标签盖住框内文字）
    for trect, ts in REC.texts:
        for brect, bl in REC.boxes:
            ov = rect_overlap(trect, brect)
            if ov:
                problems.append(
                    f"文字压框 \"{ts}\" 压在 [{bl}] 上 -> {ov[0]:.0f}x{ov[1]:.0f}px")

    # C2. 游离文本互相压字
    for i in range(len(REC.texts)):
        for j in range(i + 1, len(REC.texts)):
            ra, sa = REC.texts[i]
            rb, sb = REC.texts[j]
            ov = rect_overlap(ra, rb)
            if ov:
                problems.append(
                    f"文字互压 \"{sa}\" x \"{sb}\" -> {ov[0]:.0f}x{ov[1]:.0f}px")

    # D. 越界
    oob = 0
    for rect, lab in REC.boxes:
        if rect[0] < 0 or rect[1] < 0 or rect[0] + rect[2] > W or rect[1] + rect[3] > H:
            problems.append(f"框越界 {lab} rect={rect} canvas=({W:.0f},{H:.0f})")
    for (p0, p1) in REC.segs:
        for (x, y) in (p0, p1):
            if x < -1 or y < -1 or x > W + 1 or y > H + 1:
                oob += 1
    if oob:
        problems.append(f"线端点越界 {oob} 个")

    status = "PASS" if not problems else "FAIL"
    print(f"[{status}] {name}  canvas={W:.0f}x{H:.0f}  "
          f"框={len(REC.boxes)} 线段={len(REC.segs)} 游离文本={len(REC.texts)}")
    for p in problems:
        print(f"        - {p}")
    return not problems


def main() -> int:
    import _paper_figures_gen3 as G

    cases = [
        ("图3.4 用例图", G.fig_use_case),
        ("图3.5 序列图", G.fig_sequence),
        ("图3.7 状态图", G.fig_state),
        ("图3.9 E-R图", G.fig_er),
        ("图3.10 类图", G.fig_class),
        ("图3.11 部署图", G.fig_deploy),
        ("图4.1 流程图", G.fig_flow),
        ("图4.2 伪代码", G.fig_pseudocode),
    ]
    ok = True
    for name, fn in cases:
        ok = audit(name, fn) and ok
    print()
    print("== 几何自检总判定：", "全部通过 PASS" if ok else "存在问题 FAIL", "==")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
