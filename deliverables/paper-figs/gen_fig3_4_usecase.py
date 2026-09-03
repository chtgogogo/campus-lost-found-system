# -*- coding: utf-8 -*-
"""生成 图3.4 系统用例图（替换原位图）。

用例名严格取自论文正文 para#123：
  失主       ：发布失物 / 查看匹配 / 认领 / 验证交接码 / IM 沟通
  拾得者     ：发布拾物 / 确认归还 / 生成交接码 / IM 沟通
  管理员     ：审计时间线 / 封禁 / 分类管理
  未登录用户 ：浏览公示栏  —— 改为公开用例（不连 actor）

与原图差异：删除“游客”参与者，参与者恒为 3 个（失主/拾得者/管理员）；
原属游客的“浏览公示栏”降级为无需登录的公开用例。

输出：
  fig3_4_usecase.svg  （手写合法 SVG，Word 可直接插入）
  fig3_4_usecase.png  （matplotlib 栅格化，300 dpi；失败则仅交付 SVG）
"""
from __future__ import annotations

import io
import os
import sys
from typing import Dict, List, Tuple
from xml.sax.saxutils import escape

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

OUT_DIR: str = os.path.dirname(os.path.abspath(__file__))
SVG_PATH: str = os.path.join(OUT_DIR, "fig3_4_usecase.svg")
PNG_PATH: str = os.path.join(OUT_DIR, "fig3_4_usecase.png")

# ---------------------------------------------------------------- 画布与样式
W: int = 1180
H: int = 1080

COLOR_LINE: str = "#333333"
COLOR_UC_FILL: str = "#FFFFFF"
COLOR_UC_STROKE: str = "#2F5597"
COLOR_PUB_FILL: str = "#FFF7E6"
COLOR_PUB_STROKE: str = "#C55A11"
COLOR_ACTOR: str = "#1F3864"
COLOR_BOUND: str = "#7F7F7F"
FONT_FAMILY: str = "'Microsoft YaHei','微软雅黑','SimHei',sans-serif"

RX: float = 92.0   # 用例椭圆横半轴
RY: float = 30.0   # 用例椭圆纵半轴

# ---------------------------------------------------------------- 参与者坐标
# name -> (x, y)  y 为小人身体中心
ACTORS: Dict[str, Tuple[float, float]] = {
    "失主": (120.0, 290.0),
    "拾得者": (120.0, 605.0),
    "管理员": (120.0, 850.0),
}

# ---------------------------------------------------------------- 用例坐标
# name -> (cx, cy, is_public)
USE_CASES: Dict[str, Tuple[float, float, bool]] = {
    # 失主专属
    "发布失物": (570.0, 200.0, False),
    "查看匹配": (570.0, 280.0, False),
    "认领": (570.0, 360.0, False),
    "验证交接码": (570.0, 440.0, False),
    # 拾得者专属
    "发布拾物": (570.0, 555.0, False),
    "确认归还": (570.0, 635.0, False),
    "生成交接码": (570.0, 715.0, False),
    # 管理员专属
    "审计时间线": (570.0, 810.0, False),
    "封禁": (570.0, 885.0, False),
    "分类管理": (840.0, 850.0, False),
    # 失主 + 拾得者 共用
    "IM 沟通": (880.0, 510.0, False),
    # 公开用例（不连任何 actor）
    "浏览公示栏": (970.0, 240.0, True),
}

# 参与者 -> 其关联的用例
ASSOCIATIONS: Dict[str, List[str]] = {
    "失主": ["发布失物", "查看匹配", "认领", "验证交接码", "IM 沟通"],
    "拾得者": ["发布拾物", "确认归还", "生成交接码", "IM 沟通"],
    "管理员": ["审计时间线", "封禁", "分类管理"],
}

# 系统边界框
BOUND: Tuple[float, float, float, float] = (300.0, 130.0, 960.0, 810.0)  # x, y, w, h
BOUND_TITLE: str = "校园失物招领系统"

# ---------------------------------------------------------------- 几何工具


def ellipse_edge(
    cx: float, cy: float, rx: float, ry: float, fx: float, fy: float
) -> Tuple[float, float]:
    """求由外部点 (fx,fy) 指向椭圆中心的连线与椭圆边界的交点。

    Args:
        cx, cy: 椭圆中心。
        rx, ry: 椭圆半轴。
        fx, fy: 外部起点。

    Returns:
        椭圆边界上的交点坐标 (x, y)。
    """
    dx: float = cx - fx
    dy: float = cy - fy
    denom: float = ((dx / rx) ** 2 + (dy / ry) ** 2) ** 0.5
    if denom == 0.0:
        return cx - rx, cy
    t: float = 1.0 / denom
    return cx - t * dx, cy - t * dy


def actor_anchor(ax: float, ay: float) -> Tuple[float, float]:
    """参与者图标的连线锚点（取小人躯干右侧）。"""
    return ax + 26.0, ay


# ---------------------------------------------------------------- SVG 生成


def actor_svg(name: str, ax: float, ay: float) -> str:
    """绘制 UML 小人参与者（头/躯干/双臂/双腿 + 名称标签）。"""
    head_r: float = 13.0
    head_cy: float = ay - 40.0
    body_top: float = head_cy + head_r
    body_bot: float = ay + 16.0
    arm_y: float = ay - 8.0
    leg_y: float = ay + 52.0
    s: str = (
        f'  <g stroke="{COLOR_ACTOR}" stroke-width="2.4" fill="none" '
        f'stroke-linecap="round">\n'
        f'    <circle cx="{ax}" cy="{head_cy}" r="{head_r}" fill="#FFFFFF"/>\n'
        f'    <line x1="{ax}" y1="{body_top}" x2="{ax}" y2="{body_bot}"/>\n'
        f'    <line x1="{ax - 26}" y1="{arm_y}" x2="{ax + 26}" y2="{arm_y}"/>\n'
        f'    <line x1="{ax}" y1="{body_bot}" x2="{ax - 20}" y2="{leg_y}"/>\n'
        f'    <line x1="{ax}" y1="{body_bot}" x2="{ax + 20}" y2="{leg_y}"/>\n'
        f'  </g>\n'
        f'  <text x="{ax}" y="{leg_y + 26}" text-anchor="middle" '
        f'font-family="{FONT_FAMILY}" font-size="20" font-weight="bold" '
        f'fill="{COLOR_ACTOR}">{escape(name)}</text>\n'
        f'  <text x="{ax}" y="{leg_y + 46}" text-anchor="middle" '
        f'font-family="{FONT_FAMILY}" font-size="13" '
        f'fill="#666666">&#171;actor&#187;</text>\n'
    )
    return s


def usecase_svg(name: str, cx: float, cy: float, is_public: bool) -> str:
    """绘制用例椭圆 + 名称。"""
    fill: str = COLOR_PUB_FILL if is_public else COLOR_UC_FILL
    stroke: str = COLOR_PUB_STROKE if is_public else COLOR_UC_STROKE
    dash: str = ' stroke-dasharray="7,4"' if is_public else ""
    txt_fill: str = COLOR_PUB_STROKE if is_public else "#1F3864"
    return (
        f'  <ellipse cx="{cx}" cy="{cy}" rx="{RX}" ry="{RY}" fill="{fill}" '
        f'stroke="{stroke}" stroke-width="2"{dash}/>\n'
        f'  <text x="{cx}" y="{cy + 6}" text-anchor="middle" '
        f'font-family="{FONT_FAMILY}" font-size="17" fill="{txt_fill}">'
        f'{escape(name)}</text>\n'
    )


def build_svg() -> str:
    """组装完整 SVG 文档字符串。"""
    bx, by, bw, bh = BOUND
    parts: List[str] = []
    parts.append(
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{W}" height="{H}" viewBox="0 0 {W} {H}">\n'
        f'  <rect x="0" y="0" width="{W}" height="{H}" fill="#FFFFFF"/>\n'
    )

    # 系统边界
    parts.append(
        f'  <rect x="{bx}" y="{by}" width="{bw}" height="{bh}" fill="none" '
        f'stroke="{COLOR_BOUND}" stroke-width="2"/>\n'
        f'  <text x="{bx + bw / 2}" y="{by + 30}" text-anchor="middle" '
        f'font-family="{FONT_FAMILY}" font-size="21" font-weight="bold" '
        f'fill="#404040">{escape(BOUND_TITLE)}</text>\n'
    )

    # 关联线（先画线，保证被图形覆盖在下层）
    for actor, ucs in ASSOCIATIONS.items():
        ax, ay = ACTORS[actor]
        px, py = actor_anchor(ax, ay)
        for uc in ucs:
            cx, cy, _ = USE_CASES[uc]
            ex, ey = ellipse_edge(cx, cy, RX, RY, px, py)
            parts.append(
                f'  <line x1="{px:.1f}" y1="{py:.1f}" x2="{ex:.1f}" '
                f'y2="{ey:.1f}" stroke="{COLOR_LINE}" stroke-width="1.5"/>\n'
            )

    # 参与者
    for name, (ax, ay) in ACTORS.items():
        parts.append(actor_svg(name, ax, ay))

    # 用例
    for name, (cx, cy, pub) in USE_CASES.items():
        parts.append(usecase_svg(name, cx, cy, pub))

    # 公开用例注释
    pcx, pcy, _ = USE_CASES["浏览公示栏"]
    parts.append(
        f'  <text x="{pcx}" y="{pcy - RY - 34}" text-anchor="middle" '
        f'font-family="{FONT_FAMILY}" font-size="15" font-weight="bold" '
        f'fill="{COLOR_PUB_STROKE}">&#171;公开用例&#187;</text>\n'
        f'  <text x="{pcx}" y="{pcy - RY - 14}" text-anchor="middle" '
        f'font-family="{FONT_FAMILY}" font-size="14" '
        f'fill="{COLOR_PUB_STROKE}">未登录用户可访问，无需登录</text>\n'
    )

    # 图例
    lx: float = 320.0
    ly: float = H - 56.0
    parts.append(
        f'  <g>\n'
        f'    <ellipse cx="{lx + 34}" cy="{ly}" rx="30" ry="12" fill="{COLOR_UC_FILL}" '
        f'stroke="{COLOR_UC_STROKE}" stroke-width="2"/>\n'
        f'    <text x="{lx + 76}" y="{ly + 5}" font-family="{FONT_FAMILY}" '
        f'font-size="14" fill="#404040">需登录用例</text>\n'
        f'    <ellipse cx="{lx + 224}" cy="{ly}" rx="30" ry="12" '
        f'fill="{COLOR_PUB_FILL}" stroke="{COLOR_PUB_STROKE}" stroke-width="2" '
        f'stroke-dasharray="7,4"/>\n'
        f'    <text x="{lx + 266}" y="{ly + 5}" font-family="{FONT_FAMILY}" '
        f'font-size="14" fill="#404040">公开用例（无需登录，不关联参与者）</text>\n'
        f'  </g>\n'
    )

    parts.append("</svg>\n")
    return "".join(parts)


# ---------------------------------------------------------------- PNG 生成


def build_png() -> bool:
    """用 matplotlib 栅格化同一布局为 PNG。成功返回 True。"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Ellipse, Rectangle
        from matplotlib import font_manager
    except Exception as exc:  # noqa: BLE001
        print(f"[PNG] matplotlib 不可用: {exc}")
        return False

    # 选择可用中文字体
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for cand in ("Microsoft YaHei", "SimHei", "SimSun", "KaiTi", "FangSong",
                 "Noto Sans CJK SC", "Source Han Sans SC"):
        if cand in installed:
            matplotlib.rcParams["font.sans-serif"] = [cand]
            print(f"[PNG] 使用中文字体: {cand}")
            break
    else:
        print("[PNG] 警告: 未找到中文字体，PNG 中文可能显示为方块")
    matplotlib.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(W / 100.0, H / 100.0), dpi=300)
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)          # y 轴向下，与 SVG 坐标系一致
    ax.axis("off")
    fig.patch.set_facecolor("#FFFFFF")

    bx, by, bw, bh = BOUND
    ax.add_patch(
        Rectangle((bx, by), bw, bh, fill=False, edgecolor=COLOR_BOUND, linewidth=1.6)
    )
    ax.text(bx + bw / 2, by + 26, BOUND_TITLE, ha="center", va="center",
            fontsize=13, fontweight="bold", color="#404040")

    # 关联线
    for actor, ucs in ASSOCIATIONS.items():
        axx, ayy = ACTORS[actor]
        px, py = actor_anchor(axx, ayy)
        for uc in ucs:
            cx, cy, _ = USE_CASES[uc]
            ex, ey = ellipse_edge(cx, cy, RX, RY, px, py)
            ax.plot([px, ex], [py, ey], color=COLOR_LINE, linewidth=0.9, zorder=1)

    # 参与者小人
    for name, (axx, ayy) in ACTORS.items():
        head_r = 13.0
        head_cy = ayy - 40.0
        body_top = head_cy + head_r
        body_bot = ayy + 16.0
        arm_y = ayy - 8.0
        leg_y = ayy + 52.0
        ax.add_patch(
            Ellipse((axx, head_cy), head_r * 2, head_r * 2, fill=True,
                    facecolor="#FFFFFF", edgecolor=COLOR_ACTOR, linewidth=1.5,
                    zorder=3)
        )
        for xs, ys in (
            ([axx, axx], [body_top, body_bot]),
            ([axx - 26, axx + 26], [arm_y, arm_y]),
            ([axx, axx - 20], [body_bot, leg_y]),
            ([axx, axx + 20], [body_bot, leg_y]),
        ):
            ax.plot(xs, ys, color=COLOR_ACTOR, linewidth=1.5, zorder=3,
                    solid_capstyle="round")
        ax.text(axx, leg_y + 22, name, ha="center", va="center", fontsize=12,
                fontweight="bold", color=COLOR_ACTOR, zorder=4)
        ax.text(axx, leg_y + 42, "\u00ab actor \u00bb", ha="center", va="center",
                fontsize=8, color="#666666", zorder=4)

    # 用例椭圆
    for name, (cx, cy, pub) in USE_CASES.items():
        face = COLOR_PUB_FILL if pub else COLOR_UC_FILL
        edge = COLOR_PUB_STROKE if pub else COLOR_UC_STROKE
        style = (0, (7, 4)) if pub else "solid"
        ax.add_patch(
            Ellipse((cx, cy), RX * 2, RY * 2, facecolor=face, edgecolor=edge,
                    linewidth=1.4, linestyle=style, zorder=2)
        )
        ax.text(cx, cy, name, ha="center", va="center", fontsize=10.5,
                color=(COLOR_PUB_STROKE if pub else "#1F3864"), zorder=4)

    # 公开用例注释
    pcx, pcy, _ = USE_CASES["浏览公示栏"]
    ax.text(pcx, pcy - RY - 34, "\u00ab 公开用例 \u00bb", ha="center", va="center",
            fontsize=9.5, fontweight="bold", color=COLOR_PUB_STROKE)
    ax.text(pcx, pcy - RY - 15, "未登录用户可访问，无需登录", ha="center",
            va="center", fontsize=9, color=COLOR_PUB_STROKE)

    # 图例
    lx, ly = 320.0, H - 56.0
    ax.add_patch(Ellipse((lx + 34, ly), 60, 24, facecolor=COLOR_UC_FILL,
                         edgecolor=COLOR_UC_STROKE, linewidth=1.4))
    ax.text(lx + 76, ly, "需登录用例", ha="left", va="center", fontsize=9,
            color="#404040")
    ax.add_patch(Ellipse((lx + 224, ly), 60, 24, facecolor=COLOR_PUB_FILL,
                         edgecolor=COLOR_PUB_STROKE, linewidth=1.4,
                         linestyle=(0, (7, 4))))
    ax.text(lx + 266, ly, "公开用例（无需登录，不关联参与者）", ha="left",
            va="center", fontsize=9, color="#404040")

    fig.savefig(PNG_PATH, dpi=300, bbox_inches="tight", facecolor="#FFFFFF",
                pad_inches=0.12)
    plt.close(fig)
    return True


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)

    svg: str = build_svg()
    with open(SVG_PATH, "w", encoding="utf-8") as fh:
        fh.write(svg)
    print(f"[SVG] 已写出: {SVG_PATH}  ({len(svg)} 字符)")

    # SVG 合法性自检
    from xml.dom import minidom
    minidom.parseString(svg.encode("utf-8"))
    print("[SVG] XML 解析校验: OK")

    png_ok: bool = False
    try:
        png_ok = build_png()
    except Exception as exc:  # noqa: BLE001
        print(f"[PNG] 生成失败: {exc}")
    if png_ok and os.path.exists(PNG_PATH):
        print(f"[PNG] 已写出: {PNG_PATH}  ({os.path.getsize(PNG_PATH)} 字节)")
    else:
        print("[PNG] 未生成（仅交付 SVG）")

    # 统计核对
    n_actor = len(ACTORS)
    n_uc = len(USE_CASES)
    n_pub = sum(1 for _, _, p in USE_CASES.values() if p)
    n_link = sum(len(v) for v in ASSOCIATIONS.values())
    print(f"\n参与者={n_actor}（应为 3，且不含游客）  用例={n_uc}  "
          f"公开用例={n_pub}  关联线={n_link}")
    assert n_actor == 3, "参与者必须为 3 个"
    assert "游客" not in ACTORS, "不得出现游客参与者"
    assert n_pub == 1, "公开用例应为 1 个（浏览公示栏）"
    print("自检: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
