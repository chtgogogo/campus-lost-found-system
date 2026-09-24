"""应用配置（Pydantic Settings）。

集中管理数据库、Redis、JWT、YOLO 服务、打分权重/阈值、TTL、分区等全部可调参数。
配置来源优先级：环境变量 > 项目根 `.env` 文件 > 以下默认值。
"""
from __future__ import annotations

import logging
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
    # 安全铁律（安检 L1-1，2026-09-23）：默认值必须为空串 —— 弱默认密钥等于把家门钥匙挂在门上。
    # 应用启动时由 validate_security_config() fail fast 校验（非空 / 非 dev- 弱默认 / 非占位符），
    # 未配置直接 RuntimeError 拒绝启动。生成方式：python -c "import secrets;print(secrets.token_hex(32))"
    JWT_SECRET: str = ""
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
    HANDOVER_TTL_SEC: int = 10                 # 双码交叉验证模型 TTL（10 秒）

    # ---------------- 短信 ----------------
    SMS_RATE_LIMIT_PER_MIN: int = 5             # 每分钟上限
    SMS_RESEND_INTERVAL_SEC: int = 60           # 重发间隔

    # ---------------- API 限流（v13：固定窗口，见 core/ratelimit.py） ----------------
    # 唯一开关是 RATE_LIMIT_ENABLED（安检 L1-3，2026-09-23：DEBUG 连坐已拆除，
    # DEBUG=True 不再豁免限流；测试套件请显式设 RATE_LIMIT_ENABLED=false）
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_AUTH_PER_MIN: int = 10           # 登录/注册/发验证码（按 IP）
    # 安检 L2（卡#9，2026-09-23）：认证端点独立更严限流 —— key 加端点维度
    # （auth:login|register|send-sms:ip:<ip>），三端点各自独立桶，互不挤占。
    RATE_LIMIT_AUTH_STRICT_PER_MIN: int = 5     # 登录/注册/发短信逐端点配额（按 IP）
    RATE_LIMIT_PUBLISH_PER_MIN: int = 10        # 发布失物/拾物（按用户）
    RATE_LIMIT_PREVIEW_PER_MIN: int = 30        # 标签预览（按用户，轻量接口放宽）

    # ---------------- 安全开关拆分（安检 L1-3：一个开关只管一件事） ----------------
    # SHOW_SMS_CODE：send-sms 响应附带 dev_code（验证码直接显示，供"家人自助注册"演示）。
    # 默认 False；公网部署务必保持 False，否则验证码形同虚设。原耦合在 DEBUG 上，已解耦。
    SHOW_SMS_CODE: bool = False
    # SEED_DEMO：scripts/seed.py 是否播种演示账号/示例物品（demo_loser / demo_finder 等）。
    # 默认 False（不播种演示数据）；本机演示需要时在 .env 显式打开。
    SEED_DEMO: bool = False
    # 请求体大小护栏（安检 L1，2026-09-23）：超出直接 413，防恶意超大包打满内存。
    # 默认按上传能力上限取整：IMG_MAX_COUNT(9) × IMG_MAX_SIZE_MB(10) = 90MB + multipart 开销。
    REQUEST_BODY_MAX_MB: int = 100

    # ---------------- 匹配打分 · 阈值与展示口径 ----------------
    # 现行评分公式为下方「v10 评分引擎 v2 七子维度权重」（raw_total 合计 100 + Q10 归一化）；
    # 历史遗留的 flow-v2 五维权重（MATCH_W_PHOTO/CAT/TEXT/LOC/TIME/APP/FEAT/OTHER）、
    # v4 MATCH_W_TAG、v2 MATCH_W1..W4 已于卡#6（2026-09-23）整体下线：业务代码零引用，
    # 仅存 tests/test_match.py 的存续断言随字段一并删除。git 历史可查旧值。
    MATCH_THRESHOLD: float = 78.0   # 疑似匹配阈值：判定对象为**归一化后**的 total。
    # v17 评测 CI 门禁下限（evaluation/run_eval.py --fail-under 的缺省值）：
    # = 主集 F1 78.0 减 2pp 容差——门禁只挡「明显劣化」，给正常波动留余量；
    # 红线：盲集 dataset_blind.json 禁止挂进常规 CI（每 commit 都跑会被「跑熟」失效），
    # 仅打 tag 时人工跑并归档（CHANGELOG v17）。
    EVAL_FAIL_UNDER: float = 76.0
    # 80→78（2026-09-24 安检回归修复）：归一化分子口径对称后分数系统性下移约 4 分，
    # 阈值随分布重标定（主集 F1 回到 78.0；配合 MATCH_NEUTRAL_GAMMA=0.5，扫描数据见安检报告）。
    # flow-v3：低分「视觉」阈值。仅供前端（失主侧）弱化展示对齐口径 —— 弱化标签、虚线卡片、
    # 低分二次确认文案；与 suspected 判定（MATCH_THRESHOLD=78）完全解耦。
    # ⚠️ 后端业务代码不得引用本常量；此处定义的唯一目的是前后端常量单一事实源与可测性。
    MATCH_LOW_SCORE: float = 60.0
    # v10（变更 B）语义变更：**普通候选保底条数**，不再是硬上限。
    # ≥ MATCH_THRESHOLD 的疑似候选不受此限，可追加到 MATCH_SUSPECT_MAX 条（Q13：变量名不改）。
    MATCH_TOP_N: int = 50   # v15：候选展示扩容（配合「不是我的」排除池，前50条供用户扫选）
    TIME_DECAY_TAU_DAYS: float = 3.0    # legacy 兼容：仅 match_service.time_decay_factor（存量测试引用）使用；v2 评分用 MATCH_TIME_TAU_DAYS
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
    # 归一化中性分 γ（安检回归修复 2026-09-24）：失主提供了某维度、但候选侧完全没提
    # 该维度信息时，分子按 γ×该维度满分 计入（"对方没提到"≠"不符"，给部分信任）；
    # 候选侧提到了该维度则照实计分（提到但不符→低分/冲突罚照走，不虚高）。
    # γ=0 退回纯口径对称行为；扫描定值见 docs/pipeline/安检报告.md。
    MATCH_NEUTRAL_GAMMA: float = 0.5
    # v10（变更 B）疑似候选追加总量护栏：单次发布最多生成 max(MATCH_TOP_N, MATCH_SUSPECT_MAX) 条候选。
    MATCH_SUSPECT_MAX: int = 60   # v15: 随 TOP_N=50 扩容（疑似追加护栏须大于保底，否则撑破能力失效）

    # ---------------- v10 管理员 ----------------
    # 注册邀请码：命中则静默升为管理员（role=1）。安全铁律（安检 L1-2，2026-09-23）：
    # 默认值改空串 = 管理员邀请通道默认禁用（auth_service._resolve_role 的空串护栏会拒绝
    # 一切邀请码），启动时日志说明；实际值只从环境变量 / .env 注入，源码零字面量。
    ADMIN_APPLY_CODE: str = ""
    # 管理员留存窗（天）：物品 expires_at + 本值之后才进入 CleanupService 物理清理范围。
    ADMIN_RETENTION_DAYS: int = 270

    # v4/v2 旧权重（MATCH_W_TAG、MATCH_W1..W4）已于卡#6（2026-09-23）下线：
    # 业务代码零引用，仅 tests/test_match.py 的存续断言随字段一并删除；git 历史可查旧值。

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

# JWT 占位符黑名单：.env.example 里的示例值 / 历史弱默认，一律不得用于真实签名密钥
_JWT_FORBIDDEN = {
    "",
    "change-me",
    "changeme",
    "change-me-to-a-random-64hex",
    "change-me-to-a-strong-random-secret",
}


def validate_security_config() -> None:
    """启动安全校验（fail fast，安检 L1-1/L1-2，2026-09-23）。

    在 ``create_app()`` 最先调用，任何一项不过立即 ``RuntimeError`` 拒绝启动 ——
    宁可服务起不来，也不带着弱密钥上线。

    - ``JWT_SECRET``：必须非空、非 ``dev-`` 弱默认前缀、非占位符；
    - ``ADMIN_APPLY_CODE``：允许为空（= 管理员邀请通道禁用），但必须打日志说明，
      避免运维误以为配置了邀请码。
    """
    secret = (settings.JWT_SECRET or "").strip()
    if not secret:
        raise RuntimeError(
            "JWT_SECRET 未设置：拒绝启动。请在 .env 或环境变量配置随机密钥，"
            '生成方式：python -c "import secrets;print(secrets.token_hex(32))"'
        )
    if secret.lower().startswith("dev-"):
        raise RuntimeError("JWT_SECRET 为 dev- 弱默认值：拒绝启动，请更换为随机密钥")
    if secret in _JWT_FORBIDDEN:
        raise RuntimeError("JWT_SECRET 为占位符示例值：拒绝启动，请更换为随机密钥")
    if not (settings.ADMIN_APPLY_CODE or "").strip():
        logging.getLogger(__name__).warning(
            "ADMIN_APPLY_CODE 为空：管理员邀请通道已禁用（任何邀请码都不会命中）；"
            "如需启用请在 .env 配置强口令"
        )


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
