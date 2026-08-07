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
    W, H = 640, 2010
    c = Canvas(W, H, ss=3)
    _title(c, 24, 30, "图 3.4 系统用例图", size=16)

    # 系统边界
    c._d.rounded_rectangle(c._xy([(300, 70), (W - 20, H - 60)]), radius=c._s(10),
                           outline=C.GRAY_S, width=max(1, int(c._s(1.2))))

    # 角色（左列）
    actors = [
        (90, 150, "游客"),
        (90, 560, "失主"),
        (90, 1120, "拾得者"),
        (90, 1680, "管理员"),
    ]
    for cx, cy, label in actors:
        c.actor(cx, cy, label, scale=1.05, size=14)

    # 用例（椭圆）：(cx, cy, w, h, 文本)
    uc = [
        # 失主
        (440, 250, 230, 58, "发布失物"),
        (440, 380, 230, 58, "浏览匹配"),
        (440, 510, 230, 58, "认领"),
        (440, 640, 250, 58, "我要领走(keep1)"),
        (440, 770, 230, 58, "申诉"),
        # 拾得者
        (440, 980, 230, 58, "拍照发布"),
        (440, 1110, 270, 58, "选保管状态(keep0/keep1)"),
        (440, 1240, 260, 58, "确认归还/驳回"),
        # 管理员
        (440, 1430, 230, 58, "审核"),
        (440, 1560, 230, 58, "审计报表"),
        (440, 1690, 290, 58, "数据导出(v10新增)"),
        (440, 1820, 260, 58, "IM 轮询沟通"),
    ]
    for cx, cy, w, h, t in uc:
        c.ellipse_node((cx - w / 2, cy - h / 2, w, h), t, size=13)

    # 关联线：actor -> use case
    def link(actor_y, uc_y, ax=90):
        c.line((ax + 22, actor_y), (200, uc_y), color=C.LINE, width=1.4)

    link(560, 250); link(560, 380); link(560, 510); link(560, 640); link(560, 770)
    link(1120, 980); link(1120, 1110); link(1120, 1240)
    # 管理员关联
    c.line((112, 1680), (200, 1430), color=C.LINE, width=1.4)
    c.line((112, 1680), (200, 1560), color=C.LINE, width=1.4)
    c.line((112, 1680), (200, 1690), color=C.LINE, width=1.4)
    c.line((112, 1680), (200, 1820), color=C.LINE, width=1.4)
    # 游客关联：浏览匹配（也作为游客可用）
    c.line((112, 150), (200, 380), color=C.LINE, width=1.4, dash=(5, 4))

    # keep1 标注
    _note(c, 200, 640 + 46, "keep1: 物品留在原地，U2 完全隐藏", size=10, color=C.ORANGE_S)
    # v10 标注
    _note(c, 200, 1690 + 46, "v10 新增：数据导出 + IM 轮询沟通", size=10, color=C.GREEN_S)

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

    # 主链路箭头
    c.arrow(right(s1), left(s2), label="反向匹配命中")
    c.arrow(right(s2), left(s3), label="生成 match_record")
    c.arrow(right(s3), left(s4), label="失主认领(keep0)")
    c.arrow(right(s4), left(s5), label="拾得者确认归还")
    # 待交接 → 已解决（向下）
    c.arrow(bottom(s5), top(s6), label="双端扫码验证")

    # keep1 分支：待认领 → 待交接（跳过拾得者确认，U2 完全隐藏）
    c.arrow(right(s3), bottom(s3), color=C.ORANGE_S, head=False, label="")
    c.polyline([right(s3), offset(right(s3), 40, 0), (820, 400), bottom(s5)],
               color=C.ORANGE_S, width=1.6)
    c.arrow_head((910, 360), (0, 1), color=C.ORANGE_S, size=8)
    c.text(840, 360, "keep_status==1 & 我要领走\n(跳拾得者确认, U2 隐藏)", size=10.5,
           color=C.ORANGE_S, anchor="rm")

    # 认领中 → 已拒绝（驳回）
    c.polyline([bottom(s4), (790, 700), (560, 700), bottom(s7)],
               color=C.RED_S, width=1.6)
    c.arrow_head((560, 940), (0, 1), color=C.RED_S, size=8)
    c.text(600, 700, "拾得者驳回", size=10.5, color=C.RED_S, anchor="rm")

    # 已拒绝 → 待匹配（重入匹配池）
    c.arrow(top(s7), (560, 920), color=C.MUTED, head=False)
    c.polyline([(560, 920), (300, 920), (300, 120), bottom(s1)],
               color=C.MUTED, width=1.5, dash=(5, 4))
    c.arrow_head((120, 120), (0, 1), color=C.MUTED, size=8)
    c.text(310, 920, "重入匹配池", size=10.5, color=C.MUTED, anchor="lm")

    # 申诉（已拒绝 上 → 关闭）
    c.line((s7[0] + s7[2] / 2, s7[1]), (s7[0] + s7[2] / 2, 880), color=C.MUTED, width=1.4)
    c.text(s7[0] + s7[2] / 2 + 8, 880, "申诉成立→关闭(维持已拒绝)", size=10,
           color=C.MUTED, anchor="lm")

    return c.save(os.path.join(OUT_DIR, "fig_07_state.png"))


# ==========================================================================
# 图 3.9 E-R 图
# ==========================================================================
def fig_er() -> str:
    W, H = 1440, 940
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

    # 关系线 (a,b) + 标签
    def rel(a, b, lab, mult_a="1", mult_b="*"):
        ra, rb = rects[a], rects[b]
        p0 = (ra[0] + ra[2], ra[1] + ra[3] / 2)
        p1 = (rb[0], rb[1] + rb[3] / 2)
        c.line(p0, p1, color=C.LINE, width=1.4)
        c.text(p0[0] - 6, p0[1] - 8, mult_a, size=11, color=C.MUTED, anchor="rm")
        c.text(p1[0] + 6, p1[1] - 8, mult_b, size=11, color=C.MUTED, anchor="lm")
        mx = (p0[0] + p1[0]) / 2
        c.text(mx, p0[1] - 8, lab, size=10.5, color=C.MUTED, anchor="mm")

    rel("user", "lost_item", "发布")
    rel("user", "found_item", "发布")
    rel("user", "trust_score_log", "记分")
    rel("user", "audit_log", "操作")
    rel("category", "lost_item", "标注")
    rel("category", "found_item", "标注")
    rel("lost_item", "match_record", "参与")
    rel("found_item", "match_record", "参与")
    rel("match_record", "handover_code", "生成", mult_a="1", mult_b="1")
    rel("match_record", "im_session", "开启")
    rel("lost_item", "im_session", "涉及")
    rel("found_item", "im_session", "涉及")
    rel("im_session", "im_message", "包含")

    # 高亮 keep_status
    _note(c, 800, 470, "found_item.keep_status 字段：0=需认领 / 1=留在原地(keep1)",
          size=11, color=C.ORANGE_S)
    _note(c, 800, 805, "handover_code.expire_at：交接码过期时间存 DB（非 Redis TTL）",
          size=11, color=C.GREEN_S)

    return c.save(os.path.join(OUT_DIR, "fig_09_er.png"))


# ==========================================================================
# 图 3.10 类图
# ==========================================================================
def fig_class() -> str:
    W, H = 1520, 1120
    c = Canvas(W, H, ss=3)
    _title(c, 24, 26, "图 3.10 服务层类图", size=15)

    entities = {
        "User": (40, 60, 300, 130, ["- user_id: int", "- name: str", "- role: str",
                                    "- trust_score: float"]),
        "LostItem": (40, 250, 300, 130, ["- lost_id: int", "- cat_id: int",
                                         "- desc: str", "- status: str"]),
        "FoundItem": (40, 440, 300, 150, ["- found_id: int", "- cat_id: int",
                                          "- photo: str", "- keep_status: int ★"]),
        "MatchRecord": (40, 640, 300, 140, ["- match_id: int", "- lost_id: int",
                                            "- found_id: int", "- score: float"]),
        "HandoverCode": (40, 850, 300, 130, ["- code_id: int", "- match_id: int",
                                             "- code: str", "- expire_at: dt"]),
        "IMSession": (380, 60, 300, 120, ["- session_id: int", "- lost_id: int",
                                          "- found_id: int"]),
        "IMMessage": (380, 240, 300, 120, ["- msg_id: int", "- session_id: int",
                                           "- content: str"]),
        "TrustScoreLog": (380, 430, 300, 130, ["- log_id: int", "- user_id: int",
                                               "- delta: float", "- reason: str"]),
        "AuditLog": (380, 620, 300, 140, ["- audit_id: int", "- op: str",
                                          "- detail: str", "- partition_month"]),
    }
    services = {
        "PublishService": (820, 60, 320, 120, ["+ publish()", "+ reverse_match()"]),
        "VisionService": (820, 250, 320, 150, ["+ predict(photo)", "+ 进程内单例"]),
        "MatchService": (820, 460, 320, 140, ["+ score()", "+ claim()", "+ reject()"]),
        "HandoverService": (820, 670, 320, 120, ["+ confirm()", "+ gen_code()"]),
        "IMService": (820, 850, 320, 110, ["+ poll(4s)", "+ send()"]),
        "AuditService": (1180, 60, 320, 120, ["+ write()", "+ report()"]),
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

    # 依赖线：service -> entity
    def dep(s, e, dash=False):
        rs, re = s_rects[s], e_rects[e]
        p0 = (rs[0], rs[1] + rs[3] / 2)
        p1 = (re[0] + re[2], re[1] + re[3] / 2)
        c.line(p0, p1, color=C.MUTED, width=1.3, dash=(5, 4) if dash else None)

    dep("PublishService", "FoundItem")
    dep("PublishService", "LostItem")
    dep("MatchService", "MatchRecord")
    dep("MatchService", "LostItem")
    dep("MatchService", "FoundItem")
    dep("HandoverService", "HandoverCode")
    dep("HandoverService", "MatchRecord")
    dep("IMService", "IMSession")
    dep("IMService", "IMMessage")
    dep("AuditService", "AuditLog")
    dep("AuditService", "TrustScoreLog")

    # VisionService 进程内单例（虚线，PublishService 调用）
    c.line(right(s_rects["PublishService"]), left(s_rects["VisionService"]),
           color=C.PURPLE_S, width=1.5, dash=(5, 4))
    c.text((s_rects["PublishService"][0] + s_rects["VisionService"][0]) / 2,
           s_rects["PublishService"][1] + s_rects["PublishService"][3] + 14,
           "进程内调用（非微服务）", size=10.5, color=C.PURPLE_S, anchor="mm")

    # 标注
    c.box((820, 910, 680, 70),
          ["VisionService: YOLOv8s(best.pt, 12类) 进程内单例"],
          fill=C.PURPLE_F, stroke=C.PURPLE_S, size=12)
    c.box((820, 1000, 680, 56),
          ["YOLO-World 代码保留未接线（mode=0 休眠）"],
          fill=C.GRAY_F, stroke=C.GRAY_S, size=11, dash=True)

    return c.save(os.path.join(OUT_DIR, "fig_10_class.png"))


# ==========================================================================
# 图 3.11 部署图
# ==========================================================================
def fig_deploy() -> str:
    W, H = 1600, 600
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
    c.box((440, 480, 520, 80),
          ["Redis：生产可选 · 默认关闭（内存兜底）"],
          fill=C.GRAY_F, stroke=C.GRAY_S, size=12, dash=True)

    # 箭头
    c.arrow(right((40, 200, 280, 180)), left((440, 150, 520, 300)),
            label="HTTPS JSON + IM 轮询(4s)", label_size=12, color=C.BLUE_S)
    c.arrow(right((440, 150, 520, 300)), left((1060, 200, 300, 200)),
            label="SQLAlchemy ORM", label_size=12, color=C.TEAL_S)
    c.arrow(bottom((440, 150, 520, 300)), top((440, 480, 520, 80)),
            label="可选", label_size=11, color=C.MUTED, dash=(5, 4))

    _note(c, 40, 560, "无独立推理微服务 / 无 WebSocket 服务器；IM 为前端 4s 轮询",
          size=11, color=C.MUTED)

    return c.save(os.path.join(OUT_DIR, "fig_11_deploy.png"))


# ==========================================================================
# 图 4.1 功能模块流程图
# ==========================================================================
def fig_flow() -> str:
    W, H = 1020, 1760
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
    # d3 reject 分支回退
    c.polyline([bottom(d3), (cx - 360, center(d3)[1]), (cx - 360, center(n4)[1]),
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
    W, H = 1320, 600
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
