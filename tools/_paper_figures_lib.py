# -*- coding: utf-8 -*-
"""_paper_figures_lib.py — 论文插图绘制基础库（Pillow 实现，无需 Graphviz dot）。

设计动机：
    本机未安装 Graphviz 的 `dot` 可执行文件（仅装了 Python 绑定 graphviz==0.21，
    绑定本身不含渲染引擎），因此按既定降级方案改用 Pillow 手绘。
    相比 dot 自动布局，本库采用**显式坐标布局**，好处是：
      1) 中文字体（msyh/simhei）100% 可控，绝不出现方块乱码；
      2) 输出尺寸精确可控，便于与 docx 原图版面对齐；
      3) 结果确定可复现，重复运行像素级一致。

对外能力：
    Canvas       —— 画布 + 抗锯齿（4x 超采样后缩放）
    Canvas.box            矩形/圆角矩形节点（支持多行文本、标题栏）
    Canvas.ellipse_node   椭圆节点（用例图）
    Canvas.diamond        菱形判定节点（流程图）
    Canvas.stadium        胶囊形起止节点（流程图/状态图）
    Canvas.actor          小人图标（用例图角色）
    Canvas.arrow          直线箭头（支持虚线、标签、正交折线）
    Canvas.text           自由文本
    Canvas.lane           泳道背景

坐标系：统一使用**逻辑像素**，最终按 SS 倍超采样渲染再降采样。
"""
from __future__ import annotations

import math
import os
from typing import Iterable, List, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------------
# 字体
# --------------------------------------------------------------------------
_FONT_DIR = r"C:\Windows\Fonts"
_CJK_CANDIDATES: Tuple[Tuple[str, int], ...] = (
    ("msyh.ttc", 0),
    ("simhei.ttf", 0),
    ("simsun.ttc", 0),
    ("Deng.ttf", 0),
)
_CJK_BOLD_CANDIDATES: Tuple[Tuple[str, int], ...] = (
    ("msyhbd.ttc", 0),
    ("simhei.ttf", 0),
    ("Dengb.ttf", 0),
)
_MONO_CANDIDATES: Tuple[Tuple[str, int], ...] = (
    ("consola.ttf", 0),
    ("cour.ttf", 0),
)

_font_cache: dict = {}


def _pick(candidates: Sequence[Tuple[str, int]]) -> Tuple[str, int] | None:
    """在候选字体中挑第一个实际存在的。"""
    for name, index in candidates:
        path = os.path.join(_FONT_DIR, name)
        if os.path.exists(path):
            return path, index
    return None


CJK_FONT = _pick(_CJK_CANDIDATES)
CJK_BOLD_FONT = _pick(_CJK_BOLD_CANDIDATES)
MONO_FONT = _pick(_MONO_CANDIDATES)
HAS_CJK: bool = CJK_FONT is not None


def font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    """按字号取字体对象（带缓存）。找不到中文字体时回退 Pillow 默认位图字体。"""
    key = (size, bold, mono)
    cached = _font_cache.get(key)
    if cached is not None:
        return cached
    spec = MONO_FONT if mono else (CJK_BOLD_FONT if bold else CJK_FONT)
    if spec is None:
        spec = CJK_FONT or CJK_BOLD_FONT
    if spec is None:
        f = ImageFont.load_default()
    else:
        path, index = spec
        try:
            f = ImageFont.truetype(path, size, index=index)
        except Exception:
            f = ImageFont.load_default()
    _font_cache[key] = f
    return f


# --------------------------------------------------------------------------
# 配色（论文黑白打印友好：低饱和填充 + 深色描边）
# --------------------------------------------------------------------------
class C:
    """统一配色常量。"""

    BG = (255, 255, 255)
    LINE = (60, 66, 78)
    TEXT = (28, 32, 40)
    MUTED = (110, 118, 132)

    BLUE_F = (222, 235, 250)
    BLUE_S = (52, 108, 176)
    GREEN_F = (223, 244, 228)
    GREEN_S = (46, 138, 78)
    ORANGE_F = (253, 238, 216)
    ORANGE_S = (196, 122, 32)
    PURPLE_F = (235, 229, 248)
    PURPLE_S = (110, 82, 170)
    GRAY_F = (240, 242, 245)
    GRAY_S = (130, 138, 150)
    RED_F = (252, 226, 226)
    RED_S = (186, 62, 62)
    YELLOW_F = (255, 248, 214)
    YELLOW_S = (176, 148, 30)
    TEAL_F = (219, 243, 243)
    TEAL_S = (34, 134, 134)


Color = Tuple[int, int, int]
Point = Tuple[float, float]
Rect = Tuple[float, float, float, float]  # x, y, w, h


# --------------------------------------------------------------------------
# 画布
# --------------------------------------------------------------------------
class Canvas:
    """超采样抗锯齿画布。所有绘制 API 使用逻辑像素坐标。"""

    def __init__(self, width: int, height: int, ss: int = 3, bg: Color = C.BG) -> None:
        self.w: int = int(width)
        self.h: int = int(height)
        self.ss: int = int(ss)
        self._img = Image.new("RGB", (self.w * self.ss, self.h * self.ss), bg)
        self._d = ImageDraw.Draw(self._img)

    # ---------------- 内部工具 ----------------
    def _s(self, v: float) -> float:
        return v * self.ss

    def _xy(self, pts: Iterable[Point]) -> List[float]:
        out: List[float] = []
        for x, y in pts:
            out.extend([x * self.ss, y * self.ss])
        return out

    def text_size(self, s: str, f: ImageFont.FreeTypeFont) -> Tuple[float, float]:
        """返回逻辑像素下的文本宽高。"""
        box = self._d.textbbox((0, 0), s, font=f)
        return (box[2] - box[0]) / self.ss, (box[3] - box[1]) / self.ss

    # ---------------- 基础图元 ----------------
    def text(
        self,
        x: float,
        y: float,
        s: str,
        size: int = 13,
        color: Color = C.TEXT,
        bold: bool = False,
        mono: bool = False,
        anchor: str = "mm",
    ) -> None:
        """绘制单行文本。anchor 遵循 Pillow 语义（lt/mm/ma/lm ...）。"""
        f = font(int(size * self.ss), bold=bold, mono=mono)
        self._d.text((self._s(x), self._s(y)), s, font=f, fill=color, anchor=anchor)

    def multiline(
        self,
        x: float,
        y: float,
        lines: Sequence[str],
        size: int = 12,
        color: Color = C.TEXT,
        bold: bool = False,
        mono: bool = False,
        anchor: str = "mm",
        leading: float = 1.42,
    ) -> float:
        """居中/左对齐绘制多行文本，返回总高度（逻辑像素）。"""
        lh = size * leading
        total = lh * len(lines)
        top = y - total / 2 + lh / 2
        for i, ln in enumerate(lines):
            self.text(x, top + i * lh, ln, size=size, color=color, bold=bold, mono=mono, anchor=anchor)
        return total

    def line(
        self,
        p0: Point,
        p1: Point,
        color: Color = C.LINE,
        width: float = 1.4,
        dash: Tuple[int, int] | None = None,
    ) -> None:
        """直线，支持虚线 dash=(实,虚)。"""
        if dash is None:
            self._d.line(self._xy([p0, p1]), fill=color, width=max(1, int(self._s(width))))
            return
        x0, y0 = p0
        x1, y1 = p1
        dist = math.hypot(x1 - x0, y1 - y0)
        if dist <= 0:
            return
        ux, uy = (x1 - x0) / dist, (y1 - y0) / dist
        on, off = dash
        pos = 0.0
        while pos < dist:
            seg = min(on, dist - pos)
            a = (x0 + ux * pos, y0 + uy * pos)
            b = (x0 + ux * (pos + seg), y0 + uy * (pos + seg))
            self._d.line(self._xy([a, b]), fill=color, width=max(1, int(self._s(width))))
            pos += on + off

    def polyline(
        self,
        pts: Sequence[Point],
        color: Color = C.LINE,
        width: float = 1.4,
        dash: Tuple[int, int] | None = None,
    ) -> None:
        """折线。"""
        for i in range(len(pts) - 1):
            self.line(pts[i], pts[i + 1], color=color, width=width, dash=dash)

    def arrow_head(self, tip: Point, direction: Point, color: Color = C.LINE, size: float = 8.0,
                   hollow: bool = False) -> None:
        """在 tip 处画箭头，direction 为单位方向向量（指向 tip 前进方向）。"""
        dx, dy = direction
        norm = math.hypot(dx, dy) or 1.0
        dx, dy = dx / norm, dy / norm
        px, py = -dy, dx
        base = (tip[0] - dx * size, tip[1] - dy * size)
        a = (base[0] + px * size * 0.46, base[1] + py * size * 0.46)
        b = (base[0] - px * size * 0.46, base[1] - py * size * 0.46)
        if hollow:
            self._d.polygon(self._xy([tip, a, b]), fill=C.BG, outline=color,
                            width=max(1, int(self._s(1.2))))
        else:
            self._d.polygon(self._xy([tip, a, b]), fill=color)

    # ---------------- 节点 ----------------
    def box(
        self,
        rect: Rect,
        lines: Sequence[str] | str,
        fill: Color = C.BLUE_F,
        stroke: Color = C.BLUE_S,
        size: int = 13,
        bold: bool = False,
        radius: float = 8.0,
        text_color: Color = C.TEXT,
        width: float = 1.6,
        header: str | None = None,
        header_fill: Color | None = None,
        body_size: int | None = None,
        body_align_left: bool = False,
        mono: bool = False,
        dash: bool = False,
    ) -> Rect:
        """矩形节点。header 非空时绘制标题栏（类图/表节点用）。"""
        x, y, w, h = rect
        sw = max(1, int(self._s(width)))
        if dash:
            # 虚线边框矩形（用于"未接线/可选"组件）
            self._d.rounded_rectangle(self._xy([(x, y), (x + w, y + h)]),
                                      radius=self._s(radius), fill=fill)
            corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
            self.polyline(corners, color=stroke, width=width, dash=(6, 4))
        else:
            self._d.rounded_rectangle(self._xy([(x, y), (x + w, y + h)]),
                                      radius=self._s(radius), fill=fill,
                                      outline=stroke, width=sw)
        if isinstance(lines, str):
            lines = [lines]
        if header is not None:
            hh = size * 1.9
            hf = header_fill if header_fill is not None else stroke
            self._d.rounded_rectangle(self._xy([(x, y), (x + w, y + hh)]),
                                      radius=self._s(radius), fill=hf)
            self._d.rectangle(self._xy([(x, y + hh - radius), (x + w, y + hh)]), fill=hf)
            self.text(x + w / 2, y + hh / 2, header, size=size, color=(255, 255, 255), bold=True)
            self.line((x, y + hh), (x + w, y + hh), color=stroke, width=width)
            bs = body_size if body_size is not None else max(9, size - 2)
            if lines:
                if body_align_left:
                    lh = bs * 1.5
                    top = y + hh + lh * 0.72
                    for i, ln in enumerate(lines):
                        self.text(x + 8, top + i * lh, ln, size=bs, color=text_color,
                                  anchor="lm", mono=mono)
                else:
                    self.multiline(x + w / 2, y + hh + (h - hh) / 2, lines, size=bs,
                                   color=text_color, mono=mono)
        else:
            self.multiline(x + w / 2, y + h / 2, lines, size=size, color=text_color,
                           bold=bold, mono=mono)
        return rect

    def stadium(self, rect: Rect, lines: Sequence[str] | str, fill: Color = C.GREEN_F,
                stroke: Color = C.GREEN_S, size: int = 13, bold: bool = True) -> Rect:
        """胶囊形（起止节点）。"""
        x, y, w, h = rect
        self._d.rounded_rectangle(self._xy([(x, y), (x + w, y + h)]), radius=self._s(h / 2),
                                  fill=fill, outline=stroke, width=max(1, int(self._s(1.6))))
        if isinstance(lines, str):
            lines = [lines]
        self.multiline(x + w / 2, y + h / 2, lines, size=size, bold=bold)
        return rect

    def diamond(self, rect: Rect, lines: Sequence[str] | str, fill: Color = C.YELLOW_F,
                stroke: Color = C.YELLOW_S, size: int = 12) -> Rect:
        """菱形判定节点。"""
        x, y, w, h = rect
        pts = [(x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2)]
        self._d.polygon(self._xy(pts), fill=fill, outline=stroke,
                        width=max(1, int(self._s(1.6))))
        if isinstance(lines, str):
            lines = [lines]
        self.multiline(x + w / 2, y + h / 2, lines, size=size, bold=True)
        return rect

    def ellipse_node(self, rect: Rect, lines: Sequence[str] | str, fill: Color = C.BLUE_F,
                     stroke: Color = C.BLUE_S, size: int = 12) -> Rect:
        """椭圆节点（用例）。"""
        x, y, w, h = rect
        self._d.ellipse(self._xy([(x, y), (x + w, y + h)]), fill=fill, outline=stroke,
                        width=max(1, int(self._s(1.5))))
        if isinstance(lines, str):
            lines = [lines]
        self.multiline(x + w / 2, y + h / 2, lines, size=size)
        return rect

    def actor(self, cx: float, cy: float, label: str, scale: float = 1.0,
              color: Color = C.LINE, size: int = 13) -> None:
        """UML 小人图标，(cx, cy) 为身体中心，label 画在下方。"""
        r = 9 * scale
        body = 26 * scale
        arm = 15 * scale
        leg = 16 * scale
        w = 2.0
        top = cy - body / 2 - r
        self._d.ellipse(self._xy([(cx - r, top), (cx + r, top + 2 * r)]), fill=C.BG,
                        outline=color, width=max(1, int(self._s(w))))
        neck = top + 2 * r
        hip = neck + body
        self.line((cx, neck), (cx, hip), color=color, width=w)
        self.line((cx - arm, neck + body * 0.30), (cx + arm, neck + body * 0.30), color=color, width=w)
        self.line((cx, hip), (cx - arm * 0.85, hip + leg), color=color, width=w)
        self.line((cx, hip), (cx + arm * 0.85, hip + leg), color=color, width=w)
        self.text(cx, hip + leg + size * 0.95, label, size=size, bold=True, color=C.TEXT)

    def cylinder(self, rect: Rect, lines: Sequence[str] | str, fill: Color = C.TEAL_F,
                 stroke: Color = C.TEAL_S, size: int = 12) -> Rect:
        """圆柱体（数据库）。"""
        x, y, w, h = rect
        ry = min(14.0, h * 0.16)
        sw = max(1, int(self._s(1.6)))
        self._d.rectangle(self._xy([(x, y + ry), (x + w, y + h - ry)]), fill=fill)
        self._d.ellipse(self._xy([(x, y + h - 2 * ry), (x + w, y + h)]), fill=fill,
                        outline=stroke, width=sw)
        self._d.rectangle(self._xy([(x, y + ry), (x + w, y + h - ry)]), fill=fill)
        self.line((x, y + ry), (x, y + h - ry), color=stroke, width=1.6)
        self.line((x + w, y + ry), (x + w, y + h - ry), color=stroke, width=1.6)
        self._d.ellipse(self._xy([(x, y), (x + w, y + 2 * ry)]), fill=fill,
                        outline=stroke, width=sw)
        if isinstance(lines, str):
            lines = [lines]
        self.multiline(x + w / 2, y + h / 2 + ry * 0.35, lines, size=size, bold=True)
        return rect

    def lane(self, rect: Rect, title: str, fill: Color = C.GRAY_F, stroke: Color = C.GRAY_S,
             size: int = 13, title_fill: Color | None = None) -> Rect:
        """泳道背景 + 顶部标题条。"""
        x, y, w, h = rect
        th = size * 2.1
        self._d.rounded_rectangle(self._xy([(x, y), (x + w, y + h)]), radius=self._s(6),
                                  fill=fill, outline=stroke, width=max(1, int(self._s(1.2))))
        tf = title_fill if title_fill is not None else stroke
        self._d.rounded_rectangle(self._xy([(x, y), (x + w, y + th)]), radius=self._s(6), fill=tf)
        self._d.rectangle(self._xy([(x, y + th - 6), (x + w, y + th)]), fill=tf)
        self.text(x + w / 2, y + th / 2, title, size=size, bold=True, color=(255, 255, 255))
        return rect

    # ---------------- 连线 ----------------
    def arrow(
        self,
        p0: Point,
        p1: Point,
        color: Color = C.LINE,
        width: float = 1.5,
        dash: Tuple[int, int] | None = None,
        label: str | None = None,
        label_size: int = 11,
        label_offset: Tuple[float, float] = (0, -9),
        label_bg: bool = True,
        head: bool = True,
        head_size: float = 8.0,
        hollow_head: bool = False,
        label_color: Color = C.TEXT,
    ) -> None:
        """两点间直线箭头（可带标签底衬，避免压线看不清）。"""
        self.line(p0, p1, color=color, width=width, dash=dash)
        if head:
            self.arrow_head(p1, (p1[0] - p0[0], p1[1] - p0[1]), color=color,
                            size=head_size, hollow=hollow_head)
        if label:
            mx, my = (p0[0] + p1[0]) / 2 + label_offset[0], (p0[1] + p1[1]) / 2 + label_offset[1]
            self._label(mx, my, label, label_size, label_bg, label_color)

    def elbow(
        self,
        pts: Sequence[Point],
        color: Color = C.LINE,
        width: float = 1.5,
        dash: Tuple[int, int] | None = None,
        label: str | None = None,
        label_at: int = 0,
        label_size: int = 11,
        label_offset: Tuple[float, float] = (0, -9),
        head: bool = True,
        head_size: float = 8.0,
        label_bg: bool = True,
        label_color: Color = C.TEXT,
    ) -> None:
        """正交折线箭头。label_at 指定标签落在第几段的中点。"""
        self.polyline(pts, color=color, width=width, dash=dash)
        if head and len(pts) >= 2:
            a, b = pts[-2], pts[-1]
            self.arrow_head(b, (b[0] - a[0], b[1] - a[1]), color=color, size=head_size)
        if label and len(pts) >= 2:
            i = max(0, min(label_at, len(pts) - 2))
            mx = (pts[i][0] + pts[i + 1][0]) / 2 + label_offset[0]
            my = (pts[i][1] + pts[i + 1][1]) / 2 + label_offset[1]
            self._label(mx, my, label, label_size, label_bg, label_color)

    def _label(self, x: float, y: float, s: str, size: int, bg: bool, color: Color) -> None:
        """带白底衬的连线标签。"""
        lines = s.split("\n")
        if bg:
            f = font(int(size * self.ss))
            wmax = 0.0
            for ln in lines:
                bx = self._d.textbbox((0, 0), ln, font=f)
                wmax = max(wmax, (bx[2] - bx[0]) / self.ss)
            hh = size * 1.34 * len(lines)
            pad = 2.6
            self._d.rectangle(
                self._xy([(x - wmax / 2 - pad, y - hh / 2 - pad),
                          (x + wmax / 2 + pad, y + hh / 2 + pad)]),
                fill=C.BG)
        self.multiline(x, y, lines, size=size, color=color, leading=1.34)

    # ---------------- 输出 ----------------
    def save(self, path: str) -> str:
        """降采样并保存 PNG。"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        out = self._img.resize((self.w, self.h), Image.LANCZOS)
        out.save(path, "PNG", optimize=True)
        return path


# --------------------------------------------------------------------------
# 便捷几何
# --------------------------------------------------------------------------
def top(r: Rect) -> Point:
    """矩形上边中点。"""
    return (r[0] + r[2] / 2, r[1])


def bottom(r: Rect) -> Point:
    """矩形下边中点。"""
    return (r[0] + r[2] / 2, r[1] + r[3])


def left(r: Rect) -> Point:
    """矩形左边中点。"""
    return (r[0], r[1] + r[3] / 2)


def right(r: Rect) -> Point:
    """矩形右边中点。"""
    return (r[0] + r[2], r[1] + r[3] / 2)


def center(r: Rect) -> Point:
    """矩形中心。"""
    return (r[0] + r[2] / 2, r[1] + r[3] / 2)


def offset(p: Point, dx: float = 0.0, dy: float = 0.0) -> Point:
    """点偏移。"""
    return (p[0] + dx, p[1] + dy)
