"""v17④ 识别链路异步化测试。

覆盖执行指令④验收矩阵：
1. 发布响应含「识别中」状态，worker 处理后置完成（recognize_status 0→2）；
2. **同哈希重复提交只识别一次**（幂等）：同 PNG 两次发布 → 主任务 + 子任务，predict 恰好 1 次；
3. **重试上限触发死信**：predict 连续抛异常 → retry_count 达 3 → failed + error 可查 + 物品置失败；
4. **并发消费不重复执行**：claim_next 原子领取，第二次领取拿不到；
5. **worker 崩溃后任务可恢复**：遗留 running 任务由 recover_stale_running 复位并成功执行；
6. **CLIP 迁移**：候选精排从 BackgroundTasks 迁入任务表，worker 消费时按 payload 调 reorder。

测试环境 worker 线程已关（conftest RECOGNITION_WORKER_ENABLED=false），
用 drain_recognition()（同步清队列）与 claim_next/process_task 直接驱动。
"""
from __future__ import annotations

import threading

from app.models.item import FoundItem, LostItem
from app.models.match import MatchRecord
from app.models.recognition import RecognitionTask
from app.models.correction import CorrectionSample
from app.schemas.common import RecognitionStatus
from app.services import recognition_worker
from conftest import PNG, auth_header, drain_recognition, register_and_login


def _publish_found(client, token: str, description: str = "捡到黑色书包", category: str = "书包"):
    r = client.post(
        "/api/v1/found-items",
        headers=auth_header(token),
        data={"keep_status": "1", "description": description, "category_name": category},
        files={"images": ("found.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _category_id_by_name(db, name: str) -> int:
    from app.models.category import Category

    cat = db.query(Category).filter(Category.name == name, Category.is_active == 1).first()
    assert cat is not None, f"种子类目缺失: {name}"
    return int(cat.id)


def _fake_vision(recorder: dict, category_id: int | None = None, label: str = "书包", confidence: float = 0.9):
    """可计数 fake 视觉服务：predict 计数进 recorder["n"]，可切换为抛异常。"""
    from app.core.database import SessionLocal

    class _FakeVision:
        def predict(self, image_bytes: bytes) -> dict:
            recorder["n"] = recorder.get("n", 0) + 1
            if recorder.get("raise"):
                raise RuntimeError("YOLO 炸了")
            cid = category_id if category_id is not None else _category_id_by_name(SessionLocal(), "书包")
            return {"category_id": cid, "label": label, "confidence": confidence}

    return _FakeVision()


# ---------------- 1. 发布响应含识别中状态 ----------------

def test_publish_returns_pending_then_done(client, db, monkeypatch):
    recorder: dict = {}
    monkeypatch.setattr(
        recognition_worker, "get_vision_service", lambda: _fake_vision(recorder)
    )
    token, _, _, _, _ = register_and_login(client, "ra")
    data = _publish_found(client, token)
    item_id = data["item"]["id"]
    # 发布即返回「识别中」；任务行 pending
    assert data["item"]["recognize_status"] == int(RecognitionStatus.PENDING)
    task = (
        db.query(RecognitionTask)
        .filter(RecognitionTask.task_type == "yolo", RecognitionTask.item_id == item_id)
        .first()
    )
    assert task is not None and task.status == int(RecognitionStatus.PENDING)

    processed = drain_recognition()
    assert processed >= 1
    db.expire_all()
    item = db.get(FoundItem, item_id)
    assert item.recognize_status == int(RecognitionStatus.DONE)
    task = db.get(RecognitionTask, task.id)
    assert task.status == int(RecognitionStatus.DONE)


# ---------------- 2. 同哈希重复提交只识别一次（幂等） ----------------

def test_same_image_hash_recognized_once(client, db, monkeypatch):
    recorder: dict = {}
    monkeypatch.setattr(
        recognition_worker, "get_vision_service", lambda: _fake_vision(recorder)
    )
    token_a, _, _, _, _ = register_and_login(client, "ha")
    token_b, _, _, _, _ = register_and_login(client, "hb")
    # 两个用户上传**同一份 PNG 字节**（conftest.PNG 同一常量）→ 同 file_hash
    data_a = _publish_found(client, token_a, "A 捡到书包")
    data_b = _publish_found(client, token_b, "B 捡到书包")

    tasks = (
        db.query(RecognitionTask)
        .filter(RecognitionTask.task_type == "yolo")
        .order_by(RecognitionTask.id)
        .all()
    )
    assert len(tasks) == 2, "两次发布各有一条任务"
    parents = [t for t in tasks if t.parent_id is None]
    children = [t for t in tasks if t.parent_id is not None]
    assert len(parents) == 1 and len(children) == 1, "同哈希只能有一个主任务，其余挂子任务"
    assert children[0].parent_id == parents[0].id

    drain_recognition()
    assert recorder.get("n", 0) == 1, "同哈希两份提交，YOLO 只允许推理一次"
    db.expire_all()
    for item_id in (data_a["item"]["id"], data_b["item"]["id"]):
        item = db.get(FoundItem, item_id)
        assert item.recognize_status == int(RecognitionStatus.DONE)
        assert item.category_id == _category_id_by_name(db, "书包"), "子任务复制结果后同样完成类目回填"


def test_same_hash_after_primary_done_applies_immediately(client, db, monkeypatch):
    """主任务完成后，同图新发布的缓存复用路径必须**同步回填**物品状态。

    回归用例（压测 sqlite_async 实证）：原实现里该路径只复制任务结果、不应用物品，
    导致任务行 done 而物品永远停在「识别中」。修复后：发布响应即 DONE，无需 worker。
    """
    recorder: dict = {}
    monkeypatch.setattr(
        recognition_worker, "get_vision_service", lambda: _fake_vision(recorder)
    )
    token_a, _, _, _, _ = register_and_login(client, "ia")
    token_b, _, _, _, _ = register_and_login(client, "ib")
    _publish_found(client, token_a, "先发布")  # 主任务
    drain_recognition()  # 主任务完成（predict 1 次）
    assert recorder.get("n", 0) == 1

    data_b = _publish_found(client, token_b, "后发布同图")
    item_b_id = data_b["item"]["id"]
    # 发布响应立即 DONE（缓存复用），不再依赖 worker
    assert data_b["item"]["recognize_status"] == int(RecognitionStatus.DONE)
    assert recorder.get("n", 0) == 1, "缓存复用不得再次推理"
    db.expire_all()
    item_b = db.get(FoundItem, item_b_id)
    assert item_b.recognize_status == int(RecognitionStatus.DONE)
    assert item_b.category_id == _category_id_by_name(db, "书包"), "缓存结果同步回填类目"


# ---------------- 3. 重试上限触发死信 ----------------

def test_retry_exhaustion_dead_letter(client, db, monkeypatch):
    recorder: dict = {"raise": True}
    monkeypatch.setattr(
        recognition_worker, "get_vision_service", lambda: _fake_vision(recorder)
    )
    token, _, _, _, _ = register_and_login(client, "dl")
    data = _publish_found(client, token)
    item_id = data["item"]["id"]

    processed = drain_recognition()
    assert processed == 3, "重试上限 3：三次处理后进入死信"
    task = (
        db.query(RecognitionTask)
        .filter(RecognitionTask.task_type == "yolo", RecognitionTask.item_id == item_id)
        .first()
    )
    assert task.status == int(RecognitionStatus.FAILED)
    assert task.retry_count == 3
    assert "YOLO 炸了" in (task.error or ""), "死信 error 可查"
    db.expire_all()
    assert db.get(FoundItem, item_id).recognize_status == int(RecognitionStatus.FAILED)


# ---------------- 4. 并发消费不重复执行 ----------------

def test_concurrent_claim_executes_once(db, monkeypatch):
    from app.core.database import SessionLocal

    recorder: dict = {}
    monkeypatch.setattr(
        recognition_worker, "get_vision_service", lambda: _fake_vision(recorder)
    )
    from app.models.recognition import utcnow

    db.add(
        FoundItem(
            description="并发测试拾物",
            category_name="书包",
            finder_id=1,
            images=[],
            keep_status=1,
            status=0,
            recognize_status=int(RecognitionStatus.PENDING),
        )
    )
    db.flush()
    item_id = db.query(FoundItem).order_by(FoundItem.id.desc()).first().id
    task = RecognitionTask(
        task_type="yolo",
        status=int(RecognitionStatus.PENDING),
        file_hash="concurrent-test-hash",
        item_type="found",
        item_id=item_id,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(task)
    db.commit()
    task_id = task.id

    # 两个「worker」并发领取：只有一个拿到，另一个拿不到 → 任务不会被消费两次
    got: list = []

    def _claim():
        s = SessionLocal()
        try:
            t = recognition_worker.claim_next(s)
            got.append(t.id if t else None)
        finally:
            s.close()

    threads = [threading.Thread(target=_claim) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert sorted(got, key=lambda v: (v is None, v)) == [task_id, None], (
        f"并发领取应恰好一次成功一次落空，实际 {got}"
    )
    # 领到的一方处理 → predict 恰好一次
    s = SessionLocal()
    try:
        recognition_worker.process_task(s, task_id)
    finally:
        s.close()
    assert recorder.get("n", 0) == 1


# ---------------- 5. worker 崩溃后任务可恢复 ----------------

def test_crash_recovery_resumes_running_task(db, monkeypatch):
    from app.core.database import SessionLocal

    recorder: dict = {}
    monkeypatch.setattr(
        recognition_worker, "get_vision_service", lambda: _fake_vision(recorder)
    )
    db.add(
        FoundItem(
            description="崩溃恢复拾物",
            category_name="书包",
            finder_id=1,
            images=[],
            keep_status=1,
            status=0,
            recognize_status=int(RecognitionStatus.PENDING),
        )
    )
    db.flush()
    item_id = db.query(FoundItem).order_by(FoundItem.id.desc()).first().id
    from app.models.recognition import utcnow

    task = RecognitionTask(
        task_type="yolo",
        status=int(RecognitionStatus.RUNNING),  # 模拟崩溃时遗留的 running
        file_hash="crash-test-hash",
        item_type="found",
        item_id=item_id,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(task)
    db.commit()
    task_id = task.id

    s = SessionLocal()
    try:
        assert recognition_worker.recover_stale_running(s) >= 1, "遗留 running 应被复位"
        db.expire_all()
        assert db.get(RecognitionTask, task_id).status == int(RecognitionStatus.PENDING)
        # 复位后正常消费完成
        t = recognition_worker.claim_next(s)
        assert t is not None and t.id == task_id
        recognition_worker.process_task(s, task_id)
        db.expire_all()
        assert db.get(RecognitionTask, task_id).status == int(RecognitionStatus.DONE)
        assert db.get(FoundItem, item_id).recognize_status == int(RecognitionStatus.DONE)
    finally:
        s.close()


# ---------------- 6. CLIP 精排迁入任务表 ----------------

def test_clip_reorder_migrated_to_task_table(client, db, monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(
        recognition_worker, "reorder_match_ids", lambda ids: seen.update(ids=list(ids))
    )
    token_a, token_b, lost_id, _match_id = _publish_pair(client)
    clip_tasks = (
        db.query(RecognitionTask).filter(RecognitionTask.task_type == "clip").all()
    )
    assert len(clip_tasks) == 1, "拾物发布生成候选后应恰好入队一条 CLIP 任务"
    assert clip_tasks[0].status == int(RecognitionStatus.PENDING)

    drain_recognition()
    db.expire_all()
    task = db.get(RecognitionTask, clip_tasks[0].id)
    assert task.status == int(RecognitionStatus.DONE)
    expected = [m.id for m in db.query(MatchRecord).filter(MatchRecord.lost_id == lost_id).all()]
    assert sorted(seen.get("ids", [])) == sorted(expected), "worker 按 payload.match_ids 调精排"


def _publish_pair(client):
    """失主 A + 拾得者 B（keep0，触发反向匹配）→ (token_a, token_b, lost_id, match_id)。"""
    from datetime import datetime

    token_a, _, _, _, _ = register_and_login(client, "ca")
    token_b, _, _, _, _ = register_and_login(client, "cb")
    r = client.post(
        "/api/v1/lost-items",
        headers=auth_header(token_a),
        data={
            "title": "黑色书包",
            "description": "图书馆丢失黑色书包",
            "category_name": "书包",
            "lost_time": datetime(2026, 7, 16, 10, 0, 0).isoformat(),
        },
        files={"images": ("lost.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    lost_id = r.json()["data"]["item"]["id"]
    r = client.post(
        "/api/v1/found-items",
        headers=auth_header(token_b),
        data={
            "keep_status": "0",
            "description": "捡到黑色书包看起来像图书馆丢的",
            "category_name": "书包",
        },
        files={"images": ("found.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    matches = r.json()["data"]["suspected_matches"]
    assert matches, "拾物发布应触发反向匹配"
    return token_a, token_b, lost_id, matches[0]["id"]


# ---------------- 7. 识别完成后类目/标签回填与纠错样本 ----------------

def test_worker_refines_category_tags_and_correction(client, db, monkeypatch):
    bag_id = _category_id_by_name(db, "书包")
    recorder: dict = {}
    monkeypatch.setattr(
        recognition_worker,
        "get_vision_service",
        lambda: _fake_vision(recorder, category_id=bag_id, label="书包", confidence=0.9),
    )
    token, _, _, _, user_id = register_and_login(client, "rf")
    # 类目名不命中种子类目 → 发布时降级「其他」；识别完成后视觉类目接管
    data = _publish_found(client, token, "捡到一个奇怪物件", category="神秘物件")
    item_id = data["item"]["id"]
    db.expire_all()
    other_id = _category_id_by_name(db, "其他")
    assert db.get(FoundItem, item_id).category_id == other_id, "发布时按视觉不可用降级「其他」"

    drain_recognition()
    db.expire_all()
    item = db.get(FoundItem, item_id)
    assert item.category_id == bag_id, "识别完成后视觉类目接管"
    assert "书包" in (item.tags or []), "真实 vision_label 注入 tags"
    sample = (
        db.query(CorrectionSample)
        .filter(CorrectionSample.item_type == "found", CorrectionSample.item_id == item_id)
        .first()
    )
    assert sample is not None and sample.final_category_name == "神秘物件", "数据飞轮照常记录纠错样本"
