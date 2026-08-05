// 前端类型定义，严格对齐后端 Pydantic Schema 与统一响应体 {code, message, data}。

/** 后端统一成功响应包装 */
export interface ApiEnvelope<T> {
  code: number
  message: string
  data: T
}

/** 统一错误（HTTP 非 2xx 或业务 code != 0 时抛出） */
export class ApiError extends Error {
  code: number
  data: unknown
  constructor(code: number, message: string, data?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.data = data
  }
}

// ---------------- 用户 / 认证 ----------------
export interface UserOut {
  id: number
  student_no: string
  phone: string // 已脱敏
  real_name: string | null
  role: number // 0 普通 1 管理员
  credit_score: number
  status: number // 0 正常 1 封禁
  created_at: string
}

export interface Token {
  access_token: string
  refresh_token: string
  token_type?: string
  expires_in?: number
}

export interface LoginRequest {
  student_no: string
  password: string
}

export interface RegisterRequest {
  student_no: string
  phone: string
  sms_code: string
  password: string
  real_name?: string | null
  // v10（变更 C）：管理员邀请码（选填）。命中后端 ADMIN_APPLY_CODE 时静默升为 role=1。
  // ⚠️ 错码与不填的响应体完全一致，前端不得依据响应差异提示"邀请码错误"（AC-C9）。
  admin_code?: string | null
}

export interface SendSmsRequest {
  phone: string
  purpose: 'register' | 'bind' | 'login'
}

// ---------------- 物品 ----------------
export interface LostItemOut {
  id: number
  publisher_id: number
  category_id: number | null
  category_name: string
  title: string
  description: string
  images: string[]
  color: string | null
  // v3：结构化标签（视觉 label + 颜色词 + 地点词，保序去重）
  tags: string[]
  // v3：首图感知哈希（16-hex），用于照片相似度匹配
  image_hash: string | null
  // v8：新增结构化字段（外观 / 特征 / 地点），与后端 LostItem.appearance/features/location 对齐
  appearance: string | null
  features: string | null
  location: string | null
  // R3（2026-08-05）：非必填，空值显示"—"
  lost_time: string | null
  status: number // 0 待匹配 1 匹配中 2 待认领 3 已解决
  created_at: string
  expires_at?: string | null // v7：失效时间
  deleted_at?: string | null // v7：软删时间
}

export interface FoundItemOut {
  id: number
  finder_id: number
  category_id: number | null
  category_name: string
  description: string | null
  images: string[]
  // v3：结构化标签
  tags: string[]
  // v3：首图感知哈希（16-hex）
  image_hash: string | null
  // v8：新增结构化字段（外观 / 特征 / 地点），与后端 FoundItem.appearance/features/location 对齐
  appearance: string | null
  features: string | null
  location: string | null
  found_time: string | null
  keep_status: number // 0 已保管 1 待领取(未保管)
  contact_allowed: number
  status: number // 0 待认领 1 已解决
  created_at: string
  expires_at?: string | null // v7：失效时间
  deleted_at?: string | null // v7：软删时间
}

// ---------------- 匹配 ----------------
export interface MatchOut {
  id: number
  lost_id: number
  found_id: number
  match_score: number
  // 0 待认领 1 认领中 2 已完成 3 已拒绝
  // 4 待自取（v4：未挪动自取，单边匹配，由失主自取完成归档）
  // 5 已放弃（v5：未能找回，软删匹配 + 失物重入匹配池）
  // 6 已撤回（v2：keep1 完成记录撤回后的终态，Q7 拍板）
  status: number
  claim_reason: string | null
  created_at: string
  lost_item: LostItemOut | null
  found_item: FoundItemOut | null
  // 达到疑似阈值（score >= 80 = MATCH_THRESHOLD，语义不变）。
  // flow-v3：低分「弱化展示」由前端用 match_score < 60（MATCH_LOW_SCORE）独立派生，
  // 与 suspected 完全解耦 —— 60~79 分为 suspected=false 但**不再**弱化，仅 <60 弱化。
  suspected: boolean
  completed_at?: string | null // v7：完成时间
  shared_attributes?: string[] // 三重融合：失物/拾物 tags 交集（可解释展示）
  // v2（2026-08-05）：完成方式标记（0=双向交接 keep0 / 1=keep1 单边「申请即完成」），撤回动作唯一门控
  flow_type?: number
  // flow-v2：匹配维度明细（五维加权分值 + 总分，满分 100），与后端 MatchOut 对齐
  photo?: number | null // 图像相似度维度得分（权重 15）
  category?: number | null // 类别一致性维度得分（权重 20）
  appearance?: number | null // [deprecated] 旧六维，flow-v2 并入 text，新公式下为 0 或缺失，前端按 text 键回退
  feature?: number | null // [deprecated] 旧六维，flow-v2 并入 text，新公式下为 0 或缺失，前端按 text 键回退
  time?: number | null // 时间一致性维度得分（权重 5）
  location?: number | null // 地点一致性维度得分（权重 10）
  // flow-v2 新增：文字维度（R4）
  text?: number | null // 文字维度加权贡献（v10 起 = 文字五子维度之和，0–70）
  text_match_rate?: number | null // v10 语义变更：= text / 70（0–1）
  shared_text?: string[] // 失物侧被命中的词（可解释："共享文字"）
  total?: number | null // 总分（归一化后，满分 100）
  // ---- v10 评分引擎 v2 新增 10 个字段（全部可选，老数据不含时前端回退旧五维展示） ----
  // ⚠️ 七子维度返回的都是**归一化前的原始分**；只有 total / match_score 是归一化后的。
  photo_category?: number | null // 照片 / 系统分类一致性（0–20）
  qty?: number | null // 量词一致性（0–15）
  color?: number | null // 颜色合类一致性（0–20）
  state?: number | null // 状态 / 形容词（0–10）
  place?: number | null // 地点四级（0–15，= 旧键 location）
  keyword?: number | null // 其他关键词（0–10）
  signals?: string[] // color_conflict / state_conflict 子集
  raw_total?: number | null // 归一化前原始总分（0–100）
  norm_factor?: number | null // 归一化系数 k（≥1.0）
  provided_dims?: string[] // 失主实际填写的维度名（可解释 + 可测）
}

export interface ClaimRequest {
  claim_reason: string
  unique_proof?: string | null
}

export interface HandoverGenerate {
  code: string
  qr_token: string
  expire_at: string
}

export interface HandoverVerifyRequest {
  code: string
  role: 'lost' | 'finder'
  gps?: string | null
}

export interface HandoverVerifyResult {
  both_verified: boolean
  verified_by_lost: boolean
  verified_by_finder: boolean
}

// ---------------- P2-1：手动刷新候选（对齐 app/routers/match.py refresh_matches_for_lost） ----------------
export interface RefreshMatchesResult {
  /** 本次刷新新增的候选条数 */
  created: number
  /** 刷新后该失物的当前全部候选（score 降序，≤ MATCH_TOP_N 条，可能含低分） */
  matches: MatchOut[]
}

// ---------------- IM 即时通讯（v3 需求 D：联系对方） ----------------
export interface IMSessionCreate {
  match_id?: number // 既有匹配会话（二选一）
  found_id?: number // v4：无 match 的联系入口（绑定到具体拾物，强溯源）
}

export interface IMSessionOut {
  id: number
  match_id: number | null
  found_id: number | null // v4：无 match 联系会话绑定的拾物 id
  lost_user_id: number
  finder_user_id: number
  status: number // 0 开启 / 1 已关闭（软删，v5 复用）
  created_at: string
  last_message_at: string | null
  expires_at: string
}

// v5：「我的消息」会话列表项（富化，对应后端 IMSessionListItem）
export interface PeerUser {
  id: number
  nickname: string // real_name 或「用户{id}」
  student_no: string
}

export interface IMSessionListItem {
  id: number
  match_id: number | null
  found_id: number | null
  lost_user_id: number
  finder_user_id: number
  peer_user: PeerUser
  title: string // 后端拼好的「联系对方 · {物品标题}」
  last_message_at: string | null
  last_message_preview: string | null
  unread: boolean // 粗粒度：最后消息来自对方
  status: number
}

export interface IMMessageCreate {
  type?: 'text' | 'template'
  content: string
}

export interface IMMessageOut {
  id: number
  session_id: number
  sender_id: number
  sender_role: number // 0 失主 / 1 拾得者
  content_type: number // 0 文字 / 1 模板
  content: string
  sent_at: string
}

// ---------------- 视觉预识别（对齐 app/routers/vision.py） ----------------
export interface VisionCategory {
  id: number
  name: string
}

export interface VisionPredictResult {
  category_id: number
  label: string
  confidence: number // [0,1]
  categories: VisionCategory[]
}

// ---------------- 分页 ----------------
export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

// ---------------- v10 变更 D：管理后台 ----------------
/**
 * 管理后台用户（对齐 app/schemas/user.py::AdminUserOut）。
 *
 * ⚠️ 与 `UserOut` 的唯一实质差异：`phone` 为**明文**（取证需要）。
 * 展示该字段的界面必须同时展示合规提示。
 */
export interface AdminUserOut {
  id: number
  student_no: string
  phone: string // 明文，未脱敏
  real_name: string | null
  role: number // 0 普通 1 管理员
  credit_score: number
  status: number // 0 正常 1 封禁
  created_at: string
}

/** 匹配详情中的单条 IM 消息（对齐 AdminConversationItem）。 */
export interface AdminConversationItem {
  sent_at: string | null
  sender_role: number // 0 失主 1 拾得者
  role_label: string // 后端已给中文角色名，前端不再映射
  content: string
}

/** `GET /admin/matches/{id}/detail` 响应体（对齐 AdminMatchDetailOut）。 */
export interface AdminMatchDetailOut {
  match: MatchOut
  lost_user: AdminUserOut | null
  found_user: AdminUserOut | null
  conversation: AdminConversationItem[]
}

/** 导出范围 / 格式枚举（与后端 `_VALID_SCOPES` / `_VALID_FORMATS` 一致）。 */
export type ExportScope = 'profile' | 'conversation' | 'all'
export type ExportFormat = 'csv' | 'xlsx' | 'md'

// ---------------- 管理后台审计日志（后端暂未暴露接口，前端约定结构） ----------------
export interface AuditLog {
  id: number
  user_id: number | null
  action: string
  target_type: string | null
  target_id: number | null
  ip: string | null
  ua: string | null
  gps: string | null
  detail: string | null
  created_at: string
}
