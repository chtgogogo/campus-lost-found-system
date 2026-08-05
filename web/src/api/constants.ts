// 常量：与后端 seed / 枚举 / 配置保持一致。
// 后端 app/core/seed.py 的种子分类与 app/schemas/common.py 的枚举。

/** API 基础路径（与 vite proxy 对应）。可被 .env 的 VITE_API_BASE 覆盖。 */
export const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'

/** 种子分类（app/core/seed.py）。自增 id 从 1 开始，顺序与种子一致。 */
export interface Category {
  id: number
  name: string
  recognition_mode: number // 0 COCO 1 YOLO-World
}

export const SEED_CATEGORIES: Category[] = [
  { id: 1, name: '手机', recognition_mode: 0 },
  { id: 2, name: '钱包', recognition_mode: 0 },
  { id: 3, name: '钥匙', recognition_mode: 0 },
  { id: 4, name: '书包', recognition_mode: 0 },
  { id: 5, name: '行李箱', recognition_mode: 0 },
  { id: 6, name: '笔记本电脑', recognition_mode: 0 },
  { id: 7, name: '校园卡', recognition_mode: 0 },
  { id: 8, name: '眼镜', recognition_mode: 0 },
  { id: 9, name: '笔记本', recognition_mode: 0 },
  { id: 10, name: '雨伞', recognition_mode: 0 },
  { id: 11, name: '水杯', recognition_mode: 0 },
  { id: 12, name: '其他', recognition_mode: 0 },
]

// ---------------- 枚举中文标签（对齐 app/schemas/common.py） ----------------
export const LOST_STATUS_LABEL: Record<number, string> = {
  0: '待匹配',
  1: '匹配中',
  2: '待认领',
  3: '已解决',
}

export const FOUND_STATUS_LABEL: Record<number, string> = {
  0: '待认领',
  1: '已解决',
}

export const MATCH_STATUS_LABEL: Record<number, string> = {
  0: '待认领',
  1: '认领中',
  2: '已完成',
  3: '已拒绝',
  4: '待自取', // v4：未挪动自取（单边，待自取完成）
  5: '已放弃', // v5：未能找回（软删匹配 + 失物重入匹配池）
  6: '已撤回', // v2：keep1 完成记录撤回后的终态（Q7 拍板）
}

/** IM 会话状态标签（v5：软删复用 status=1） */
export const IM_SESSION_STATUS_LABEL: Record<number, string> = {
  0: '进行中',
  1: '已关闭',
}

export const KEEP_STATUS_LABEL: Record<number, string> = {
  0: '暂为保管', // v4：拾得者已代为保管，强制开启联系
  1: '未挪动', // v4：物品原地未动，失主可自取 / 申请匹配
}

/** 「已完成交接」tab 状态徽标文案（v6：已解决项专属徽标，避免硬编码） */
export const RESOLVED_BADGE_LABEL = '已完成交接'

/** 审计操作类型中文映射（app/services/audit_service.py / common.AuditAction） */
export const AUDIT_ACTION_LABEL: Record<string, string> = {
  publish_lost: '发布失物',
  publish_found: '发布拾物',
  claim: '认领',
  confirm_return: '确认归还',
  reject: '拒绝认领',
  handover_generate: '生成交接码',
  handover_complete: '交接完成',
  handover_verify: '验证交接码',
  ban: '封禁',
  appeal: '申诉',
}

export function auditActionLabel(action: string): string {
  return AUDIT_ACTION_LABEL[action] || action
}

export function categoryName(id: number | null | undefined): string {
  if (id == null) return '未分类'
  return SEED_CATEGORIES.find((c) => c.id === id)?.name || '未分类'
}

/** v3 IM 轮询间隔（ms），对齐后端 IM_POLL_INTERVAL_MS（前端轮询而非 WebSocket） */
export const IM_POLL_INTERVAL_MS = 4000

// ---------------- 匹配（2026-08-05 增量：对齐后端 settings，前端低分判定 / 候选上限提示用） ----------------
/** 疑似匹配阈值（与后端 settings.MATCH_THRESHOLD 对齐）：仅用于 suspected 判定，与低分视觉口径无关 */
export const MATCH_THRESHOLD = 80

/** flow-v3：低分「视觉」阈值（与后端 settings.MATCH_LOW_SCORE 对齐）。
 *  仅失主侧弱化展示使用 —— 弱化标签 / 虚线卡片 / 低分二次确认文案；与 suspected(80) 完全解耦。 */
export const MATCH_LOW_SCORE = 60

/** 普通候选**保底条数**（与后端 settings.MATCH_TOP_N 对齐）。
 *  v10 变更 B：语义由「候选上限」改为「保底条数」—— ≥MATCH_THRESHOLD 的疑似不受此限，全部追加。 */
export const MATCH_TOP_N = 10

/** 疑似候选条数硬上限（与后端 settings.MATCH_SUSPECT_MAX 对齐），防极端数据下候选爆炸 */
export const MATCH_SUSPECT_MAX = 50

/** 演示态管理员邀请码（与后端 settings.ADMIN_APPLY_CODE 默认值对齐；生产环境必须改环境变量） */
export const MOCK_ADMIN_APPLY_CODE = '110'

// ---------------- flow-v2（2026-08-05）：[deprecated] 五维权重，v10 已下线，仅保留兼容引用 ----------------
/** [deprecated] flow-v2 五维权重：15·photo + 20·category + 50·text + 10·location + 5·time */
export const MATCH_WEIGHTS = { photo: 15, category: 20, text: 50, location: 10, time: 5 }

// ---------------- v10 评分引擎 v2：七子维度满分（与后端 settings.MATCH_W2_* 对齐） ----------------
/** 七子维度满分：分类 20 + 文字 70（量词 15 / 颜色 20 / 状态 10 / 地点 15 / 关键词 10）+ 时间 10 */
export const MATCH_WEIGHTS_V2 = {
  photo_category: 20,
  qty: 15,
  color: 20,
  state: 10,
  place: 15,
  keyword: 10,
  time: 10,
} as const

/** 文字大维度满分（= 五个文字子维度之和） */
export const MATCH_TEXT_MAX = 70

/** 子维度中文名（明细展示复用，避免各组件各写一份） */
export const MATCH_DIM_LABEL: Record<string, string> = {
  photo_category: '照片/分类',
  qty: '量词',
  color: '颜色',
  state: '状态',
  place: '地点',
  keyword: '关键词',
  time: '时间',
}

/** 冲突信号中文提示（score_detail.signals → 前端角标文案） */
export const MATCH_SIGNAL_LABEL: Record<string, string> = {
  color_conflict: '颜色不符，大概率非同一物品',
  state_conflict: '新旧/完好度描述矛盾',
}
