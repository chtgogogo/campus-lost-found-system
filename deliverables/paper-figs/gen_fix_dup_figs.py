# -*- coding: utf-8 -*-
"""生成 3 张正确的论文图，替换 md5 重复的错图：
   fig3_3 数据类图  -> 替换 图3.3（原错用 图3.10 服务层类图 rId24）
   fig3_6 活动图    -> 替换 图3.6（原错用 图4.1 流程图 rId28）
   fig4_1 流程图    -> 替换 图4.1（两处 rId28），与服务层类图/活动图 均不同
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Polygon
import os

OUT = os.path.dirname(os.path.abspath(__file__))
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
BLUE = '#3a6ea5'
GREEN = '#2e8b57'
ORANGE = '#cc6600'
GREY = '#666666'


def _box(ax, x, y, w, h, title, lines, fc='#eef3ff', ec=BLUE, tcolor='#1f3a5f'):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.04",
                                fc=fc, ec=ec, lw=1.5))
    ax.text(x + w / 2, y + h - 0.22, title, ha='center', va='center',
            fontsize=10.5, fontweight='bold', color=tcolor)
    for i, ln in enumerate(lines):
        ax.text(x + 0.12, y + h - 0.55 - i * 0.32, ln, ha='left', va='center',
                fontsize=8.2, color='#333')
    return y + h


def _arrow(ax, x1, y1, x2, y2, color='#444', style='->'):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style,
                                 mutation_scale=14, color=color, lw=1.4))


# ---------------- 图 3.3 数据类图 ----------------
def gen_dataclass():
    fig, ax = plt.subplots(figsize=(9.2, 7.0))
    ax.set_xlim(0, 10); ax.set_ylim(0, 8); ax.axis('off')
    classes = [
        ('User 用户', ['+id: int (PK)', '+student_no', '+role: 0/1', '+credit_score']),
        ('Category 分类', ['+id: int (PK)', '+name', '+kind']),
        ('LostItem 失物', ['+id (PK)', '+publisher_id (FK)', '+category_id (FK)', '+image_hash', '+status']),
        ('FoundItem 拾物', ['+id (PK)', '+finder_id (FK)', '+category_id (FK)', '+image_hash', '+keep_status']),
        ('MatchRecord 匹配', ['+id (PK)', '+lost_id (FK)', '+found_id (FK)', '+match_score', '+status']),
        ('HandoverCode 交接码', ['+match_id (PK,FK)', '+lost_code / finder_code', '+*_expire', '+*_verified']),
        ('IMSession 会话', ['+id (PK)', '+lost_user_id (FK)', '+finder_user_id (FK)']),
        ('IMMessage 消息', ['+id (PK)', '+session_id (FK)', '+sender_id (FK)']),
        ('AuditLog 审计', ['+id (PK)', '+user_id (FK)', '+action', '+gps']),
        ('TrustScoreLog 信用', ['+id (PK)', '+user_id (FK)', '+delta']),
    ]
    # 两列布局
    col_x = [0.4, 5.2]
    y_top = 7.6
    h = 1.15
    gap = 0.28
    positions = {}
    for i, (name, lines) in enumerate(classes):
        col = i % 2
        row = i // 2
        x = col_x[col]
        y = y_top - row * (h + gap)
        _box(ax, x, y - h, 4.0, h, name, lines)
        positions[name] = (x + 4.0, y - h / 2)
    # 关系（简线，带基数标注）
    rel = [
        ('User 用户', 'LostItem 失物', '1—*'),
        ('User 用户', 'FoundItem 拾物', '1—*'),
        ('Category 分类', 'LostItem 失物', '1—*'),
        ('Category 分类', 'FoundItem 拾物', '1—*'),
        ('LostItem 失物', 'MatchRecord 匹配', '1—*'),
        ('FoundItem 拾物', 'MatchRecord 匹配', '1—*'),
        ('MatchRecord 匹配', 'HandoverCode 交接码', '1—1'),
        ('User 用户', 'IMSession 会话', '1—*'),
        ('IMSession 会话', 'IMMessage 消息', '1—*'),
        ('User 用户', 'AuditLog 审计', '1—*'),
        ('User 用户', 'TrustScoreLog 信用', '1—*'),
    ]
    for a, b, label in rel:
        if a in positions and b in positions:
            xa, ya = positions[a]
            xb, yb = positions[b]
            mx = (xa + xb) / 2
            _arrow(ax, xa, ya, xb, yb, color=GREY)
            ax.text(mx, (ya + yb) / 2 + 0.1, label, ha='center', fontsize=7, color=GREY)
    ax.set_title('图 3.3 数据类图（10 张表实体及关系）', fontsize=12, fontweight='bold', color='#1f3a5f')
    fig.savefig(os.path.join(OUT, 'fig3_3_dataclass.png'), dpi=200, bbox_inches='tight')
    fig.savefig(os.path.join(OUT, 'fig3_3_dataclass.svg'), bbox_inches='tight')
    plt.close(fig)
    print('fig3_3 done')


# ---------------- 图 3.6 活动图 ----------------
def _act(ax, x, y, w, h, text, fc='#eef3ff', ec=BLUE):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.35",
                                fc=fc, ec=ec, lw=1.5))
    ax.text(x + w / 2, y + h / 2, text, ha='center', va='center', fontsize=9, color='#1f3a5f')


def _dec(ax, x, y, r, text):
    ax.add_patch(Polygon([(x, y - r), (x + r, y), (x, y + r), (x - r, y)],
                         closed=True, fc='#fff7e6', ec=ORANGE, lw=1.5))
    ax.text(x, y, text, ha='center', va='center', fontsize=8.5, color=ORANGE)


def gen_activity():
    fig, ax = plt.subplots(figsize=(6.5, 8.2))
    ax.set_xlim(0, 7); ax.set_ylim(0, 17); ax.axis('off')
    cx = 3.5
    bw, bh = 4.2, 0.7
    steps = [
        ('失主发布失物信息', 16.0),
        ('系统视觉打标 (YOLOv8s 进程内)', 14.4),
        ('拾得者发布拾物信息', 12.8),
        ('匹配引擎 · 六维加权打分', 11.2),
        ('生成候选并推送失主', 9.6),
        ('失主认领 (填理由/凭证)', 8.0),
        ('拾得者确认归还', 6.4),
    ]
    for text, y in steps:
        _act(ax, cx - bw / 2, y, bw, bh, text)
    _dec(ax, cx, 4.8, 0.7, '双方\n各生成码?')
    _act(ax, cx - bw / 2, 3.0, bw, bh, '双码交叉验证 (各 4 位,10s)', fc='#eafaf0', ec=GREEN)
    _act(ax, cx - bw / 2, 1.2, bw, bh, '交接完成 · 审计黑匣子记录', fc='#eafaf0', ec=GREEN)
    # 箭头
    ys = [16.0 + bh, 14.4 + bh, 12.8 + bh, 11.2 + bh, 9.6 + bh, 8.0 + bh, 6.4 + bh]
    for y0 in ys:
        _arrow(ax, cx, y0, cx, y0 - 0.3)
    _arrow(ax, cx, 4.8 + 0.7, cx, 3.0 + bh)
    _arrow(ax, cx, 3.0, cx, 1.2 + bh)
    # 起点/终点
    ax.scatter([cx], [16.9], s=90, color=BLUE, zorder=5)
    ax.text(cx, 16.9, '开始', ha='center', va='bottom', fontsize=8, color=BLUE)
    ax.scatter([cx], [1.2 - 0.35], s=90, facecolors='none', edgecolors=BLUE, linewidths=1.8, zorder=5)
    ax.set_title('图 3.6 发布-匹配-交接 活动图', fontsize=12, fontweight='bold', color='#1f3a5f')
    fig.savefig(os.path.join(OUT, 'fig3_6_activity.png'), dpi=200, bbox_inches='tight')
    fig.savefig(os.path.join(OUT, 'fig3_6_activity.svg'), bbox_inches='tight')
    plt.close(fig)
    print('fig3_6 done')


# ---------------- 图 4.1 功能模块流程图 ----------------
def gen_flow():
    fig, ax = plt.subplots(figsize=(9.0, 3.8))
    ax.set_xlim(0, 10); ax.set_ylim(0, 4); ax.axis('off')
    mods = [
        ('发布模块', '拍照/填表'),
        ('视觉打标模块', 'YOLOv8s 进程内'),
        ('匹配模块', '六维加权打分'),
        ('认领模块', '理由/凭证'),
        ('交接模块', '双码交叉验证'),
        ('IM 模块', '轮询 4s'),
        ('审计模块', '黑匣子'),
    ]
    n = len(mods)
    w = 1.15
    ys = 2.3
    xs = [0.4 + i * 1.32 for i in range(n)]
    for (name, sub), x in zip(mods, xs):
        _box(ax, x, ys, w, 1.0, name, [sub], fc='#eef3ff', ec=BLUE)
    for i in range(n - 1):
        _arrow(ax, xs[i] + w, ys + 0.5, xs[i + 1], ys + 0.5, color='#444')
    ax.text(5.0, 1.0, '核心业务功能模块流程图（发布 → 打标 → 匹配 → 认领 → 交接，IM 与审计贯穿全程）',
            ha='center', fontsize=9, color=GREY)
    ax.set_title('图 4.1 核心业务功能模块流程图', fontsize=12, fontweight='bold', color='#1f3a5f')
    fig.savefig(os.path.join(OUT, 'fig4_1_flow.png'), dpi=200, bbox_inches='tight')
    fig.savefig(os.path.join(OUT, 'fig4_1_flow.svg'), bbox_inches='tight')
    plt.close(fig)
    print('fig4_1 done')


if __name__ == '__main__':
    gen_dataclass()
    gen_activity()
    gen_flow()
    print('ALL DONE')
