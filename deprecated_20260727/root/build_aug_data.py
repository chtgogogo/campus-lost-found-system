"""
失物招领系统 · 训练数据增广管道
================================
从 LoremFlickr（Flickr 知识共享 CC 图，按关键词取图，无需 API key）下载免费图片，
为「检测模型」自动生成 YOLO 格式边界框（整图伪框，假设物体为画面主体），
按类分文件夹存放，可直接合并进训练集重训。

为什么需要这一步：
  best.pt 是 YOLOv8 *检测* 模型，训练需要「图片 + 边界框标注(.txt)」，不是只分文件夹。
  模型自身预测不可作标签（会放大错误），故用外部自由图源 + 伪框增广弱类。

用法:
  python build_aug_data.py                 # 默认拉弱类(钱包/钥匙/校园卡)+眼镜/笔记本
  python build_aug_data.py --per 80        # 每类张数
  python build_aug_data.py --classes wallet,keys   # 只拉指定类

输出目录:
  aug_data/images/train/*.jpg
  aug_data/labels/train/*.txt   (YOLO 格式: class_id cx cy w h, 归一化)
  aug_data/report.txt           (下载统计)
"""
import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

PROJECT = Path(__file__).resolve().parent
OUT = PROJECT / "aug_data"
IMG_DIR = OUT / "images" / "train"
LBL_DIR = OUT / "labels" / "train"

# (我们的类id, LoremFlickr 关键词, 默认张数)
# 类id 对齐 best.pt / seed: 0手机 1钱包 2钥匙 3书包 4行李箱 5笔记本电 6校园卡 7眼镜 8笔记本 9雨伞 10水杯
DEFAULT_TARGETS = [
    (1, "wallet", 60),        # 钱包（弱类，最缺）
    (2, "keys", 60),          # 钥匙（弱类，最缺）
    (6, "student,id", 60),     # 校园卡（弱类；用 student id 卡作近似）
    (7, "eyeglasses", 40),     # 眼镜（补充）
    (8, "notebook", 40),       # 笔记本（补充）
]

W, H = 416, 312
HEADERS = {"User-Agent": "Mozilla/5.0 (aug-pipe)"}


def fetch_one(class_id: int, keyword: str, idx: int) -> tuple[str, bool, str]:
    """下载一张图并写伪框。返回 (filename, ok, note)。"""
    # lock 使每张图确定且互不相同
    url = f"https://loremflickr.com/{W}/{H}/{keyword}?lock={class_id * 100000 + idx}"
    fname = f"{keyword.replace(',', '_')}_{class_id}_{idx:04d}.jpg"
    fpath = IMG_DIR / fname
    lpath = LBL_DIR / (fname[:-4] + ".txt")
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=25)
            if r.status_code == 200 and r.content[:2] == b"\xff\xd8":
                fpath.write_bytes(r.content)
                # 整图伪框：中心(0.5,0.5)，宽高 0.98（留 1% 边距）
                lpath.write_text(f"{class_id} 0.5 0.5 0.98 0.98\n")
                return (fname, True, "ok")
            time.sleep(0.5)
        except Exception as e:  # noqa
            time.sleep(1.0)
    return (fname, False, "fail")


def download_class(class_id: int, keyword: str, count: int) -> int:
    ok = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(fetch_one, class_id, keyword, i) for i in range(1, count + 1)]
        for f in as_completed(futs):
            _, success, _ = f.result()
            ok += 1 if success else 0
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per", type=int, default=None, help="每类张数(覆盖默认)")
    ap.add_argument("--classes", type=str, default=None, help="只拉指定类, 逗号分隔, 如 wallet,keys")
    args = ap.parse_args()

    targets = DEFAULT_TARGETS
    if args.classes:
        want = set(args.classes.split(","))
        targets = [t for t in DEFAULT_TARGETS if t[1].split(",")[0] in want]
    if args.per:
        targets = [(cid, kw, args.per) for (cid, kw, _) in targets]

    IMG_DIR.mkdir(parents=True, exist_ok=True)
    LBL_DIR.mkdir(parents=True, exist_ok=True)

    print(f"目标输出: {OUT}")
    print(f"将下载类: {[t[1] for t in targets]}")
    print("-" * 60)

    report_lines = []
    total_ok = 0
    for cid, kw, n in targets:
        t0 = time.time()
        ok = download_class(cid, kw, n)
        dt = time.time() - t0
        line = f"{kw:12s} 类id={cid}  成功 {ok}/{n}  耗时 {dt:.1f}s"
        print(line)
        report_lines.append(line)
        total_ok += ok

    # 写报告
    (OUT / "report.txt").write_text(
        "\n".join(report_lines) + f"\n\n总计成功 {total_ok} 张\n"
        f"图片: {IMG_DIR}\n标签: {LBL_DIR}\n"
    )
    print("-" * 60)
    print(f"✅ 完成，共 {total_ok} 张。下一步：合并进训练集并重训。")


if __name__ == "__main__":
    main()
