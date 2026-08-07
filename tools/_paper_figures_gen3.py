# -*- coding: utf-8 -*-
"""_paper_figures_gen3.py — 生成毕业设计论文 8 张架构/算法插图（fig 3/5/7/9/10/11/4.1/4.2）。

复用既有绘图库 _paper_figures_lib（Canvas / font / C / 几何辅助），不重写该库。
运行：python _paper_figures_gen3.py   （建议在 tools/ 目录下，或用本文件所在目录的 venv）

输出目录：tools/_paper_figures_new/
   fig_03_use_case.png   图 3.4 用例图
   fig_05_sequence.png   图 3.5 序列图
   fig_07_state.png      图 3.7 状态图
   fig_09_er.png         图 3.9 E-R 图
   fig_10_class.png      图 3.10 类图
   fig_11_deploy.png     图 3.11 部署图
   fig_41_flow.png       图 4.1 功能模块流程图
   fig_42_pseudocode.png 图 4.2 加权打分伪代码

所有图内容严格对齐系统真实状态：
  - 视觉：单路微调 YOLOv8s(best.pt, 12 类)；YOLO-World 代码保留未接线。
  - 部署：FastAPI(uvicorn) + Vue3；HTTPS JSON + IM 轮询(4s)；VisionService 进程内单例。
  - 存储：MySQL 8.0 主库；Redis 默认关闭（生产可选）；交接码存 DB 的 expire_at。
  - 匹配：六维加权 + 归一化因子 k = 100/max(W_provided,50)；阈值 80；其他类 20·photo+80·tag。
  - flow-v3：keep1（留在原地）失主走"我要领走"→待交接（跳拾得者确认）；confirm/reject 两条分支。
"""
from __future__ import annotations

import os
import sys

# 保证能从任意 cwd 导入同目录的绘图库
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _paper_figures_lib import (  # noqa: E402
    Canvas, font, C, top, bottom, left, right, center, offset,
)

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_paper_figures_new")

# --------------------------------------------------------------------------
# 通用小工具
# --------------------------------------------------------------------------

def _title(c: Canvas, x: float, y: float, text: str, size: int = 15) -> None:
    """左上角小标题（图号）。"""
    c.text(x, y, text, size=size, bold=True, color=C.TEXT, anchor="lm")


def _note(c: Canvas, x: float, y: float, text: str, size: int = 11,
          color: object = C.MUTED) -> None:
    """灰色说明文字。"""
    c.text(x, y, text, size=size, color=color, anchor="lm")


# ==========================================================================
# 图 3.4 用例图
# ==========================================================================
def fig_use_case() -> str:
    # 排版说明：原 640x2010（宽高比 3.14）单列布局，在论文中按 13cm 宽插入会被
    # 拉成 42cm 高，横跨约 1.7 个 A4 版心。现改为「左右双侧角色 + 中间双列用例」
    # 的标准 UML 布局，宽高比降到 0.70，插入后约 14cm x 9.8cm，单页可容纳。
    W, H = 1400, 980
    c = Canvas(W, H, ss=3)
    _title(c, 24, 30, "图 3.4 系统用例图", size=16)

    # 系统边界
    c._d.rounded_rectangle(c._xy([(300, 70), (1100, 870)]), radius=c._s(10),
                           outline=C.GRAY_S, width=max(1, int(c._s(1.2))))
    c.text(700, 96, "校园失物招领智能匹配系统", size=12, color=C.MUTED, anchor="mm")

    # 角色：左右两侧分列，避免所有连线挤在一侧
    c.actor(110, 200, "游客", scale=1.05, size=14)
    c.actor(110, 540, "失主", scale=1.05, size=14)
    c.actor(1290, 260, "拾得者", scale=1.05, size=14)
    c.actor(1290, 650, "管理员", scale=1.05, size=14)

    # 用例（椭圆）：左列=失主/游客，右列=拾得者/管理员
    uc = [
        (560, 190, 230, 58, "发布失物"),
        (560, 320, 230, 58, "浏览匹配"),
        (560, 450, 230, 58, "认领"),
        (560, 580, 250, 58, "我要领走(keep1)"),
        (560, 710, 230, 58, "申诉"),
        (900, 150, 230, 58, "拍照发布"),
        (900, 260, 290, 58, "选保管状态(keep0/keep1)"),
        (900, 370, 260, 58, "确认归还/驳回"),
        (900, 480, 230, 58, "审核"),
        (900, 590, 230, 58, "审计报表"),
        (900, 700, 290, 58, "数据导出(v10新增)"),
        (900, 810, 260, 58, "IM 轮询沟通"),
    ]
    rects = {}
    for cx, cy, w, h, t in uc:
        r = (cx - w / 2, cy - h / 2, w, h)
        rects[t] = r
        c.ellipse_node(r, t, size=13)

    def link_l(actor_cy: float, target: str, dash=None) -> None:
        """左侧角色 → 用例椭圆左沿。"""
        tr = rects[target]
        c.line((140, actor_cy), (tr[0] - 2, tr[1] + tr[3] / 2),
               color=C.LINE, width=1.4, dash=dash)

    def link_r(actor_cy: float, target: str) -> None:
        """右侧角色 → 用例椭圆右沿。"""
        tr = rects[target]
        c.line((1260, actor_cy), (tr[0] + tr[2] + 2, tr[1] + tr[3] / 2),
               color=C.LINE, width=1.4)

    # 失主（左）
    for t in ("发布失物", "浏览匹配", "认领", "我要领走(keep1)", "申诉"):
        link_l(540, t)
    # 游客（左，虚线：仅浏览）
    link_l(200, "浏览匹配", dash=(5, 4))
    # 拾得者（右）
    for t in ("拍照发布", "选保管状态(keep0/keep1)", "确认归还/驳回"):
        link_r(260, t)
    # 管理员（右）
    for t in ("审核", "审计报表", "数据导出(v10新增)", "IM 轮询沟通"):
        link_r(650, t)

    # 标注（置于系统边界下方空白区）
    _note(c, 300, 912, "keep1：物品留在原地，失主「我要领走」直达待交接，拾得者侧(U2)完全隐藏",
          size=11, color=C.ORANGE_S)
    _note(c, 300, 946, "v10 新增：数据导出 + IM 轮询沟通（前端 4s 轮询，非 WebSocket）",
          size=11, color=C.GREEN_S)

    return c.save(os.path.join(OUT_DIR, "fig_03_use_case.png"))


# ==========================================================================
# 图 3.5 序列图
# ==========================================================================
def fig_sequence() -> str:
    W, H = 1500, 1980
    c = Canvas(W, H, ss=3)
    _title(c, 24, 26, "图 3.5 发布-匹配-交接 UML 序列图", size=15)

    lanes = [
        "前端\n(失主/拾得者)",
        "FastAPI\nRouter",
        "Publish\nService",
        "Vision\nService(进程内)",
        "Match\nService",
        "Handover\nService",
        "MySQL\n8.0",
    ]
    n = len(lanes)
    x0 = 40
    lw = (W - 2 * x0) / n
    header_h = 64
    top_y = 70
    life_top = top_y + header_h
    life_bottom = H - 70

    # 泳道头部 + 生命线
    for i, name in enumerate(lanes):
        lx = x0 + lw * i
        cx = lx + lw / 2
        c.box((lx + 4, top_y, lw - 8, header_h), name, size=11, bold=True,
              fill=C.GRAY_F, stroke=C.GRAY_S)
        c.line((cx, life_top), (cx, life_bottom), color=C.GRAY_S, width=1.2, dash=(4, 4))

    def msg(frm: int, to: int, label: str, y: float, color: object = C.LINE,
            dash: tuple | None = None) -> None:
        fx = x0 + lw * frm + lw / 2
        tx = x0 + lw * to + lw / 2
        c.arrow((fx, y), (tx, y), color=color, width=1.5, dash=dash, label=label,
                label_size=10.5, label_offset=(0, -10))

    y = life_top + 24
    step = 84

    # ---- 发布 + 进程内打标 + 反向匹配 ----
    msg(0, 1, "① POST /publish (保管状态 keep0/keep1)", y); y += step
    msg(1, 2, "② publish(item, keep_status)", y); y += step
    msg(2, 3, "③ predict(photo) 进程内单例", y, color=C.PURPLE_S); y += step
    msg(3, 2, "④ labels (YOLOv8s 12类)", y, color=C.PURPLE_S, dash=(5, 4)); y += step
    msg(2, 6, "⑤ insert found_item(keep_status)", y); y += step
    msg(2, 4, "⑥ reverse_match(lost_item 池)", y); y += step
    msg(4, 6, "⑦ query lost_item 同类别待认领", y, dash=(5, 4)); y += step
    msg(6, 4, "⑧ 候选集", y, dash=(5, 4)); y += step
    msg(4, 6, "⑨ insert match_record(score)", y); y += step
    msg(4, 0, "⑩ 推送疑似匹配(≥80)", y, color=C.GREEN_S); y += step + 10

    # ---- 认领 + 确认/驳回 + 交接 ----
    msg(0, 1, "⑪ POST /claim (keep1→我要领走)", y); y += step
    msg(1, 4, "⑫ claim(match_id)", y); y += step
    msg(4, 6, "⑬ 校验 match_record.status", y, dash=(5, 4)); y += step
    msg(0, 1, "⑭ confirm_return / reject", y, color=C.ORANGE_S); y += step
    # confirm 分支
    msg(1, 5, "⑮ confirm → HandoverService", y, color=C.GREEN_S); y += step
    msg(5, 6, "⑯ insert handover_code(expire_at)", y, color=C.GREEN_S); y += step
    msg(5, 0, "⑰ 展示交接码 / 双端扫码 verify", y, color=C.GREEN_S); y += step + 10
    # reject 分支
    msg(1, 4, "⑭' reject()", y, color=C.RED_S); y += step
    msg(4, 6, "⑮' match_record 重入匹配池", y, color=C.RED_S); y += step
    c.text(x0 + lw * 4 + lw / 2, y - step + 14, "keep1 时 reject/confirm 均返回 422 (code 9001)",
           size=10, color=C.RED_S, anchor="mm")

    # 底部图例
    lg_y = H - 40
    c.line((x0, lg_y), (x0 + 360, lg_y), color=C.GREEN_S, width=2)
    c.text(x0 + 370, lg_y, "绿色=交接闭环(DB expire_at，非 Redis TTL)", size=11,
           color=C.GREEN_S, anchor="lm")
    c.text(W - x0, lg_y, "keep_status: 0=需认领 / 1=留在原地", size=11,
           color=C.ORANGE_S, anchor="rm")

    return c.save(os.path.join(OUT_DIR, "fig_05_sequence.png"))


# ==========================================================================
# 图 3.7 状态图
# ==========================================================================
def fig_state() -> str:
    W, H = 1120, 1340
    c = Canvas(W, H, ss=3)
    _title(c, 24, 26, "图 3.7 失物状态图", size=15)

    def state(x, y, w, h, t, fill=C.BLUE_F, stroke=C.BLUE_S):
        return c.box((x, y, w, h), t, size=13, fill=fill, stroke=stroke)

    # 主链路（左→右，上排）
    s1 = state(40, 60, 160, 60, "待匹配")
    s2 = state(260, 60, 160, 60, "匹配中")
    s3 = state(480, 60, 160, 60, "待认领")
    s4 = state(700, 60, 170, 60, "认领中")
    s5 = state(910, 60, 170, 60, "待交接")
    s6 = state(910, 980, 170, 60, "已解决")

    # 已拒绝（下排）
    s7 = state(480, 980, 170, 60, "已拒绝", fill=C.RED_F, stroke=C.RED_S)

    # 主链路水平箭头：贴在状态框【下沿】(y=120)，label 置于其下方，避免压字
    y_edge = 120

    def harrow(a, b, lab: str) -> None:
        c.arrow((a[0] + a[2], y_edge), (b[0], y_edge), label=lab, label_offset=(0, 12))

    harrow(s1, s2, "反向匹配命中")
    harrow(s2, s3, "生成 match_record")
    harrow(s3, s4, "失主认领(keep0)")
    harrow(s4, s5, "拾得者确认归还")
    # 待交接 → 已解决（向下）
    c.arrow(bottom(s5), top(s6), label="双端扫码验证", label_offset=(12, 0))

    # keep1 分支：待认领 → 待交接（跳过认领中/拾得者确认），从上方绕行
    c.polyline([top(s3), (s3[0] + s3[2] / 2, 28), (s5[0] + s5[2] / 2, 28), top(s5)],
               color=C.ORANGE_S, width=1.6)
    c.arrow_head(top(s5), (0, 1), color=C.ORANGE_S, size=8)
    c.text((s3[0] + s3[2] / 2 + s5[0] + s5[2] / 2) / 2, 16,
           "keep_status==1 & 我要领走(跳拾得者确认, U2 隐藏)",
           size=10.5, color=C.ORANGE_S, anchor="mm")

    # 认领中 → 已拒绝（驳回）：从 s4 下沿向下进入 s7 上沿
    c.polyline([bottom(s4), (s4[0] + s4[2] / 2, 560), (s7[0] + s7[2] / 2, 560), top(s7)],
               color=C.RED_S, width=1.6)
    c.arrow_head(top(s7), (0, 1), color=C.RED_S, size=8)
    c.text(s4[0] + s4[2] / 2 + 8, 560, "拾得者驳回", size=10.5, color=C.RED_S, anchor="lm")

    # 已拒绝 → 待匹配（重入匹配池）：从 s7 左侧沿画布最左侧竖直回到 s1 【左沿】
    # 注意：不可走 y=120，该横向通道已被上排主链路箭头占用，会叠线。
    x_back = 18
    y_s1c = s1[1] + s1[3] / 2
    c.polyline([left(s7), (x_back, s7[1] + s7[3] / 2), (x_back, y_s1c), left(s1)],
               color=C.MUTED, width=1.5, dash=(5, 4))
    c.arrow_head(left(s1), (1, 0), color=C.MUTED, size=8)
    c.text(x_back + 10, s7[1] + s7[3] / 2 - 16, "重入匹配池", size=10.5,
           color=C.MUTED, anchor="lm")

    # 申诉：改为 s7 下方注记（原竖线 x=565 与驳回箭头同轴，会重叠）
    c.text(s7[0], s7[1] + s7[3] + 20, "申诉成立→关闭(维持已拒绝)", size=10,
           color=C.MUTED, anchor="lm")

    return c.save(os.path.join(OUT_DIR, "fig_07_state.png"))


# ==========================================================================
# 图 3.9 E-R 图
# ==========================================================================
def fig_er() -> str:
    # H 由 940 增至 1000：为底部跨列总线（y=946/968）留出通道，避免斜穿表体。
    W, H = 1440, 1000
    c = Canvas(W, H, ss=3)
    _title(c, 24, 26, "图 3.9 数据库 E-R 图（10 张表）", size=15)

    tables = {
        "user": (40, 50, 330, 150,
                 ["user_id PK", "name", "phone", "role", "trust_score"]),
        "category": (40, 240, 330, 130,
                     ["cat_id PK", "name", "mode", "yolo_world_prompt"]),
        "lost_item": (430, 40, 360, 190,
                      ["lost_id PK", "user_id FK", "cat_id FK", "desc / photo", "status", "created_at"]),
        "found_item": (430, 270, 360, 210,
                       ["found_id PK", "user_id FK", "cat_id FK", "photo", "keep_status:0/1 ★", "status", "created_at"]),
        "match_record": (430, 530, 360, 180,
                         ["match_id PK", "lost_id FK", "found_id FK", "score", "status", "created_at"]),
        "handover_code": (430, 760, 360, 160,
                          ["code_id PK", "match_id FK", "code", "expire_at", "used"]),
        "im_session": (860, 40, 340, 150,
                       ["session_id PK", "lost_id FK", "found_id FK"]),
        "im_message": (860, 230, 340, 150,
                       ["msg_id PK", "session_id FK", "sender_id FK", "content"]),
        "trust_score_log": (860, 430, 340, 160,
                            ["log_id PK", "user_id FK", "delta", "reason", "created_at"]),
        "audit_log": (860, 640, 340, 170,
                      ["audit_id PK", "op / actor_id", "detail", "created_at", "partition_month"]),
    }

    # 画表
    rects = {}
    for name, (x, y, w, h, fields) in tables.items():
        r = c.box((x, y, w, h), fields, header=name, header_fill=C.BLUE_S,
                  size=12, body_size=11.5, body_align_left=True)
        rects[name] = r

    # ---- 关系线路由 --------------------------------------------------
    # 原实现固定「右沿→左沿」直连，导致 user→trust_score_log / user→audit_log
    # 斜穿 lost_item、found_item、match_record 表体，且同列回折线反向压表。
    # 现按相对位置分派三种走法，全部走空白通道，保证不穿任何表体。
    def _mult(x, y, s, anchor):
        c.text(x, y, s, size=11, color=C.MUTED, anchor=anchor)

    def rel_h(a, b, lab, mult_a="1", mult_b="*", a_off=0.0, b_off=0.0):
        """左右列相邻：a 右沿 → b 左沿 直连（中间为空白列间距）。"""
        ra, rb = rects[a], rects[b]
        p0 = (ra[0] + ra[2], ra[1] + ra[3] / 2 + a_off)
        p1 = (rb[0], rb[1] + rb[3] / 2 + b_off)
        c.line(p0, p1, color=C.LINE, width=1.4)
        # 基数标注放在【框外】的列间隙里（放框内会压住表格边框/字段）
        _mult(p0[0] + 7, p0[1] - 9, mult_a, "lm")
        _mult(p1[0] - 7, p1[1] - 9, mult_b, "rm")
        # 关系名放线的【下方】，与两端基数错开，避免三者挤在同一水平线
        c.text((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2 + 11, lab,
               size=10.5, color=C.MUTED, anchor="mm")

    def rel_v(a, b, lab, mult_a="1", mult_b="*"):
        """同列上下相邻：a 下沿 → b 上沿 垂直连。"""
        ra, rb = rects[a], rects[b]
        x = ra[0] + ra[2] / 2
        y0, y1 = ra[1] + ra[3], rb[1]
        c.line((x, y0), (x, y1), color=C.LINE, width=1.4)
        _mult(x - 7, y0 + 11, mult_a, "rm")
        _mult(x - 7, y1 - 11, mult_b, "rm")
        c.text(x + 8, (y0 + y1) / 2, lab, size=10.5, color=C.MUTED, anchor="lm")

    def rel_elbow(a, b, xc, lab, mult_a="1", mult_b="*"):
        """同列但不相邻：经列左侧空白通道 xc 正交绕行，不穿中间表。"""
        ra, rb = rects[a], rects[b]
        p0 = (ra[0], ra[1] + ra[3] / 2)
        p1 = (rb[0], rb[1] + rb[3] / 2)
        c.polyline([p0, (xc, p0[1]), (xc, p1[1]), p1], color=C.LINE, width=1.4)
        _mult(p0[0] - 8, p0[1] - 10, mult_a, "rm")
        _mult(p1[0] - 8, p1[1] - 10, mult_b, "rm")
        # 标签贴近目标端而非通道中点：中点处会与列间隙里的 rel_h 关系名撞字
        c.text(xc - 6, p1[1] - 45, lab, size=10.5, color=C.MUTED, anchor="rm")

    def rel_bus(a, b, y_bus, x_out, x_in, lab, mult_a="1", mult_b="*", a_off=0.0):
        """跨越整列的远距离关系：左出 → 画布底部总线 → 右侧回折进入 b 右沿。"""
        ra, rb = rects[a], rects[b]
        p0 = (ra[0], ra[1] + ra[3] / 2 + a_off)
        p1 = (rb[0] + rb[2], rb[1] + rb[3] / 2)
        c.polyline([p0, (x_out, p0[1]), (x_out, y_bus), (x_in, y_bus),
                    (x_in, p1[1]), p1], color=C.LINE, width=1.4)
        _mult(p0[0] - 8, p0[1] - 10, mult_a, "rm")
        _mult(p1[0] + 8, p1[1] - 10, mult_b, "lm")
        c.text((x_out + x_in) / 2, y_bus - 10, lab, size=10.5, color=C.MUTED, anchor="mm")

    # 列相邻直连（入口点上下错开，避免多线共点）
    rel_h("user", "lost_item", "发布", a_off=-30, b_off=-25)
    rel_h("user", "found_item", "发布", a_off=30, b_off=-25)
    rel_h("category", "lost_item", "标注", a_off=-25, b_off=25)
    rel_h("category", "found_item", "标注", a_off=25, b_off=25)
    rel_h("lost_item", "im_session", "涉及", b_off=-40)
    rel_h("found_item", "im_session", "涉及", b_off=0)
    rel_h("match_record", "im_session", "开启", b_off=40)
    # 同列上下相邻：垂直连
    rel_v("found_item", "match_record", "参与")
    rel_v("match_record", "handover_code", "生成", mult_b="1")
    rel_v("im_session", "im_message", "包含")
    # 同列不相邻：走 col1|col2 之间的空白通道 x=412
    rel_elbow("lost_item", "match_record", 412, "参与")
    # 跨整列：走画布底部总线（表体最低 920，总线 946/968 均在其下）
    rel_bus("user", "trust_score_log", 946, 32, 1258, "记分", a_off=-30)
    rel_bus("user", "audit_log", 968, 18, 1238, "操作", a_off=30)

    # 高亮标注：移到左下空白区（原 x=800 位置会被新增的列间通道穿过）
    _note(c, 45, 430, "keep_status：0=需认领 / 1=留在原地(keep1)",
          size=10.5, color=C.ORANGE_S)
    _note(c, 45, 470, "expire_at：交接码过期存 DB（非 Redis TTL）",
          size=10.5, color=C.GREEN_S)

    return c.save(os.path.join(OUT_DIR, "fig_09_er.png"))


# ==========================================================================
# 图 3.10 类图
# ==========================================================================
def fig_class() -> str:
    # 重排版原因（原 1520x1120 双列实体布局存在两类硬伤）：
    #   1) service->entity 依赖线固定「服务左沿→实体右沿」直连，凡目标在第 1 列的
    #      连线都会斜穿第 2 列实体框体（如 MatchService→FoundItem 整条穿过
    #      TrustScoreLog）；AuditService 的两条线还穿过 VisionService/MatchService。
    #   2) 注记框 (820,910,680,70) 与 IMService (820,850,320,110) 实测重叠 320x50px。
    # 现改为「实体单列 + 服务单列 + 注记独立列」，所有依赖线只落在 x=360..620
    # 的空白通道内，结构上不可能穿框；注记移到右侧独立列，彻底消除重叠。
    W, H = 1460, 1300
    c = Canvas(W, H, ss=3)
    _title(c, 24, 26, "图 3.10 服务层类图", size=15)

    entities = {
        "User": (40, 60, 320, 118, ["- user_id: int", "- name: str", "- role: str",
                                    "- trust_score: float"]),
        "LostItem": (40, 200, 320, 118, ["- lost_id: int", "- cat_id: int",
                                         "- desc: str", "- status: str"]),
        "FoundItem": (40, 340, 320, 118, ["- found_id: int", "- cat_id: int",
                                          "- photo: str", "- keep_status: int ★"]),
        "MatchRecord": (40, 480, 320, 118, ["- match_id: int", "- lost_id: int",
                                            "- found_id: int", "- score: float"]),
        "HandoverCode": (40, 620, 320, 118, ["- code_id: int", "- match_id: int",
                                             "- code: str", "- expire_at: dt"]),
        "IMSession": (40, 760, 320, 100, ["- session_id: int", "- lost_id: int",
                                          "- found_id: int"]),
        "IMMessage": (40, 882, 320, 100, ["- msg_id: int", "- session_id: int",
                                          "- content: str"]),
        "TrustScoreLog": (40, 1004, 320, 118, ["- log_id: int", "- user_id: int",
                                               "- delta: float", "- reason: str"]),
        "AuditLog": (40, 1144, 320, 118, ["- audit_id: int", "- op: str",
                                          "- detail: str", "- partition_month"]),
    }
    services = {
        "PublishService": (620, 240, 330, 100, ["+ publish()", "+ reverse_match()"]),
        "VisionService": (620, 380, 330, 100, ["+ predict(photo)", "+ 进程内单例"]),
        "MatchService": (620, 520, 330, 118, ["+ score()", "+ claim()", "+ reject()"]),
        "HandoverService": (620, 678, 330, 100, ["+ confirm()", "+ gen_code()"]),
        "IMService": (620, 820, 330, 100, ["+ poll(4s)", "+ send()"]),
        "AuditService": (620, 1080, 330, 100, ["+ write()", "+ report()"]),
    }

    e_rects = {}
    for name, (x, y, w, h, attrs) in entities.items():
        e_rects[name] = c.box((x, y, w, h), attrs, header=name, header_fill=C.BLUE_S,
                              size=12, body_size=11, body_align_left=True)
    s_rects = {}
    for name, (x, y, w, h, meths) in services.items():
        fill = C.PURPLE_F if name == "VisionService" else C.GREEN_F
        stroke = C.PURPLE_S if name == "VisionService" else C.GREEN_S
        s_rects[name] = c.box((x, y, w, h), meths, header=name, header_fill=stroke,
                              size=12, body_size=11, body_align_left=True)

    # 依赖线：service 左沿 → entity 右沿。两列之间 x=360..620 为纯空白通道，
    # 任何端点落在两列边沿的直线都只经过该通道，不会穿过任何类框。
    # s_off / e_off 让同一端的多条线错开，避免共点重叠。
    def dep(s, e, s_off=0.0, e_off=0.0, dash=False):
        rs, re_ = s_rects[s], e_rects[e]
        p0 = (rs[0], rs[1] + rs[3] / 2 + s_off)
        p1 = (re_[0] + re_[2], re_[1] + re_[3] / 2 + e_off)
        c.line(p0, p1, color=C.MUTED, width=1.3, dash=(5, 4) if dash else None)

    dep("PublishService", "LostItem", s_off=-15, e_off=-22)
    dep("PublishService", "FoundItem", s_off=15, e_off=-22)
    dep("MatchService", "LostItem", s_off=-30, e_off=22)
    dep("MatchService", "FoundItem", s_off=0, e_off=22)
    dep("MatchService", "MatchRecord", s_off=30, e_off=-22)
    dep("HandoverService", "MatchRecord", s_off=-15, e_off=22)
    dep("HandoverService", "HandoverCode", s_off=15, e_off=0)
    dep("IMService", "IMSession", s_off=-15, e_off=0)
    dep("IMService", "IMMessage", s_off=15, e_off=0)
    dep("AuditService", "TrustScoreLog", s_off=-15, e_off=0)
    dep("AuditService", "AuditLog", s_off=15, e_off=0)

    # VisionService 进程内单例（虚线，PublishService 调用）——同列上下相邻，走垂直连
    xv = 620 + 330 / 2
    c.line((xv, 340), (xv, 380), color=C.PURPLE_S, width=1.5, dash=(5, 4))
    c.text(xv + 10, 360, "进程内调用（非微服务）",
           size=10.5, color=C.PURPLE_S, anchor="lm")

    # 标注：独立右列 x=990..1430，与服务列（止于 950）完全分离，杜绝压框
    c.box((990, 240, 440, 110),
          ["VisionService:", "YOLOv8s(best.pt, 12 类)", "进程内单例"],
          fill=C.PURPLE_F, stroke=C.PURPLE_S, size=12)
    c.box((990, 390, 440, 96),
          ["YOLO-World 代码保留未接线", "（seed mode=0 休眠）"],
          fill=C.GRAY_F, stroke=C.GRAY_S, size=11, dash=True)

    return c.save(os.path.join(OUT_DIR, "fig_10_class.png"))


# ==========================================================================
# 图 3.11 部署图
# ==========================================================================
def fig_deploy() -> str:
    # H 600→620 且 Redis 下移到 y=500：原 FastAPI(止于450) 与 Redis(起于480)
    # 仅 30px 间隙，"可选" 标签放不下，实测压住 FastAPI 框 22x4px。
    W, H = 1600, 620
    c = Canvas(W, H, ss=3)
    _title(c, 24, 26, "图 3.11 系统部署图", size=15)

    # 客户端
    c.box((40, 200, 280, 180),
          ["浏览器 / 手机 Web", "Vue3 + Element Plus", "前端"],
          fill=C.BLUE_F, stroke=C.BLUE_S, size=14)
    # 服务端（FastAPI + 进程内 VisionService）
    c.box((440, 150, 520, 300),
          ["FastAPI (uvicorn)", "VisionService 进程内单例", "(YOLOv8s, 12类)",
           "Publish/Match/Handover/IM/Audit Service"],
          fill=C.GREEN_F, stroke=C.GREEN_S, size=13)
    # MySQL
    c.cylinder((1060, 200, 300, 200), ["MySQL 8.0", "主库 (10 表)"],
               fill=C.TEAL_F, stroke=C.TEAL_S, size=14)
    # Redis（可选，关闭）
    c.box((440, 500, 520, 80),
          ["Redis：生产可选 · 默认关闭（内存兜底）"],
          fill=C.GRAY_F, stroke=C.GRAY_S, size=12, dash=True)

    # 箭头（label 置于连线中点上方，落在组件间隙，避免压字）
    c.arrow(right((40, 200, 280, 180)), left((440, 150, 520, 300)),
            label="HTTPS JSON\n+ IM 轮询(4s)", label_size=11.5, color=C.BLUE_S,
            label_offset=(0, -16))
    c.arrow(right((440, 150, 520, 300)), left((1060, 200, 300, 200)),
            label="SQLAlchemy ORM", label_size=11.5, color=C.TEAL_S,
            label_offset=(0, -16))
    # 短箭头：标签移到连线【右侧】的空白处，不再压在两框之间
    c.arrow(bottom((440, 150, 520, 300)), top((440, 500, 520, 80)),
            label="可选", label_size=11, color=C.MUTED, dash=(5, 4),
            label_offset=(46, 0))

    _note(c, 40, 596, "无独立推理微服务 / 无 WebSocket 服务器；IM 为前端 4s 轮询",
          size=11, color=C.MUTED)

    return c.save(os.path.join(OUT_DIR, "fig_11_deploy.png"))


# ==========================================================================
# 图 4.1 功能模块流程图
# ==========================================================================
def fig_flow() -> str:
    # W 1020→1240：宽高比由 1.73 降到 1.42，按 14cm 宽插入后高度从 24.2cm 降到
    # 19.9cm，可与图题同页；纵向结构与分支走线保持不变。
    W, H = 1240, 1760
    c = Canvas(W, H, ss=3)
    _title(c, 24, 26, "图 4.1 核心业务功能模块流程图", size=15)

    cx = W / 2
    bw, bh = 420, 70

    def node(y, t, fill=C.BLUE_F, stroke=C.BLUE_S, is_stadium=False):
        r = (cx - bw / 2, y, bw, bh)
        if is_stadium:
            c.stadium(r, t, fill=fill, stroke=stroke)
        else:
            c.box(r, t, fill=fill, stroke=stroke, size=13)
        return r

    def diamond(y, t):
        r = (cx - 200, y, 400, 110)
        c.diamond(r, t, size=12)
        return r

    def down(a, b, label="", color=C.LINE):
        c.arrow(bottom(a), top(b), label=label, color=color, label_size=11)

    y = 70
    n1 = node(y, "拾得者发布（拍照 + 选保管状态 keep0/keep1）", C.BLUE_F, C.BLUE_S, True); y += 110
    n2 = node(y, "VisionService 进程内打标（YOLOv8s 12类）"); y += 110
    n3 = node(y, "写 found_item（keep_status）"); y += 110
    n4 = node(y, "反向匹配 lost_item 池"); y += 110
    n5 = node(y, "MatchService 六维打分（归一化因子 k）"); y += 110
    d1 = diamond(y, "score ≥ 80 ?"); y += 150
    n6 = node(y, "生成疑似匹配"); y += 110
    n7 = node(y, "失主认领"); y += 110
    d2 = diamond(y, "keep_status==1 & 我要领走 ?"); y += 150
    # keep1 分支（右侧短线到待交接）
    n8 = node(y, "拾得者确认归还 / 驳回"); y += 110
    d3 = diamond(y, "确认 / 驳回 ?"); y += 150
    n9 = node(y, "HandoverService 生成 DB 交接码(expire_at)"); y += 110
    n10 = node(y, "双端扫码验证"); y += 110
    n11 = node(y, "已解决 + 审计留痕", C.GREEN_F, C.GREEN_S, True)

    down(n1, n2)
    down(n2, n3)
    down(n3, n4)
    down(n4, n5)
    down(n5, d1)
    # d1 no 分支
    c.arrow(right(d1), (cx + 380, center(d1)[1]), label="否", color=C.MUTED, head=False)
    c.text(cx + 390, center(d1)[1], "不推送", size=11, color=C.MUTED, anchor="lm")
    down(d1, n6, label="是")
    down(n6, n7)
    down(n7, d2)
    # d2 yes 分支：直接到 n9（待交接，跳确认）
    c.polyline([right(d2), (cx + 360, center(d2)[1]), (cx + 360, center(n9)[1]),
                right(n9)], color=C.ORANGE_S, width=1.6)
    c.arrow_head((right(n9)[0], center(n9)[1]), (-1, 0), color=C.ORANGE_S, size=8)
    c.text(cx + 370, (center(d2)[1] + center(n9)[1]) / 2,
           "是(keep1)\n跳拾得者确认\nU2 完全隐藏", size=10.5, color=C.ORANGE_S, anchor="lm")
    down(d2, n8, label="否")
    down(n8, d3)
    # d3 reject 分支回退：必须从菱形【左顶点】出发；原先从 bottom(d3) 起步再折向
    # 左侧，那条斜边会从菱形内部穿出去（自检可复现）。
    c.polyline([left(d3), (cx - 360, center(d3)[1]), (cx - 360, center(n4)[1]),
                left(n4)], color=C.RED_S, width=1.6)
    c.arrow_head((left(n4)[0], center(n4)[1]), (1, 0), color=C.RED_S, size=8)
    c.text(cx - 370, (center(d3)[1] + center(n4)[1]) / 2,
           "驳回→重入匹配池\n(keep1 时返回 422)", size=10.5, color=C.RED_S, anchor="rm")
    down(d3, n9, label="确认")
    down(n9, n10)
    down(n10, n11)

    return c.save(os.path.join(OUT_DIR, "fig_41_flow.png"))


# ==========================================================================
# 图 4.2 加权打分伪代码
# ==========================================================================
def fig_pseudocode() -> str:
    W, H = 1320, 740
    c = Canvas(W, H, ss=3)
    _title(c, 24, 26, "图 4.2 加权打分伪代码（v10）", size=15)

    # 代码块背景
    bx, by, bw, bh = 30, 70, W - 60, H - 110
    c._d.rounded_rectangle(c._xy([(bx, by), (bx + bw, by + bh)]), radius=c._s(10),
                           fill=(247, 247, 249), outline=C.GRAY_S, width=max(1, int(c._s(1.4))))

    code = [
        "# six-dimension weighted scoring (v10)",
        "OTHER_ID = 12        # 'other' fallback class",
        "TAU      = 3         # time-decay window",
        "THRESHOLD = 80       # suspected-match threshold",
        "SUSPECT   = 80       # suspected line",
        "LOW       = 60       # low-score line (weakens owner visual only)",
        "",
        "def score(lost, found):",
        "    w = load_weights()                 # six base weights",
        "    if found.cat_id == OTHER_ID:       # other-class branch",
        "        raw = 20*photo_match + 80*tag_match_rate",
        "    else:",
        "        raw = (20*photo + 30*category + 20*appearance",
        "             + 15*feature + 10*time + 5*location)   # sum",
        "    W_provided = sum(enabled_weights(w))",
        "    k = 100 / max(W_provided, 50)      # normalization factor",
        "    total = clamp(raw * k, 0, 100)",
        "    is_suspected = total >= SUSPECT",
        "    return total if total >= THRESHOLD else 0",
    ]

    x = bx + 26
    y = by + 30
    lh = 30
    for ln in code:
        c.text(x, y, ln, size=15, color=C.TEXT, mono=True, anchor="lm")
        y += lh

    return c.save(os.path.join(OUT_DIR, "fig_42_pseudocode.png"))


# ==========================================================================
# main
# ==========================================================================
def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    results = [
        ("图3.4 用例图", fig_use_case()),
        ("图3.5 序列图", fig_sequence()),
        ("图3.7 状态图", fig_state()),
        ("图3.9 E-R图", fig_er()),
        ("图3.10 类图", fig_class()),
        ("图3.11 部署图", fig_deploy()),
        ("图4.1 流程图", fig_flow()),
        ("图4.2 伪代码", fig_pseudocode()),
    ]
    print("== 生成完成 ==")
    for label, path in results:
        exist = os.path.exists(path)
        sz = os.path.getsize(path) if exist else 0
        print(f"  [{label}] {path}  exist={exist}  {sz}B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
