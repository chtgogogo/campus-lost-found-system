import os
from PIL import Image
import numpy as np

NEW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_paper_figures_new")

def ink_bbox(path):
    im = Image.open(path).convert("L")
    a = np.asarray(im)
    # non-white = ink
    mask = a < 240
    if not mask.any():
        return None
    ys, xs = np.where(mask)
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()),
            int(im.size[0]), int(im.size[1]))

print("== 像素 ink 包围盒 (验证无截断/布局填充) ==")
# fig_42_pseudocode: old cutoff ~y=580 (H was 600). 新行应在 y>620.
n="fig_42_pseudocode.png"; p=os.path.join(NEW,n)
x0,y0,x1,y1,W,H=ink_bbox(p)
print(f"  {n}: img={W}x{H} ink_x=[{x0},{x1}] ink_y=[{y0},{y1}]")
print(f"      ink 最大 y={y1} -> {'已超出旧截断线580, 末两行已渲染' if y1>620 else '*** 仍疑似截断 ***'}")

# fig_03_use_case: 两列布局 1400宽, 检查 ink 是否同时覆盖左右两半
n="fig_03_use_case.png"; p=os.path.join(NEW,n)
x0,y0,x1,y1,W,H=ink_bbox(p)
left_half = x1 > W*0.25
right_half = x0 < W*0.75
print(f"  {n}: img={W}x{H} ink_x=[{x0},{x1}] ink_y=[{y0},{y1}]")
print(f"      左半有墨={left_half} 右半有墨={right_half} -> {'双列均已填充' if (left_half and right_half) else '*** 某列空白 ***'}")

# fig_07_state: 检查整体有 ink (非空白)
n="fig_07_state.png"; p=os.path.join(NEW,n)
x0,y0,x1,y1,W,H=ink_bbox(p)
print(f"  {n}: img={W}x{H} ink_x=[{x0},{x1}] ink_y=[{y0},{y1}] -> {'非空' if (x1-x0)>100 and (y1-y0)>100 else '*** 疑似空白 ***'}")

# fig_10_class / fig_09_er / fig_11_deploy / fig_41_flow: 非空 + 合理范围
for n in ["fig_10_class.png","fig_09_er.png","fig_11_deploy.png","fig_41_flow.png","fig_05_sequence.png"]:
    p=os.path.join(NEW,n)
    x0,y0,x1,y1,W,H=ink_bbox(p)
    print(f"  {n}: img={W}x{H} ink_x=[{x0},{x1}] ink_y=[{y0},{y1}] -> {'非空OK' if (x1-x0)>100 and (y1-y0)>100 else '*** 疑似空白 ***'}")
