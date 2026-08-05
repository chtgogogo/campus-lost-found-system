"""
失物招领系统 · 合并增广数据 + 输出重训命令
============================================
把 build_aug_data.py 产出的 aug_data/ 合并进【项目内自包含数据集】dataset/final。

数据源演变：
- 历史来源是 E:\\mod\\processed\\final（约 3.96 万张，11 类）。
- 现已把该数据集一次性复制进项目 dataset/final（见 bootstrap()），
  之后训练/合并只依赖项目内数据，不再读取 E:\\mod，故 E:\\mod 可安全删除。
- aug_data/ 是弱类增广「源头」，随时可重新合并进 dataset/final。

用法:
  python merge_and_retrain.py                 # 首次：复制主集 + 合并增广 + 清缓存 + 打印命令
  python merge_and_retrain.py --dry           # 只打印将做什么，不改动
"""
import argparse
import shutil
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
AUG = PROJECT / "aug_data"
FINAL = PROJECT / "dataset" / "final"             # 项目内自包含数据集（训练读取这里）
SRC_FINAL = Path(r"E:\mod\processed\final")       # 一次性来源（删除 E:\mod 前必须跑一次本脚本完成复制）


def _rewrite_data_yaml() -> None:
    """把 data.yaml 的 path 改为相对【项目根目录】的 'dataset/final'。

    注意：本机 ultralytics 版本会把相对 path 解析为「运行训练时的 CWD（项目根目录）」，
    而非 yaml 文件所在目录。因此 path 必须是相对项目根的路径（'dataset/final'），
    不能用 '.'（会被解析成项目根，导致 images/val 找不到）。
    """
    p = FINAL / "data.yaml"
    if not p.exists():
        return
    lines = p.read_text(encoding="utf-8").splitlines()
    out = ["path: dataset/final" if ln.startswith("path:") else ln for ln in lines]
    p.write_text("\n".join(out) + "\n", encoding="utf-8")


def bootstrap(dry: bool = False) -> bool:
    """首次把 E:\\mod\\processed\\final 复制进项目 dataset/final（仅一次）。返回是否就绪。"""
    if FINAL.exists() and any(FINAL.rglob("*.jpg")):
        print(f"[bootstrap] 已存在自包含数据集: {FINAL}，跳过复制")
        return True
    if not SRC_FINAL.exists():
        print(f"[ERROR] 未找到来源数据集: {SRC_FINAL}\n"
              "请先确认 E:\\mod 还在（删除 E:\\mod 前必须成功跑一次本脚本完成复制）。")
        return False
    print(f"[bootstrap] 复制主训练集 {SRC_FINAL} -> {FINAL} ...")
    if dry:
        print("[DRY] 未复制")
        return False
    shutil.copytree(SRC_FINAL, FINAL)
    _rewrite_data_yaml()
    train_n = len(list((FINAL / "images" / "train").glob("*.jpg")))
    print(f"✅ 已复制主训练集到项目内（{train_n} 张 train），此后训练不再依赖 E:\\mod")
    return True


def merge(dry: bool = False) -> None:
    src_img = AUG / "images" / "train"
    src_lbl = AUG / "labels" / "train"
    dst_img = FINAL / "images" / "train"
    dst_lbl = FINAL / "labels" / "train"

    if not FINAL.exists():
        print("[ERROR] dataset/final 不存在，请先运行本脚本完成 bootstrap 复制")
        return
    if not src_img.exists():
        print(f"[ERROR] 未找到增广数据: {src_img}\n请先运行 build_aug_data.py")
        return

    jpgs = list(src_img.glob("*.jpg"))
    print(f"待合并增广图: {len(jpgs)} 张 (来自 {src_img})")
    print(f"目标训练集: {dst_img}")

    if dry:
        print("[DRY] 未做任何改动。")
        return

    dst_img.mkdir(parents=True, exist_ok=True)
    dst_lbl.mkdir(parents=True, exist_ok=True)
    n = 0
    for jpg in jpgs:
        shutil.copy2(jpg, dst_img / jpg.name)
        txt = src_lbl / (jpg.stem + ".txt")
        if txt.exists():
            shutil.copy2(txt, dst_lbl / txt.name)
        n += 1

    # 清缓存，强制 ultralytics 重建标签索引
    for c in (FINAL / "labels").glob("*.cache"):
        c.unlink()
    train_n = len(list(dst_img.glob("*.jpg")))
    print(f"✅ 已合并 {n} 张增广图 + 标注到 {FINAL}")
    print(f"   新 train 图数: {train_n}")

    print("\n" + "=" * 60)
    print("下一步：在你本机 GPU 上运行（务必在项目根目录，且一次只跑一个进程）")
    print("=" * 60)
    print(r'python tools/dataset_prep/train_yolov8.py '
          r'--data "dataset/final/data.yaml" '
          r'--workers 0 --epochs 80 --name lostfound_v2')
    print("\n说明:")
    print("  - 只启动【一个】训练进程！之前 4 个并发把系统内存打爆导致 OOM 崩溃")
    print("  - --model 默认 yolov8n.pt（COCO 预训练），从零在合并集上训，最稳")
    print("  - 想复用上次崩溃前 22 轮权重做 warm-start：")
    print("      --model runs/detect/runs/detect/lostfound_v2/weights/last.pt")
    print("  - 训前关掉浏览器/IDE 释放内存；若仍 OOM 用 --batch 4 --imgsz 416")
    print("  - 训完把 best.pt 复制覆盖 models/weights/best.pt")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只打印，不改动")
    args = ap.parse_args()
    if bootstrap(dry=args.dry):
        merge(dry=args.dry)
