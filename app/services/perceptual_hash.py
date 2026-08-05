"""感知哈希（pHash）服务（v3 增量，需求 C）。

零新增依赖：复用既有 **Pillow**（`PIL.Image`）做灰度 / 缩放，DCT 用纯 `math` 实现，
不引入 `imagehash` / `numpy` / `scipy`（设计决策 Q2）。

算法：
1. 输入字节 → PIL 解码 → 灰度。
2. 缩放至 32×32（LANCZOS）。
3. 2D-DCT（纯 Python/math，32×32 矩阵极小，开销可忽略）。
4. 取左上 8×8（排除 DC 直流分量 [0,0]），按中值阈值生成 63-bit 哈希。
5. 序列化为 16 位十六进制字符串（64-bit 宽度，高位补 0）。

相似度：`hamming_sim(h1, h2) = 1 - hamming_dist / 64 ∈ [0, 1]`；
任一缺失（空串 / None）降级为 `0.0`，不阻断匹配（Q2）。

降级铁律：`compute` 解码失败返回空串 `""`，调用方将其视为缺失。
"""
from __future__ import annotations

import io
import math
import statistics

from PIL import Image

_HASH_BITS = 64  # 16-hex 宽度


def _dct_2d(matrix: list[list[float]]) -> list[list[float]]:
    """2D DCT-II（朴素实现，O(n^4)，32×32 规模可接受）。"""
    n = len(matrix)
    result: list[list[float]] = [[0.0] * n for _ in range(n)]
    for u in range(n):
        cu = 1.0 / math.sqrt(2) if u == 0 else 1.0
        for v in range(n):
            cv = 1.0 / math.sqrt(2) if v == 0 else 1.0
            total = 0.0
            for x in range(n):
                for y in range(n):
                    total += (
                        matrix[x][y]
                        * math.cos(math.pi * (2 * x + 1) * u / (2 * n))
                        * math.cos(math.pi * (2 * y + 1) * v / (2 * n))
                    )
            result[u][v] = 0.5 * cu * cv * total
    return result


def compute(image_bytes: bytes) -> str:
    """对图片字节计算感知哈希，返回 16-hex 字符串；失败返回空串。"""
    if not image_bytes:
        return ""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("L")
    except Exception:
        return ""
    try:
        img = img.resize((32, 32), Image.LANCZOS)
        pixels = list(img.getdata())
        matrix = [pixels[i * 32 : (i + 1) * 32] for i in range(32)]
        dct = _dct_2d(matrix)
        # 取左上 8×8，排除 DC（0,0）
        vals: list[float] = []
        for u in range(8):
            for v in range(8):
                if u == 0 and v == 0:
                    continue
                vals.append(dct[u][v])
        if not vals:
            return ""
        median = statistics.median(vals)
        bits = [1 if val > median else 0 for val in vals]
        hash_int = 0
        for b in bits:
            hash_int = (hash_int << 1) | b
        return format(hash_int, "016x")
    except Exception:
        return ""


def hamming_sim(h1: str | None, h2: str | None) -> float:
    """Hamming 距离 → 相似度 ∈ [0, 1]；任一缺失返回 0.0。"""
    if not h1 or not h2:
        return 0.0
    try:
        a = int(h1, 16)
        b = int(h2, 16)
    except ValueError:
        return 0.0
    xor = a ^ b
    dist = bin(xor).count("1")
    # 以两者较长者的 bit 长度为分母，保证 ∈ [0,1]
    denom = max(len(h1), len(h2)) * 4
    if denom <= 0:
        return 0.0
    return max(0.0, 1.0 - dist / float(denom))


class PerceptualHash:
    """感知哈希工具类（供服务层以 `PerceptualHash.compute / hamming_sim` 调用）。"""

    @staticmethod
    def compute(image_bytes: bytes) -> str:
        return compute(image_bytes)

    @staticmethod
    def hamming_sim(h1: str | None, h2: str | None) -> float:
        return hamming_sim(h1, h2)
