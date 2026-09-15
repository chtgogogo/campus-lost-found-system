"""匹配评测脚本（v13）：在标注数据集上跑七维打分引擎，输出精度/召回基线。

用法::

    .venv/Scripts/python.exe evaluation/run_eval.py            # 阈值取 settings.MATCH_THRESHOLD
    .venv/Scripts/python.exe evaluation/run_eval.py --threshold 70

不依赖数据库/视觉模型：直接构造与 ORM 对象同构的 SimpleNamespace 喂给
MatchService.score()（v10 七维均为文本/类目/时间维度，无需真实图片）。
每次调权重后重跑本脚本，分数变化即调优依据（结果写入 evaluation/results-v13.md）。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.services.match_service import MatchService  # noqa: E402

_HERE = Path(__file__).parent


def _make_item(side: dict, is_lost: bool) -> SimpleNamespace:
    """把数据集里的一侧物品转成打分引擎所需的最小字段集。"""
    return SimpleNamespace(
        title=side.get("title") if is_lost else None,
        description=side.get("description") or "",
        category_name=side.get("category_name") or "",
        category_id=None,  # 统一走名称比对，让 v12 家族逻辑生效
        tags=[],
        appearance=None,
        features=None,
        location=side.get("location") or "",
        lost_time=_parse_dt(side.get("lost_time")) if is_lost else None,
        found_time=_parse_dt(side.get("found_time")) if not is_lost else None,
    )


def _parse_dt(raw: str | None) -> datetime | None:
    return datetime.fromisoformat(raw) if raw else None


def run(threshold: float, dataset_file: str = "dataset.json") -> dict:
    dataset = json.loads((_HERE / dataset_file).read_text(encoding="utf-8"))
    matcher = MatchService()
    rows: list[dict] = []
    for pair in dataset["pairs"]:
        lost = _make_item(pair["lost"], is_lost=True)
        found = _make_item(pair["found"], is_lost=False)
        score = matcher.score(lost, found)
        predicted = score >= threshold
        label = bool(pair["label"])
        if label and predicted:
            verdict = "TP"
        elif label and not predicted:
            verdict = "FN"
        elif not label and predicted:
            verdict = "FP"
        else:
            verdict = "TN"
        rows.append(
            {
                "id": pair["id"],
                "note": pair.get("note", ""),
                "label": label,
                "score": score,
                "predicted": predicted,
                "verdict": verdict,
            }
        )

    tp = sum(1 for r in rows if r["verdict"] == "TP")
    fp = sum(1 for r in rows if r["verdict"] == "FP")
    fn = sum(1 for r in rows if r["verdict"] == "FN")
    tn = sum(1 for r in rows if r["verdict"] == "TN")
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "threshold": threshold,
        "rows": rows,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision, "recall": recall, "f1": f1,
    }


def render(result: dict) -> str:
    lines = [
        f"# 评测结果（阈值 {result['threshold']}）",
        "",
        f"- TP={result['tp']}  FP={result['fp']}  FN={result['fn']}  TN={result['tn']}",
        f"- 精确率 precision = {result['precision']:.1%}",
        f"- 召回率 recall    = {result['recall']:.1%}",
        f"- F1               = {result['f1']:.1%}",
        "",
        "| ID | 判定 | 标注 | 预测 | 分数 | 说明 |",
        "|---|---|---|---|---|---|",
    ]
    for r in result["rows"]:
        mark = {"TP": "✅", "TN": "✅", "FP": "❌误配", "FN": "⚠️漏配"}[r["verdict"]]
        lines.append(
            f"| {r['id']} | {mark} | {'正' if r['label'] else '负'} | "
            f"{'配' if r['predicted'] else '不配'} | {r['score']:.1f} | {r['note']} |"
        )
    borderline = [r for r in result["rows"] if 60 <= r["score"] < result["threshold"]]
    if borderline:
        lines += ["", f"## 边界样本（60~阈值，共 {len(borderline)} 条）", ""]
        lines += [f"- {r['id']}（{r['score']:.1f}）：{r['note']}" for r in borderline]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="匹配引擎评测")
    parser.add_argument("--threshold", type=float, default=float(settings.MATCH_THRESHOLD))
    parser.add_argument("--dataset", type=str, default="dataset.json",
                        help="评测集文件名（位于 evaluation/ 下，如 dataset_control.json）")
    parser.add_argument("--out", type=str, default="results-v13.md", help="结果输出文件名")
    args = parser.parse_args()
    result = run(args.threshold, args.dataset)
    report = render(result)
    out = _HERE / args.out
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"[已写入 {out.name}]")
