"""locust 压测场景（v17 任务②）。四场景单选，由环境变量 LOADTEST_SCENARIO 控制。

场景与被测接口（单机校园规模，诚实口径）：

=================  ==============================================  ==========================
场景名             请求                                            说明
=================  ==============================================  ==========================
list               GET  /api/v1/lost-items?page_size=20            物品列表（公示栏主 tab）
publish            POST /api/v1/found-items（1 张 64px PNG）        发布，**含同步 YOLO 识别**
matches            GET  /api/v1/matches?page_size=20               匹配列表（2000 条候选池）
handover           POST /api/v1/matches/{id}/handover/verify       交接码验证，**错码路径**
mixed              以上混合（读:发布:交接 = 6:2:2 权重）             真实"边浏览边发布"读写并发
=================  ==============================================  ==========================

约定：
- 压测时服务端以 RATE_LIMIT_ENABLED=false 启动（测应用本身而非限流器），README 声明。
- handover 为错码路径：业务 4xx 信封（码错/锁定）视为**预期成功**（catch_response 标记），
  仅 5xx/网络错误计失败——错码路径含「码行行锁查询 + 恒时比较 + attempts 写提交」，
  与真实验证的读写配比一致；正确码路径一次性流转不可重复压测。
- 发布场景每次上传同一 64px PNG：YOLO 对小图按 640 输入推理，CPU 耗时与真实场景同量级。
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path

from locust import HttpUser, between, task

_MANIFEST = json.loads(
    (Path(__file__).resolve().parent / "_env" / "seed_manifest.json").read_text(encoding="utf-8")
)
_SCENARIO = os.environ.get("LOADTEST_SCENARIO", "list")

# 64px 纯色 PNG（导入时生成一次）：validate_images 过魔数，YOLO 走真实 640 输入推理
try:
    from PIL import Image

    _buf = io.BytesIO()
    Image.new("RGB", (64, 64), (180, 154, 66)).save(_buf, format="PNG")
    _PNG = _buf.getvalue()
except Exception:  # pragma: no cover - 无 Pillow 时用最小合法 PNG 兜底
    import base64

    _PNG = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
        "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    )


class LoadTestUser(HttpUser):
    """四场景单选压测用户（LOADTEST_SCENARIO: list | publish | matches | handover）。"""

    wait_time = between(0.0, 0.05)
    _handover_idx = 0

    def on_start(self) -> None:
        student_no = (
            _MANIFEST["student_no_hand"]
            if _SCENARIO == "handover"
            else _MANIFEST["student_no_list"]
        )
        with self.client.post(
            "/api/v1/auth/login",
            json={"student_no": student_no, "password": _MANIFEST["password"]},
            name="POST /auth/login（一次性）",
            catch_response=True,
        ) as r:
            if r.status_code != 200:
                r.failure(f"login failed: {r.status_code}")
                return
            token = r.json()["data"]["access_token"]
        self.client.headers["Authorization"] = f"Bearer {token}"

    # ---------------- 场景 1：物品列表 ----------------
    @task(4 if _SCENARIO == "mixed" else 1)
    def list_items(self) -> None:
        if _SCENARIO not in ("list", "mixed"):
            return
        self.client.get(
            "/api/v1/lost-items",
            params={"page": 1, "page_size": 20},
            name="GET /lost-items",
        )

    # ---------------- 场景 2：发布（含同步 YOLO 识别） ----------------
    @task(2 if _SCENARIO == "mixed" else 1)
    def publish_found(self) -> None:
        if _SCENARIO not in ("publish", "mixed"):
            return
        self.client.post(
            "/api/v1/found-items",
            files=[("images", ("loadtest.png", _PNG, "image/png"))],
            data={
                "keep_status": "1",
                "category_name": "书包",
                "description": f"压测发布-{os.urandom(4).hex()}",
            },
            name="POST /found-items（含同步识别）",
        )

    # ---------------- 场景 3：匹配列表 ----------------
    @task(2 if _SCENARIO == "mixed" else 1)
    def match_list(self) -> None:
        if _SCENARIO not in ("matches", "mixed"):
            return
        self.client.get(
            "/api/v1/matches",
            params={"page": 1, "page_size": 20},
            name="GET /matches",
        )

    # ---------------- 场景 4：交接码验证（错码路径） ----------------
    @task(2 if _SCENARIO == "mixed" else 1)
    def handover_verify(self) -> None:
        if _SCENARIO not in ("handover", "mixed"):
            return
        ids = _MANIFEST["hand_match_ids"]
        LoadTestUser._handover_idx = (LoadTestUser._handover_idx + 1) % len(ids)
        match_id = ids[LoadTestUser._handover_idx]
        with self.client.post(
            f"/api/v1/matches/{match_id}/handover/verify",
            json={"code": "0000", "role": "lost"},
            name="POST /handover/verify（错码路径）",
            catch_response=True,
        ) as r:
            # 错码路径的业务 4xx（码错/锁定）= 预期响应；仅 5xx/异常计失败
            if r.status_code == 200:
                r.success()
            elif 400 <= r.status_code < 500:
                r.success()
            else:
                r.failure(f"unexpected {r.status_code}")
