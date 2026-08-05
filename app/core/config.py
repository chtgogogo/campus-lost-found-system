"""应用配置（Pydantic Settings）。

集中管理数据库、Redis、JWT、YOLO 服务、打分权重/阈值、TTL、分区等全部可调参数。
配置来源优先级：环境变量 > 项目根 `.env` 文件 > 以下默认值。
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import TYPE_CHECKING

from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from app.core.redis_client import RedisClient

# 项目根目录（本文件位于 app/core/config.py，故上溯两级）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Settings(BaseSettings):
    """全局配置。

    所有字段均可通过环境变量或 `.env` 覆盖（见 §5.6）。
    """

    model_config = SettingsConfigDict(
        env_file=os.path.join(BASE_DIR, ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------------- 基础 ----------------
    APP_NAME: str = "Campus Lost & Found API"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = True

    # ---------------- 数据库 ----------------
    # dev 默认 SQLite（位于项目根，E 盘）；生产切换 MySQL
    DATABASE_URL: str = "sqlite:///./dev.db"
    DB_ECHO: bool = False

    # ---------------- Redis / 内存兜底 ----------------
    # MVP 阶段 Redis 可选；不可用时自动降级为进程内内存存储（单进程开发足够）
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_ENABLED: bool = False  # 显式关闭则直接用内存兜底，避免无 Redis 报错

    # ---------------- JWT ----------------
    JWT_SECRET: str = "dev-secret-change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MIN: int = 120          # access token 120 分钟
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7          # refresh token 7 天

    # ---------------- 视觉识别（进程内 VisionService） ----------------
    # MVP 桩不加载模型；T-DEP 按以下配置加载真实 YOLOv8n + YOLO-World 权重。
    YOLO_DEVICE: str = "cpu"                              # 推理设备 cpu / cuda:0
    YOLO_MODEL_DIR: str = os.path.join(BASE_DIR, "models", "weights")  # 权重目录（项目内，严禁 C 盘）
    # YOLO 不可用时降级使用的默认分类 id（需在 seed 中存在；0 表示仅人工类）
    YOLO_FALLBACK_CATEGORY_ID: int = 0
    # 权重文件名（落 YOLO_MODEL_DIR）
    YOLO_COCO_MODEL: str = "best.pt"           # 用户训练 11 类校园失物模型（替代通用 COCO）
    YOLO_WORLD_MODEL: str = "yolov8s-world.pt" # YOLO-World 零样本模型
    # 检测置信度阈值（低于此值的检测框被忽略）
    YOLO_CONF_THRESHOLD: float = 0.12  # 降低门槛以提升弱类（钥匙/钱包/水杯）召回，代价是偶发误识别

    # ---------------- 交接码 ----------------
    HANDOVER_TTL_MIN: int = 30                  # 交接码 30 分钟有效

    # ---------------- 短信 ----------------
    SMS_RATE_LIMIT_PER_MIN: int = 5             # 每分钟上限
    SMS_RESEND_INTERVAL_SEC: int = 60           # 重发间隔

    # ---------------- 匹配打分（2026-08-05 flow-v2 新公式，Q5 拍板） ----------------
    # 普通类五维公式（合计 100，阈值沿用 80）：
    #   score = 15·photo + 20·category + 50·text + 10·location + 5·time
    # text 为动态文字词覆盖率（失物侧词集 containment，description 首次进打分，见 match_service.text_match_rate）。
    # 「其他」类（category_name == OTHER_CATEGORY_NAME）特殊路径：
    #   score = 20·photo + 80·tag_match_rate   （类目权重外移，tag_match_rate 与 text_match_rate 同口径）
    # 空值规则（Q6）：location / time 任一缺失 → 中性 0.5；text 失物侧空词集 → 0.5；photo 无图 → 0.0。
    # ⚠️ v10 起以下五个 MATCH_W_* 全部 [deprecated]：评分主路径改用下方 v2 七子维度权重
    #    （MATCH_W2_*）。保留定义仅为不破坏外部引用与存量测试，score/score_detail 不再调用。
    MATCH_W_PHOTO: float = 15.0   # [deprecated] 照片相似度（感知哈希 Hamming → 相似度）
    MATCH_W_CAT: float = 20.0     # [deprecated] 类目命中（精确 1.0 / 父级 0.5）
    MATCH_W_TEXT: float = 50.0    # [deprecated] 文字动态词覆盖率（失物侧词集 containment）
    MATCH_W_LOC: float = 10.0     # [deprecated] 地点相似度（包含 + 编辑距离阈值双判）
    MATCH_W_TIME: float = 5.0     # [deprecated] 时间衰减（任一缺失 → 0.5）
    MATCH_W_APP: float = 20.0     # [deprecated] 外观权重：flow-v2 起并入 text 词集，不再被 score 调用
    MATCH_W_FEAT: float = 15.0    # [deprecated] 特征权重：flow-v2 起并入 text 词集，不再被 score 调用
    MATCH_W_OTHER: float = 80.0   # [deprecated] 「其他」类特殊路径权重；v10 Q7 起「其他」统一走 v2 公式
    MATCH_THRESHOLD: float = 80.0   # 疑似匹配阈值：判定对象为**归一化后**的 total（v10 维持 80 不变）
    # flow-v3：低分「视觉」阈值。仅供前端（失主侧）弱化展示对齐口径 —— 弱化标签、虚线卡片、
    # 低分二次确认文案；与 suspected 判定（MATCH_THRESHOLD=80）完全解耦。
    # ⚠️ 后端业务代码不得引用本常量；此处定义的唯一目的是前后端常量单一事实源与可测性。
    MATCH_LOW_SCORE: float = 60.0
    # v10（变更 B）语义变更：**普通候选保底条数**，不再是硬上限。
    # ≥ MATCH_THRESHOLD 的疑似候选不受此限，可追加到 MATCH_SUSPECT_MAX 条（Q13：变量名不改）。
    MATCH_TOP_N: int = 10
    TIME_DECAY_TAU_DAYS: float = 3.0    # [deprecated for v2] flow-v2 时间衰减 τ（天）；v2 改用 MATCH_TIME_TAU_DAYS
    # 「其他」类枚举名（运行时按名称解析，避免硬编码 id 耦合；seed 中以同名行存在）
    OTHER_CATEGORY_NAME: str = "其他"

    # ---------------- v10 评分引擎 v2 七子维度权重（PRD §A.3，R2 §2.1） ----------------
    # raw_total = photo_category(20) + [qty(15)+color(20)+state(10)+place(15)+keyword(10) = 文字 70] + time(10)
    # 合计 100；各档位分值（量词五档 / 颜色三档 / 地点四级）见 app/services/scoring_refs.py 与
    # app/services/color_family.py（单一事实源，禁止在打分函数里写魔法数字）。
    MATCH_W2_PHOTO_CAT: float = 20.0   # 照片/系统分类一致性（同 20 / 近似 10 / 不同 0 / 缺失或双方「其他」10）
    MATCH_W2_QTY: float = 15.0         # 文字·量词一致性
    MATCH_W2_COLOR: float = 20.0       # 文字·颜色合类一致性
    MATCH_W2_STATE: float = 10.0       # 文字·状态/形容词
    MATCH_W2_PLACE: float = 15.0       # 文字·地点四级命中（已并入文字 70，不再独立维度）
    MATCH_W2_KEYWORD: float = 10.0     # 文字·其他关键词（品牌/材质/图案/型号）
    MATCH_W2_TIME: float = 10.0        # 时间衰减
    # v2 时间衰减 τ（天）：time = 10·exp(-Δdays/τ)。**不复用** TIME_DECAY_TAU_DAYS=3.0，避免影响其它引用点。
    MATCH_TIME_TAU_DAYS: float = 15.0

    # ---------------- v10 归一化（Q10 用户拍板，P0 主路径） ----------------
    # k = 100 / max(W_provided, MATCH_NORM_MIN_WEIGHT)；total = clamp(raw_total · k, 0, 100)
    # 铁律：W_provided **只由失主侧决定**（候选侧永不进分母），否则同一失物的候选不可比、排序失真。
    MATCH_NORMALIZE: bool = True          # kill switch：False 时 k≡1.0，退回纯 raw 分（可回滚/AB）
    MATCH_NORM_MIN_WEIGHT: float = 50.0   # 防爆下限：仅填类目的纯图失物封顶 40 分，避免满分误报
    # v10（变更 B）疑似候选追加总量护栏：单次发布最多生成 max(MATCH_TOP_N, MATCH_SUSPECT_MAX) 条候选。
    MATCH_SUSPECT_MAX: int = 50

    # ---------------- v10 管理员 ----------------
    # 注册邀请码：命中则静默升为管理员（role=1）；生产必须通过环境变量 ADMIN_APPLY_CODE 改为强口令。
    # ⚠️ 配成空串时 auth_service 的 bool(expected) 护栏会使任何邀请码都不命中（防全员管理员越权）。
    ADMIN_APPLY_CODE: str = "110"
    # 管理员留存窗（天）：物品 expires_at + 本值之后才进入 CleanupService 物理清理范围。
    ADMIN_RETENTION_DAYS: int = 270

    # v4 旧标签命中率权重（保留并标 deprecated：不再被 score 调用，避免外部引用断裂）
    MATCH_W_TAG: float = 40.0     # [deprecated] v4 containment 权重，v8 已拆分为 appearance/feature/location

    # v2 旧权重（Q3 拍板：保留并标 deprecated，避免外部引用断裂；新代码改用上方 W_PHOTO/W_CAT/W_TEXT/W_LOC/W_TIME）
    MATCH_W1: float = 40.0    # [deprecated] 原类目命中权重
    MATCH_W2: float = 25.0    # [deprecated] 原时间衰减权重
    MATCH_W3: float = 20.0    # [deprecated] 原地点文本相似度权重（v3 已移除地点因子）
    MATCH_W4: float = 15.0    # [deprecated] 原关键词 Jaccard 权重（v3 由 W_TAG 标签 Jaccard 取代）

    # ---------------- 图片 / 存储 ----------------
    IMG_MAX_COUNT: int = 9
    IMG_MAX_SIZE_MB: int = 10
    IMG_STORAGE: str = "local"                  # local | minio | oss
    UPLOAD_DIR: str = os.path.join(BASE_DIR, "uploads")   # 本地上传根目录（项目内）

    # ---------------- 保留期 ----------------
    IM_RETENTION_DAYS: int = 30   # IM 会话/消息留存天数（v3 Q7：7 → 30，超期仅清理 im_session/im_message，审计长期留存）
    AUDIT_RETENTION_DAYS: int = 365

    # ---------------- 实时通信 ----------------
    IM_POLL_INTERVAL_MS: int = 4000   # 前端轮询会话消息间隔（v3 Q6：4s，非 WebSocket）

    # ---------------- 分页 ----------------
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100


@lru_cache
def get_settings() -> Settings:
    """返回全局配置单例。"""
    return Settings()


settings = get_settings()


def get_redis() -> "RedisClient":
    """返回 KV 存储客户端（Redis 优先，内存兜底）。

    统一访问入口，调用方无需关心底层实现：
    - ``REDIS_ENABLED=True`` 且 redis 服务可达 → 真实 Redis 客户端；
    - 否则（禁用 / 未安装 / 连接失败）→ 进程内内存兜底对象。

    两者均暴露 ``get`` / ``set`` / ``expires`` 接口，供活跃存储（如交接码缓存）使用。

    采用惰性导入 ``app.core.redis_client``，避免与 ``config`` 形成循环依赖，
    也保证无 redis 依赖时模块仍可正常导入。
    """
    from app.core.redis_client import kv

    return kv
