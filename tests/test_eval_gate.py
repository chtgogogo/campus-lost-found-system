"""v17 评测 CI 门禁单测（任务①）。

两层验证：
1. 单元级：``check_gate`` 的判定语义（等于阈值=通过 / 低于=阻断 / None=不启用）。
2. 端到端：以子进程真实执行 ``evaluation/run_eval.py``，
   - 缺省门禁（settings.EVAL_FAIL_UNDER=76，主集 F1 78.0）→ 退出码 0；
   - ``--fail-under 99``（故意不可能达到）→ 退出码 1 —— 门禁真的会挡的直接证据
     （执行指令①验收项：阈值临时设 99 验证会挡）。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from evaluation.run_eval import check_gate

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _fake_result(f1: float) -> dict:
    return {"f1": f1}


# ---------------- 单元级：check_gate ----------------

def test_gate_passes_when_f1_equals_threshold():
    # 恰好等于阈值 → 通过（1e-9 容差吸收浮点误差）
    assert check_gate(_fake_result(0.76), 76.0) is True


def test_gate_passes_when_f1_above_threshold():
    assert check_gate(_fake_result(0.78), 76.0) is True


def test_gate_blocks_when_f1_below_threshold():
    assert check_gate(_fake_result(0.70), 76.0) is False


def test_gate_skipped_when_fail_under_none():
    assert check_gate(_fake_result(0.0), None) is True


# ---------------- 端到端：子进程真实退出码 ----------------

def _run_eval_cli(*cli_args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"  # Windows 控制台缺省 gbk，报告含 emoji 需强制 utf-8
    return subprocess.run(
        [sys.executable, str(_PROJECT_ROOT / "evaluation" / "run_eval.py"), *cli_args],
        cwd=str(_PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=120,
    )


def test_cli_default_gate_passes_exit_zero():
    proc = _run_eval_cli()
    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    assert "[门禁通过]" in proc.stdout


def test_cli_fail_under_99_blocks_with_exit_one():
    """执行指令①验收：故意把阈值设 99（不可能达到），验证门禁真的会挡（退出码 1）。"""
    proc = _run_eval_cli("--fail-under", "99")
    assert proc.returncode == 1, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    assert "[门禁不通过]" in proc.stdout
