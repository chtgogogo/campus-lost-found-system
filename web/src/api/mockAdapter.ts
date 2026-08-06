// 演示模式适配器（axios adapter）：当“演示数据”开关开启时，
// 拦截所有请求并返回与后端 Schema 完全一致的本地静态数据，
// 使得前端在无后端运行时也能完整渲染每一个页面（用于论文截图/演示）。
//
// 同时维护一份可变的会话内“数据库”（发布/认领/交接状态会在本次会话内保持），
// 让交互流程（发布→匹配→认领→交接）在演示模式下也能闭环体验。

import type {
  AxiosAdapter,
  AxiosResponse,
  InternalAxiosRequestConfig,
} from 'axios'
import type {
  AuditLog,
  FoundItemOut,
  IMSessionListItem,
  IMMessageOut,
  IMSessionOut,
  LostItemOut,
  MatchOut,
  Page,
  Token,
  UserOut,
} from '@/types'
import {
  MOCK_CURRENT_USER_ID,
  currentMockRole,
  makeMockToken,
  mockAdminUser,
  mockAuditLogs,
  mockCurrentUser,
  mockFoundItems,
  mockIMMessages,
  mockIMSessions,
  mockLostItems,
  mockMatches,
  mockUsers,
  phImage,
} from './mockData'
import {
  MATCH_SUSPECT_MAX,
  MATCH_THRESHOLD,
  MATCH_TOP_N,
  MOCK_ADMIN_APPLY_CODE,
  SEED_CATEGORIES,
} from './constants'

// ---------------- 会话内可变状态 ----------------
let mockToken: string | null = null
let mockUser: UserOut = mockCurrentUser
const handoverState: Record<number, { code: string; verified_by_lost: boolean; verified_by_finder: boolean }> = {}

function setSession(token: string, user: UserOut) {
  mockToken = token
  mockUser = user
}

// ---------------- 响应构造 ----------------
function ok<T>(config: InternalAxiosRequestConfig, data: T): AxiosResponse {
  return {
    data: { code: 0, message: 'success', data },
    status: 200,
    statusText: 'OK',
    headers: {},
    config,
    request: {},
  }
}

function fail(
  config: InternalAxiosRequestConfig,
  code: number,
  message: string,
  httpStatus = 400,
): AxiosResponse {
  return {
    data: { code, message, data: null },
    status: httpStatus,
    statusText: 'ERR',
    headers: {},
    config,
    request: {},
  }
}

// ---------------- 工具 ----------------
function authHeader(config: InternalAxiosRequestConfig): string | undefined {
  const h = config.headers as unknown as {
    get?: (k: string) => string | undefined
    Authorization?: string
  }
  if (!h) return undefined
  if (typeof h.get === 'function') return h.get('Authorization') || undefined
  return h.Authorization
}

function requireAuth(config: InternalAxiosRequestConfig): boolean {
  const a = authHeader(config)
  return !!a && a.startsWith('Bearer ')
}

function parseBody(config: InternalAxiosRequestConfig): unknown {
  const d = config.data
  if (d == null) return {}
  if (typeof d === 'string') {
    try {
      return JSON.parse(d)
    } catch {
      return {}
    }
  }
  if (typeof FormData !== 'undefined' && d instanceof FormData) return d
  if (typeof URLSearchParams !== 'undefined' && d instanceof URLSearchParams) {
    const o: Record<string, string> = {}
    d.forEach((v, k) => (o[k] = v))
    return o
  }
  return d
}

function fdString(fd: FormData, key: string): string {
  const v = fd.get(key)
  return v == null ? '' : String(v)
}

function fdInt(fd: FormData, key: string, fallback = 0): number {
  const v = fd.get(key)
  if (v == null || v === '') return fallback
  const n = Number(v)
  return Number.isFinite(n) ? n : fallback
}

function genCode(len = 6): string {
  const alpha = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
  let s = ''
  for (let i = 0; i < len; i++) s += alpha[Math.floor(Math.random() * alpha.length)]
  return s
}

function nextId(arr: { id: number }[]): number {
  return arr.reduce((m, x) => Math.max(m, x.id), 0) + 1
}

function paginate<T>(items: T[], page: number, pageSize: number): Page<T> {
  const total = items.length
  const start = (page - 1) * pageSize
  return {
    items: items.slice(start, start + pageSize),
    total,
    page,
    page_size: pageSize,
  }
}

// v7：用户侧可见性过滤——未软删（deleted_at 为空）且未过期（expires_at > now）。
// 与后端 list_lost_items/list_found_items/my_items 的语义一致。
type ExpirableItem = { expires_at?: string | null; deleted_at?: string | null }
function userVisibleItem(it: ExpirableItem): boolean {
  if (it.deleted_at) return false
  if (!it.expires_at) return true
  return it.expires_at > new Date().toISOString()
}

// ---------------- 2026-08-05 增量：演示候选生成 / 对端可见性（与真实后端同口径） ----------------
function sharedNounTags(a: string[] | undefined, b: string[] | undefined): boolean {
  return (a || []).some((t) => (b || []).includes(t))
}

/** 确定性伪随机打分：基于双方 id 生成稳定分数；同类目加成 → 同时产出低分/高分候选。 */
function mockMatchScore(lost: LostItemOut, found: FoundItemOut): number {
  const seed = Math.abs(lost.id * 131 + found.id * 17)
  const sameCat = !!lost.category_name && lost.category_name === found.category_name
  let s = 34 + (seed % 49) // 34..82
  if (sameCat) s += 14 // 同类目 → 84..96（高分候选）
  return Math.max(30, Math.min(96, s))
}

/**
 * 由失物/拾物对构造 MatchOut（v10 评分引擎 v2 明细按比例填充，总分与 match_score 对齐；
 * id 由调用方显式传入保证唯一）。
 *
 * 演示态口径必须与后端 `MatchService.score_detail` 一致：
 * 分类 20 + 文字 70（量词 15 / 颜色 20 / 状态 10 / 地点 15 / 关键词 10）+ 时间 10。
 * 七子维度是**归一化前的原始分**，演示态里 `norm_factor` 恒为 1（mock 分数直接就是最终分）。
 * 旧五维键按 R2 §7.1 同步映射保留，老组件不断裂。
 */
function buildMockMatchOut(
  lost: LostItemOut,
  found: FoundItemOut,
  status: number,
  score: number,
  id: number,
  flowType = 0,
): MatchOut {
  const total = Math.round(score)
  const r = score / 100
  // v10 七子维度（按比例分摊，保证 Σ = total，可直接用于前端明细条）
  const photoCategory = Math.round(r * 20)
  const qty = Math.round(r * 15)
  const state = Math.round(r * 10)
  const place = Math.round(r * 15)
  const keyword = Math.round(r * 10)
  const time = Math.round(r * 10)
  // 颜色维度吸收取整误差，保证七维之和恰等于 total（避免明细条与总分对不上）
  const color = total - (photoCategory + qty + state + place + keyword + time)
  const text = qty + color + state + place + keyword
  const sharedText = (lost.tags || []).filter((t) => (found.tags || []).includes(t))
  // 演示态冲突信号：双方都标了颜色 tag 且完全不相交 → color_conflict（与后端软化口径一致）
  const lostColors = (lost.tags || []).filter((t) => t.endsWith('色'))
  const foundColors = (found.tags || []).filter((t) => t.endsWith('色'))
  const signals: string[] =
    lostColors.length > 0 &&
    foundColors.length > 0 &&
    !lostColors.some((c) => foundColors.includes(c))
      ? ['color_conflict']
      : []
  return {
    id,
    lost_id: lost.id,
    found_id: found.id,
    match_score: score,
    status,
    claim_reason: null,
    created_at: isoNow(),
    lost_item: lost,
    found_item: found,
    suspected: score >= MATCH_THRESHOLD,
    flow_type: flowType,
    // ---- 旧五维键（R2 §7.1 映射，老组件继续可读） ----
    photo: photoCategory, // = photo_category
    category: 0, // [deprecated] 已并入 photo_category
    text,
    text_match_rate: Number((text / 70).toFixed(4)),
    appearance: 0, // [deprecated] flow-v2 并入 text
    feature: 0, // [deprecated] flow-v2 并入 text
    time,
    location: place, // = place（已含在文字 70 内）
    shared_text: sharedText,
    total,
    // ---- v10 新增 10 个字段 ----
    photo_category: photoCategory,
    qty,
    color,
    state,
    place,
    keyword,
    signals,
    raw_total: total,
    norm_factor: 1,
    provided_dims: ['photo_category', 'qty', 'color', 'place', 'time'],
  }
}

/**
 * v10 变更 B（TS 版，与后端 `publish_service._cut_with_suspects` **同款逻辑**）。
 *
 * `scored` 必须已按「分数降序、同分 id 升序」排好。返回「保底前 baseN 条 +
 * 其后所有 ≥ MATCH_THRESHOLD 的疑似」。演示态口径必须与后端一致（AC-B10）。
 *
 * @param scored 已降序的候选数组
 * @param baseN 普通候选保底条数（可为 0）
 * @param scoreOf 取分函数
 */
function cutWithSuspects<T>(scored: T[], baseN: number, scoreOf: (x: T) => number): T[] {
  let n = Math.max(0, baseN)
  while (n < scored.length && scoreOf(scored[n]) >= MATCH_THRESHOLD) n += 1
  const cap = Math.max(MATCH_TOP_N, MATCH_SUSPECT_MAX)
  return scored.slice(0, Math.min(n, cap))
}

/** 失物侧候选生成：从拾物池筛同类目/共享名词 tag，去重 + 打分降序。
 *  flow-v3（修订 flow-v2 R2-a）：**不再按 keep_status 过滤** —— keep1（留在原地未挪动）拾物
 *  单向进入匹配池，可作为失主侧候选返回（与后端 `_recall_lost_candidates` 同口径）。
 *  单向性由 `handleCreateFound` 的 isKeep1 早退保证（反向不为拾得者生成候选）。
 *  v10 变更 B：`maxCount` 语义由「上限」改为「普通候选保底条数」，≥MATCH_THRESHOLD 的疑似不受此限。 */
function genCandidatesForLost(lost: LostItemOut, status: number, maxCount = MATCH_TOP_N): MatchOut[] {
  const dup = new Set(
    mockMatches.filter((m) => m.lost_id === lost.id).map((m) => m.found_id),
  )
  const pool = mockFoundItems.filter(
    (f) =>
      f.status === 0 &&
      !f.deleted_at &&
      (f.category_name === lost.category_name ||
        sharedNounTags(lost.tags || [], f.tags || [])),
  )
  const sorted = pool
    .filter((f) => !dup.has(f.id))
    .map((f) => ({ score: mockMatchScore(lost, f), found: f }))
    .sort((a, b) => b.score - a.score || a.found.id - b.found.id)
  const scored = cutWithSuspects(sorted, maxCount, (x) => x.score)
  // 批次内显式分配连续 id，避免 nextId 在 map 循环内重复
  const base = nextId(mockMatches as { id: number }[])
  return scored.map(({ score, found }, idx) =>
    buildMockMatchOut(lost, found, status, score, base + idx),
  )
}

/** 拾物侧候选生成（Q5 对称）：从失物池筛同类目/共享名词 tag，去重 + 打分降序。
 *  v10 变更 B：同样放开疑似，与正向路径口径对称。 */
function genCandidatesForFound(found: FoundItemOut, status: number, maxCount = MATCH_TOP_N): MatchOut[] {
  const dup = new Set(
    mockMatches.filter((m) => m.found_id === found.id).map((m) => m.lost_id),
  )
  const pool = mockLostItems.filter(
    (l) =>
      (l.status === 0 || l.status === 1) &&
      !l.deleted_at &&
      (l.category_name === found.category_name ||
        sharedNounTags(l.tags || [], found.tags || [])),
  )
  const sorted = pool
    .filter((l) => !dup.has(l.id))
    .map((l) => ({ score: mockMatchScore(l, found), lost: l }))
    .sort((a, b) => b.score - a.score || a.lost.id - b.lost.id)
  const scored = cutWithSuspects(sorted, maxCount, (x) => x.score)
  // 批次内显式分配连续 id，避免 nextId 在 map 循环内重复
  const base = nextId(mockMatches as { id: number }[])
  return scored.map(({ score, lost }, idx) =>
    buildMockMatchOut(lost, found, status, score, base + idx),
  )
}

/** P1-2：对端可见性过滤——对端软删 / 进行中状态对端已解决 → 隐藏（终态保留）。 */
function counterpartHidden(m: MatchOut): boolean {
  const lost = m.lost_item
  const found = m.found_item
  if (!lost || !found) return true
  if (lost.deleted_at || found.deleted_at) return true
  if (m.status === 0 || m.status === 1 || m.status === 4) {
    if (lost.status === 3 || found.status === 1) return true
  }
  return false
}

// ---------------- 路由处理 ----------------
type Ctx = {
  config: InternalAxiosRequestConfig
  body: unknown
  params: URLSearchParams
}

function handleRegister(ctx: Ctx): AxiosResponse {
  const b = ctx.body as Record<string, string>
  // v10 变更 C：邀请码命中 → role=1（静默；不命中/不填一律走原 currentMockRole，响应体形态完全一致）。
  // ⚠️ 已知演示态限制（R2 §4.4）：`buildUserFromToken` 的演示分支硬编码 role:0，
  //    因此「注册成管理员 → 登出 → 再登录」会掉回普通用户。验收时注册后请勿中途登出。
  const isAdmin = (b.admin_code || '').trim() === MOCK_ADMIN_APPLY_CODE
  const user: UserOut = {
    ...mockCurrentUser,
    student_no: b.student_no || mockCurrentUser.student_no,
    phone: (b.phone || '13800000000').replace(/(\d{3})\d{4}(\d{4})/, '$1****$2'),
    real_name: b.real_name || null,
    role: isAdmin ? 1 : currentMockRole,
  }
  const token: Token = makeMockToken()
  setSession(token.access_token, user)
  return ok(ctx.config, { user, token })
}

function handleLogin(ctx: Ctx): AxiosResponse {
  const b = ctx.body as Record<string, string>
  const user: UserOut = {
    ...mockCurrentUser,
    student_no: b.student_no || mockCurrentUser.student_no,
    role: currentMockRole,
  }
  const token: Token = makeMockToken()
  setSession(token.access_token, user)
  return ok(ctx.config, token)
}

function handleRefresh(ctx: Ctx): AxiosResponse {
  const token: Token = makeMockToken()
  return ok(ctx.config, token)
}

function handleSendSms(ctx: Ctx): AxiosResponse {
  // 演示模式下固定返回演示验证码，方便联调
  return ok(ctx.config, {
    sent: true,
    dev_code: '123456',
  })
}

function handleBindPhone(ctx: Ctx): AxiosResponse {
  const b = ctx.body as Record<string, string>
  mockUser = { ...mockUser, phone: (b.phone || mockUser.phone).replace(/(\d{3})\d{4}(\d{4})/, '$1****$2') }
  return ok(ctx.config, mockUser)
}

function handleLogout(ctx: Ctx): AxiosResponse {
  mockToken = null
  return ok(ctx.config, { ok: true })
}

function handleCreateLost(ctx: Ctx): AxiosResponse {
  const fd = ctx.body as FormData
  const imageCount = typeof FormData !== 'undefined' && fd instanceof FormData
    ? fd.getAll('images').filter((f) => f && (f as Blob).size != null).length
    : 0
  const images = Array.from({ length: Math.max(imageCount, 1) }, (_, i) => phImage('失物照片', i))
  const item: LostItemOut = {
    id: nextId(mockLostItems),
    publisher_id: mockUser.id,
    category_id: null,
    category_name: fdString(fd, 'category_name') || '未分类',
    title: fdString(fd, 'title') || '未命名失物',
    description: fdString(fd, 'description'),
    images,
    color: fdString(fd, 'color') || null,
    tags: [],
    image_hash: null,
    appearance: fdString(fd, 'appearance') || null,
    features: fdString(fd, 'features') || null,
    location: fdString(fd, 'location') || null,
    lost_time: fdString(fd, 'lost_time') || new Date().toISOString(),
    status: 0,
    created_at: new Date().toISOString(),
  }
  mockLostItems.unshift(item)
  // 2026-08-05 增量：发布后模拟后端候选生成（同类目/共享 tag → top10 无论分数落 status=0，含低分）
  const created = genCandidatesForLost(item, 0)
  if (created.length) {
    mockMatches.unshift(...created)
    item.status = 1 // 生成任意候选 → MATCHING（与后端一致）
  }
  return ok(ctx.config, { item, suspected_matches: created })
}

function handleCreateFound(ctx: Ctx): AxiosResponse {
  const fd = ctx.body as FormData
  const files = typeof FormData !== 'undefined' && fd instanceof FormData
    ? (fd.getAll('images').filter((f) => f && (f as Blob).size != null) as Blob[])
    : []
  const images = files.length
    ? files.map((_, i) => phImage('拾物照片', i))
    : [phImage('拾物照片', 0)]
  const item: FoundItemOut = {
    id: nextId(mockFoundItems),
    finder_id: mockUser.id,
    category_id: null,
    category_name: fdString(fd, 'category_name') || '未分类',
    description: fdString(fd, 'description') || null,
    images,
    tags: [],
    image_hash: null,
    appearance: fdString(fd, 'appearance') || null,
    features: fdString(fd, 'features') || null,
    location: fdString(fd, 'location') || null,
    found_time: fdString(fd, 'found_time') || null,
    keep_status: fdInt(fd, 'keep_status', 0),
    contact_allowed: fdInt(fd, 'contact_allowed', 1),
    status: 0,
    created_at: new Date().toISOString(),
  }
  mockFoundItems.unshift(item)
  // flow-v3：keep1 单向 —— 不为拾得者反向生成候选失物（与后端 `_reverse_match_found` 早退同口径）；
  // 正向（失主发布 / 刷新候选）已放开 keep1，见 genCandidatesForLost。
  // keep0（暂为保管）保持现状：发布对称生成候选失物（Q5）；每条新匹配的 lost.status → MATCHING
  const isKeep1 = item.keep_status === 1
  const created = isKeep1 ? [] : genCandidatesForFound(item, 0)
  for (const m of created) {
    if (m.lost_item) m.lost_item.status = 1
  }
  if (created.length) {
    mockMatches.unshift(...created)
  }
  return ok(ctx.config, { item, suspected_matches: created })
}

function listLost(ctx: Ctx): AxiosResponse {
  const page = Number(ctx.params.get('page') || '1')
  const pageSize = Number(ctx.params.get('page_size') || '20')
  let items = [...mockLostItems].sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
  // v6：按物品自身 status 过滤（resolved_only > exclude_resolved > 旧 status）。
  // ⚠️ 仅认 LostItem.status（3=已解决），不读 MatchRecord.status，规避数值碰撞。
  const resolvedOnly = ctx.params.get('resolved_only') === 'true'
  const excludeResolved = ctx.params.get('exclude_resolved') === 'true'
  if (resolvedOnly) {
    items = items.filter((i) => i.status === 3)
  } else if (excludeResolved) {
    items = items.filter((i) => i.status !== 3)
  } else {
    const s = ctx.params.get('status')
    if (s != null) items = items.filter((i) => i.status === Number(s))
  }
  // v7：用户侧过滤（未过期 + 未软删）
  items = items.filter(userVisibleItem)
  return ok(ctx.config, paginate(items, page, pageSize))
}

function listFound(ctx: Ctx): AxiosResponse {
  const page = Number(ctx.params.get('page') || '1')
  const pageSize = Number(ctx.params.get('page_size') || '20')
  let items = [...mockFoundItems].sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
  // v6：按物品自身 status 过滤（resolved_only > exclude_resolved > 旧 status）。
  // ⚠️ 仅认 FoundItem.status（1=已解决），不读 MatchRecord.status，规避数值碰撞。
  const resolvedOnly = ctx.params.get('resolved_only') === 'true'
  const excludeResolved = ctx.params.get('exclude_resolved') === 'true'
  if (resolvedOnly) {
    items = items.filter((i) => i.status === 1)
  } else if (excludeResolved) {
    items = items.filter((i) => i.status !== 1)
  } else {
    const s = ctx.params.get('status')
    if (s != null) items = items.filter((i) => i.status === Number(s))
  }
  // v7：用户侧过滤（未过期 + 未软删）
  items = items.filter(userVisibleItem)
  return ok(ctx.config, paginate(items, page, pageSize))
}

function getLost(ctx: Ctx, id: number): AxiosResponse {
  const it = mockLostItems.find((x) => x.id === id)
  return it ? ok(ctx.config, it) : fail(ctx.config, 2001, '失物不存在', 404)
}

function getFound(ctx: Ctx, id: number): AxiosResponse {
  const it = mockFoundItems.find((x) => x.id === id)
  return it ? ok(ctx.config, it) : fail(ctx.config, 2001, '拾物不存在', 404)
}

function deleteLost(ctx: Ctx, id: number): AxiosResponse {
  const it = mockLostItems.find((x) => x.id === id)
  if (!it) return fail(ctx.config, 2001, '失物不存在', 404)
  // v7：软删（与后端 DELETE /lost-items/{id} 语义对齐，不破坏引用完整性）
  it.deleted_at = new Date().toISOString()
  return ok(ctx.config, it)
}

function deleteFound(ctx: Ctx, id: number): AxiosResponse {
  const it = mockFoundItems.find((x) => x.id === id)
  if (!it) return fail(ctx.config, 2001, '拾物不存在', 404)
  // v7：软删（与后端 DELETE /found-items/{id} 语义对齐，不破坏引用完整性）
  it.deleted_at = new Date().toISOString()
  return ok(ctx.config, it)
}

function matchesForLost(ctx: Ctx, id: number): AxiosResponse {
  const list = mockMatches
    .filter((m) => m.lost_id === id)
    .filter((m) => !counterpartHidden(m)) // P1-2：与后端放开阈值后行为一致（含低分）
    .sort((a, b) => b.match_score - a.match_score)
  return ok(ctx.config, list)
}

function myMatches(ctx: Ctx): AxiosResponse {
  const page = Number(ctx.params.get('page') || '1')
  const pageSize = Number(ctx.params.get('page_size') || '20')
  let list = [...mockMatches].sort((a, b) => b.match_score - a.match_score)
  // 与真实后端 /matches 一致：提供 status 时按状态过滤（v6 已完成交接 tab 传 status=2）
  const s = ctx.params.get('status')
  if (s != null) list = list.filter((m) => m.status === Number(s))
  // P1-2：对端可见性过滤（软删 / 进行中状态对端已解决 → 隐藏；终态保留）
  list = list.filter((m) => !counterpartHidden(m))
  // flow-v3 U2=完全隐藏：拾得者侧过滤掉 keep1（留在原地未挪动）拾物的全部候选，
  // 与后端 list_my_matches 的 as_found 分支 keep_status 过滤同口径
  list = list.filter(
    (m) => !(m.found_item?.finder_id === mockUser.id && m.found_item?.keep_status === 1),
  )
  return ok(ctx.config, paginate(list, page, pageSize))
}

// ---------------- P2-1：手动刷新候选（与后端 refresh_matches_for_lost 同口径） ----------------
function handleRefreshMatches(ctx: Ctx, lostId: number): AxiosResponse {
  const lost = mockLostItems.find((x) => x.id === lostId)
  if (!lost) return fail(ctx.config, 2001, '失物不存在', 404)
  if (lost.deleted_at) return fail(ctx.config, 9001, '该失物已删除，不可刷新候选', 422)
  if (lost.status === 3) return fail(ctx.config, 9001, '已解决的失物不可刷新候选', 422)
  const existingCount = mockMatches.filter((m) => m.lost_id === lostId).length
  // v10 变更 B（B-4/B-5）：**删除「已满即返回空」的早退**。quota=0 时仍继续，
  // 由 cutWithSuspects 只补 ≥MATCH_THRESHOLD 的疑似（与后端 refresh_lost_candidates 同口径）。
  const quota = Math.max(0, MATCH_TOP_N - existingCount)
  const created = genCandidatesForLost(lost, 0, quota)
  if (created.length) {
    mockMatches.unshift(...created)
    lost.status = 1
  }
  const matches = mockMatches
    .filter((m) => m.lost_id === lostId)
    .filter((m) => !counterpartHidden(m))
    .sort((a, b) => b.match_score - a.match_score)
  return ok(ctx.config, { created: created.length, matches })
}

function claimMatch(ctx: Ctx, id: number): AxiosResponse {
  const b = ctx.body as Record<string, string>
  const reason = (b.claim_reason || '').trim()
  if (!reason) return fail(ctx.config, 3002, '认领理由必填', 400)
  const m = mockMatches.find((x) => x.id === id)
  if (!m) return fail(ctx.config, 2001, '匹配不存在', 404)
  if (m.status !== 0) return fail(ctx.config, 3003, '该匹配已处理（非待认领）', 409)
  // R2（P0-3 分流守卫）：keep_status=1 拾物不允许走普通 claim，须走「申请即完成」
  if (m.found_item?.keep_status === 1)
    return fail(ctx.config, 9001, '该拾物留在原地未挪动，请使用「申请即完成」', 422)
  m.status = 1
  m.claim_reason = reason
  return ok(ctx.config, m)
}

// flow-v2（R2 / P0-3）：keep1「申请即完成」—— 对 status=0 候选一步到位终态已完成。
function claimCompleteMatch(ctx: Ctx, id: number): AxiosResponse {
  const m = mockMatches.find((x) => x.id === id)
  if (!m) return fail(ctx.config, 2001, '匹配不存在', 404)
  if (m.lost_item?.publisher_id !== mockUser.id)
    return fail(ctx.config, 2003, '仅失主可申请即完成', 403)
  if (m.found_item?.keep_status !== 1)
    return fail(ctx.config, 9001, '该拾物非「留在原地未挪动」，请走标准认领流程', 422)
  if (m.status !== 0) return fail(ctx.config, 3003, '仅待认领候选可申请即完成', 409)
  if (m.found_item?.status !== 0)
    return fail(ctx.config, 3003, '该拾物已处理，不可申请', 409)
  m.status = 2
  m.flow_type = 1
  if (m.lost_item) m.lost_item.status = 3
  if (m.found_item) m.found_item.status = 1
  resetCompletion(m)
  return ok(ctx.config, m)
}

// flow-v2（R2 / P0-4）：keep1 完成记录撤回 —— status→6、双端状态回退、拾物恢复可申请。
function revokeMatch(ctx: Ctx, id: number): AxiosResponse {
  const m = mockMatches.find((x) => x.id === id)
  if (!m) return fail(ctx.config, 2001, '匹配不存在', 404)
  if (m.lost_item?.publisher_id !== mockUser.id)
    return fail(ctx.config, 2003, '仅失主可撤回', 403)
  if (m.flow_type !== 1 || m.status !== 2)
    return fail(ctx.config, 3003, '仅 keep1 申请即完成的已完成记录可撤回', 409)
  m.status = 6
  // 失物回退：有其他进行中匹配（status∈{0,1,4}）→ MATCHING(1)，否则 PENDING_MATCH(0)
  const lostId = m.lost_id
  const hasActive = mockMatches.some(
    (x) =>
      x.lost_id === lostId &&
      x.id !== id &&
      (x.status === 0 || x.status === 1 || x.status === 4),
  )
  if (m.lost_item) m.lost_item.status = hasActive ? 1 : 0
  if (m.found_item) {
    m.found_item.status = 0
    // 双方 expires_at 顺延 +90 天恢复可检索
    m.found_item.expires_at = new Date(Date.now() + 90 * 24 * 3600 * 1000).toISOString()
  }
  if (m.lost_item) {
    m.lost_item.expires_at = new Date(Date.now() + 90 * 24 * 3600 * 1000).toISOString()
  }
  // completed_at 保留原值（撤回时间以审计/前端展示为准）
  return ok(ctx.config, m)
}

function confirmReturn(ctx: Ctx, id: number): AxiosResponse {
  const m = mockMatches.find((x) => x.id === id)
  if (!m) return fail(ctx.config, 2001, '匹配不存在', 404)
  // flow-v3 keep1 单向性守卫（与后端 match.py confirm_return 对齐）
  if (m.found_item?.keep_status === 1)
    return fail(ctx.config, 9001, '该物品留在原地未挪动，无需你确认归还，请等待失主申请后自行取回', 422)
  if (m.status === 2 || m.status === 3)
    return fail(ctx.config, 3003, '该匹配状态不可确认归还', 409)
  return ok(ctx.config, m)
}

function handoverGenerate(ctx: Ctx, id: number): AxiosResponse {
  const m = mockMatches.find((x) => x.id === id)
  if (!m) return fail(ctx.config, 2001, '匹配不存在', 404)
  if (m.status !== 1) return fail(ctx.config, 3003, '仅认领中（待交接）的匹配可生成交接码', 409)
  const code = genCode(6)
  handoverState[id] = { code, verified_by_lost: false, verified_by_finder: false }
  return ok(ctx.config, {
    code,
    qr_token: Math.random().toString(36).slice(2) + Date.now().toString(36),
    expire_at: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
  })
}

function handoverVerify(ctx: Ctx, id: number): AxiosResponse {
  const b = ctx.body as Record<string, string>
  const code = (b.code || '').trim().toUpperCase()
  const role = b.role
  const st = handoverState[id]
  if (!st) return fail(ctx.config, 4001, '交接码无效', 400)
  if (st.code !== code) return fail(ctx.config, 4001, '交接码无效', 400)
  if (role === 'lost') {
    if (st.verified_by_lost) return fail(ctx.config, 4003, '失主端已验证，请等待对方确认', 409)
    st.verified_by_lost = true
  } else if (role === 'finder') {
    if (st.verified_by_finder) return fail(ctx.config, 4003, '拾得者端已验证，请等待对方确认', 409)
    st.verified_by_finder = true
  } else {
    return fail(ctx.config, 9001, 'role 必须为 lost 或 finder', 422)
  }
  const both = st.verified_by_lost && st.verified_by_finder
  if (both) {
    const m = mockMatches.find((x) => x.id === id)
    if (m) {
      m.status = 2
      resetCompletion(m)
    }
  }
  return ok(ctx.config, {
    both_verified: both,
    verified_by_lost: st.verified_by_lost,
    verified_by_finder: st.verified_by_finder,
  })
}

function rejectMatch(ctx: Ctx, id: number): AxiosResponse {
  const m = mockMatches.find((x) => x.id === id)
  if (!m) return fail(ctx.config, 2001, '匹配不存在', 404)
  // flow-v3 keep1 单向性守卫（与后端 match.py reject_match 对齐）
  if (m.found_item?.keep_status === 1)
    return fail(ctx.config, 9001, '该物品留在原地未挪动，是否被领走由失主决定，你无需处理', 422)
  if (m.status === 2 || m.status === 3)
    return fail(ctx.config, 3003, '该匹配已处理（非待认领/认领中）', 409)
  m.status = 3
  return ok(ctx.config, m)
}

function auditLogs(ctx: Ctx): AxiosResponse {
  const page = Number(ctx.params.get('page') || '1')
  const pageSize = Number(ctx.params.get('page_size') || '20')
  const items = [...mockAuditLogs].sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
  return ok(ctx.config, paginate(items, page, pageSize))
}

// ---------------- 我的发布（v3 需求 E） ----------------
function myItems(ctx: Ctx): AxiosResponse {
  const lost = mockLostItems.filter((x) => x.publisher_id === mockUser.id && userVisibleItem(x))
  const found = mockFoundItems.filter((x) => x.finder_id === mockUser.id && userVisibleItem(x))
  return ok(ctx.config, { lost, found })
}

// ---------------- IM 即时通讯（v3 需求 D） ----------------
function isoNow(): string {
  return new Date().toISOString()
}

// v7：与后端 3 个完成路径对齐——写 completed_at 并把双方物品 expires_at 顺延 +90 天。
function resetCompletion(m: MatchOut): void {
  m.completed_at = isoNow()
  const later = new Date(Date.now() + 90 * 24 * 3600 * 1000).toISOString()
  if (m.lost_item) m.lost_item.expires_at = later
  if (m.found_item) m.found_item.expires_at = later
}

function handleCreateSession(ctx: Ctx): AxiosResponse {
  const b = ctx.body as { match_id?: number; found_id?: number }
  // v4：无 match 的联系入口（绑定具体拾物）
  if (b.found_id != null) {
    const foundId = Number(b.found_id)
    const found = mockFoundItems.find((x) => x.id === foundId)
    if (!found) return fail(ctx.config, 2001, '拾物不存在', 404)
    // 门控（Q5）：唯一来源为 found_item.contact_allowed
    if (found.contact_allowed === 0)
      return fail(ctx.config, 2003, '对方暂未开启联系', 403)
    const lostUser = mockUser.id
    const foundUser = found.finder_id
    let session = mockIMSessions.find(
      (s) => s.found_id === foundId && s.status === 0,
    )
    if (!session) {
      session = {
        id: nextId(mockIMSessions as { id: number }[]),
        match_id: null,
        found_id: foundId,
        lost_user_id: lostUser,
        finder_user_id: foundUser,
        status: 0,
        created_at: isoNow(),
        last_message_at: null,
        expires_at: new Date(Date.now() + 30 * 24 * 3600 * 1000).toISOString(),
      }
      mockIMSessions.push(session)
    }
    return ok(ctx.config, session)
  }

  const matchId = Number(b.match_id)
  const m = mockMatches.find((x) => x.id === matchId)
  if (!m) return fail(ctx.config, 2001, '匹配记录不存在', 404)
  const lostUser = m.lost_item?.publisher_id ?? -1
  const foundUser = m.found_item?.finder_id ?? -1
  if (mockUser.id !== lostUser && mockUser.id !== foundUser)
    return fail(ctx.config, 2003, '无权对该匹配发起会话', 403)
  // 门控（Q5）：唯一来源为对端 found_item.contact_allowed
  if (m.found_item?.contact_allowed === 0)
    return fail(ctx.config, 2003, '对方暂未开启联系', 403)
  let session = mockIMSessions.find((s) => s.match_id === matchId && s.status === 0)
  if (!session) {
    session = {
      id: nextId(mockIMSessions as { id: number }[]),
      match_id: matchId,
      found_id: null,
      lost_user_id: lostUser,
      finder_user_id: foundUser,
      status: 0,
      created_at: isoNow(),
      last_message_at: null,
      expires_at: new Date(Date.now() + 30 * 24 * 3600 * 1000).toISOString(),
    }
    mockIMSessions.push(session)
  }
  return ok(ctx.config, session)
}

// v4：失主手动申请匹配（未挪动自取），生成 status=4「待自取」单边匹配
// flow-v2（R2 / P1-1 分流）：found.keep_status===1（留在原地未挪动）→ 一步完成 status=2（flow_type=1），
// 与后端 create_manual_match 的 keep1 分流一致；keep0 → status=4 现状。
function createManualMatch(ctx: Ctx): AxiosResponse {
  const b = ctx.body as { lost_id?: number; found_id?: number }
  const lostId = Number(b.lost_id)
  const foundId = Number(b.found_id)
  const lost = mockLostItems.find((x) => x.id === lostId)
  const found = mockFoundItems.find((x) => x.id === foundId)
  if (!lost) return fail(ctx.config, 2001, '失物不存在', 404)
  if (!found) return fail(ctx.config, 2001, '拾物不存在', 404)
  if (lost.publisher_id !== mockUser.id)
    return fail(ctx.config, 2003, '仅失主可发起申请匹配', 403)
  if (lost.status !== 0 && lost.status !== 1 && lost.status !== 2)
    return fail(ctx.config, 9001, '该失物状态不可发起申请匹配', 422)
  if (found.status !== 0)
    return fail(ctx.config, 3003, '该拾物不可申请匹配', 409)
  const dup = mockMatches.find(
    (x) =>
      x.lost_id === lostId &&
      x.found_id === foundId &&
      (x.status === 0 || x.status === 1 || x.status === 4),
  )
  if (dup) return fail(ctx.config, 3003, '该失物与拾物已存在进行中的匹配', 409)
  if (found.keep_status === 1) {
    // P1-1 分流：keep1 → 一步完成（终态 status=2 + flow_type=1 + 双端已解决 + completed_at）
    const m: MatchOut = {
      id: nextId(mockMatches as { id: number }[]),
      lost_id: lostId,
      found_id: foundId,
      match_score: 82.5,
      status: 2,
      flow_type: 1,
      claim_reason: null,
      created_at: isoNow(),
      lost_item: lost,
      found_item: found,
      suspected: true,
      photo: 15,
      category: 20,
      text: 40,
      text_match_rate: 0.8,
      appearance: 0,
      feature: 0,
      time: 2.5,
      location: 5,
      shared_text: (lost.tags || []).filter((t) => (found.tags || []).includes(t)),
      total: 83,
    }
    lost.status = 3
    found.status = 1
    resetCompletion(m)
    mockMatches.unshift(m)
    return ok(ctx.config, m)
  }
  const m: MatchOut = {
    id: nextId(mockMatches as { id: number }[]),
    lost_id: lostId,
    found_id: foundId,
    match_score: 79.0,
    status: 4,
    flow_type: 0,
    claim_reason: null,
    created_at: isoNow(),
    lost_item: lost,
    found_item: found,
    suspected: false,
    // flow-v2 五维明细（手动申请匹配以加权默认值填充，总分与 match_score 对齐）
    photo: 12,
    category: 16,
    text: 39,
    text_match_rate: 0.78,
    appearance: 0,
    feature: 0,
    time: 5,
    location: 7,
    shared_text: [],
    total: 79,
  }
  mockMatches.unshift(m)
  return ok(ctx.config, m)
}

// v4：失主单边完成「待自取」匹配（status 4 → 2，双端置已解决）
function selfCompleteMatch(ctx: Ctx, id: number): AxiosResponse {
  const m = mockMatches.find((x) => x.id === id)
  if (!m) return fail(ctx.config, 2001, '匹配不存在', 404)
  if (m.lost_item?.publisher_id !== mockUser.id)
    return fail(ctx.config, 2003, '仅失主可完成自取', 403)
  if (m.status !== 4)
    return fail(ctx.config, 3003, '仅待自取匹配可完成', 409)
  m.status = 2
  if (m.lost_item) m.lost_item.status = 3
  if (m.found_item) m.found_item.status = 1
  resetCompletion(m)
  return ok(ctx.config, m)
}

function handleGetMessages(ctx: Ctx, id: number): AxiosResponse {
  const session = mockIMSessions.find((s) => s.id === id)
  if (!session) return fail(ctx.config, 2001, '会话不存在', 404)
  const since = Number(ctx.params.get('since_id') || '0')
  const list = mockIMMessages
    .filter((mm) => mm.session_id === id && mm.id > since)
    .sort((a, b) => a.id - b.id)
  return ok(ctx.config, list)
}

// ---------------- v5：「我的消息」会话列表（富化，与后端语义一致） ----------------
function buildSessionTitle(s: IMSessionOut): string {
  let found: FoundItemOut | null = null
  if (s.found_id != null) {
    found = mockFoundItems.find((f) => f.id === s.found_id) || null
  } else if (s.match_id != null) {
    const m = mockMatches.find((x) => x.id === s.match_id)
    found = m?.found_item || null
  }
  let name = ''
  if (found) {
    name = (found.category_name || '').trim()
    if (!name) name = (found.description || '').trim().slice(0, 12)
  }
  return name ? `联系对方 · ${name}` : '联系对方'
}

function buildSessionListItem(s: IMSessionOut): IMSessionListItem {
  const peerId = s.lost_user_id === mockUser.id ? s.finder_user_id : s.lost_user_id
  const peer = mockUsers.find((u) => u.id === peerId) || null
  const nickname = peer?.real_name || `用户${peerId}`
  const studentNo = peer?.student_no || ''
  const msgs = mockIMMessages
    .filter((mm) => mm.session_id === s.id)
    .sort((a, b) => a.id - b.id)
  const last = msgs.length ? msgs[msgs.length - 1] : null
  const preview = last ? last.content.slice(0, 20) || null : null
  const unread = !!last && last.sender_id !== mockUser.id
  const lastMessageAt = s.last_message_at || (last ? last.sent_at : null)
  return {
    id: s.id,
    match_id: s.match_id,
    found_id: s.found_id,
    lost_user_id: s.lost_user_id,
    finder_user_id: s.finder_user_id,
    peer_user: { id: peerId, nickname, student_no: studentNo },
    title: buildSessionTitle(s),
    last_message_at: lastMessageAt,
    last_message_preview: preview,
    unread,
    status: s.status,
  }
}

function listMySessions(ctx: Ctx): AxiosResponse {
  const list = mockIMSessions
    .filter(
      (s) =>
        s.status === 0 &&
        (s.lost_user_id === mockUser.id || s.finder_user_id === mockUser.id),
    )
    .sort((a, b) => {
      const ta = a.last_message_at || ''
      const tb = b.last_message_at || ''
      // 空值排末尾
      if (!ta && !tb) return 0
      if (!ta) return 1
      if (!tb) return -1
      return tb < ta ? -1 : tb > ta ? 1 : 0
    })
    .map(buildSessionListItem)
  return ok(ctx.config, list)
}

function deleteSession(ctx: Ctx, id: number): AxiosResponse {
  const s = mockIMSessions.find((x) => x.id === id)
  if (!s) return fail(ctx.config, 2001, '会话不存在', 404)
  if (s.lost_user_id !== mockUser.id && s.finder_user_id !== mockUser.id)
    return fail(ctx.config, 2003, '无权操作该会话', 403)
  s.status = 1 // 软删
  return ok(ctx.config, { id: s.id, status: s.status })
}

function successSession(ctx: Ctx, id: number): AxiosResponse {
  const s = mockIMSessions.find((x) => x.id === id)
  if (!s) return fail(ctx.config, 2001, '会话不存在', 404)
  if (s.lost_user_id !== mockUser.id && s.finder_user_id !== mockUser.id)
    return fail(ctx.config, 2003, '无权操作该会话', 403)
  s.status = 1 // 软删
  let matchArchived = false
  if (s.match_id != null) {
    const m = mockMatches.find((x) => x.id === s.match_id)
    if (m && (m.status === 0 || m.status === 1 || m.status === 4)) {
      m.status = 2
      if (m.lost_item) m.lost_item.status = 3
      if (m.found_item) m.found_item.status = 1
      resetCompletion(m)
      matchArchived = true
    }
  }
  return ok(ctx.config, { id: s.id, status: s.status, match_archived: matchArchived })
}

// v5：未能找回（失主放弃匹配，软删 status=5 + 失物重入匹配池）
function giveupMatch(ctx: Ctx, id: number): AxiosResponse {
  const m = mockMatches.find((x) => x.id === id)
  if (!m) return fail(ctx.config, 2001, '匹配不存在', 404)
  if (m.lost_item?.publisher_id !== mockUser.id)
    return fail(ctx.config, 2003, '仅失主可放弃该匹配', 403)
  if (m.status === 2 || m.status === 3)
    return fail(ctx.config, 3003, '该匹配已终态，无法放弃', 409)
  m.status = 5
  if (m.lost_item) m.lost_item.status = 0
  return ok(ctx.config, m)
}

function handleSendMessage(ctx: Ctx, id: number): AxiosResponse {
  const session = mockIMSessions.find((s) => s.id === id)
  if (!session) return fail(ctx.config, 2001, '会话不存在', 404)
  const b = ctx.body as { content?: string; type?: string }
  const content = (b.content || '').trim()
  if (!content) return fail(ctx.config, 9001, '消息内容不能为空', 422)
  // 禁链接（与后端正则对齐，演示态同样拦截）
  if (/https?:\/\/|www\.|<a\s|href\s*=/i.test(content))
    return fail(ctx.config, 9001, '消息中不可包含外部链接', 422)
  // 门控双保险
  const match = mockMatches.find((x) => x.id === session.match_id)
  if (match?.found_item?.contact_allowed === 0)
    return fail(ctx.config, 2003, '对方暂未开启联系', 403)
  const senderRole = session.lost_user_id === mockUser.id ? 0 : 1
  const msg: IMMessageOut = {
    id: nextId(mockIMMessages as { id: number }[]),
    session_id: id,
    sender_id: mockUser.id,
    sender_role: senderRole,
    content_type: b.type === 'template' ? 1 : 0,
    content,
    sent_at: isoNow(),
  }
  mockIMMessages.push(msg)
  session.last_message_at = msg.sent_at
  return ok(ctx.config, msg)
}

// ---------------- 视觉预识别（演示占位） ----------------
// ⚠️ 演示模式占位：未做真实推理，返回结果不代表真实识别。
// 仅依据上传图片的「字节长度 + 文件名」做确定性伪随机，从种子类目中挑一个类目，
// 不同图片会得到不同类目（不再永远返回「手机」），但置信度为明显占位的低值。
// 若需要真实的 YOLOv8 视觉识别，请连接后端 —— /vision/predict 由 VisionService 提供真推理。
function handleVisionPredict(ctx: Ctx): AxiosResponse {
  // 演示态请求体为 FormData，字段名为 'image'（见 web/src/api/vision.ts）
  const body = ctx.body as unknown
  const file: File | null =
    typeof FormData !== 'undefined' && body instanceof FormData
      ? (body.get('image') as File | null)
      : null

  // 无图片（理论上不会发生，发布前已校验首图存在）时诚实降级为「其他 + 0.0」
  if (!file) {
    const other = SEED_CATEGORIES.find((c) => c.name === '其他') || SEED_CATEGORIES[0]
    return ok(ctx.config, {
      category_id: other.id,
      label: other.name,
      confidence: 0.0,
      categories: SEED_CATEGORIES.map((c) => ({ id: c.id, name: c.name })),
    })
  }

  // 确定性哈希：基于文件名 + 字节长度，避免 Math.random，
  // 保证同一图片结果稳定、便于演示复现。
  const seedStr = `${file.name || ''}::${file.size || 0}`
  let hash = 0
  for (let i = 0; i < seedStr.length; i++) {
    hash = (hash * 31 + seedStr.charCodeAt(i)) >>> 0
  }

  // 不同图片 → 不同类目（不再写死「手机」）
  const cat = SEED_CATEGORIES[hash % SEED_CATEGORIES.length]
  // 占位置信度：0.30~0.60 之间的确定值，明确提示这是演示而非真识别
  const confidence = Number((0.3 + (hash % 31) / 100).toFixed(2))

  return ok(ctx.config, {
    category_id: cat.id,
    label: cat.name,
    confidence,
    categories: SEED_CATEGORIES.map((c) => ({ id: c.id, name: c.name })),
  })
}

// ---------------- 审计导出（演示模式返回 Blob，触发下载） ----------------
function handleExportAudit(ctx: Ctx): AxiosResponse {
  const fmt = (ctx.params.get('format') || 'csv').toLowerCase()
  let content: string
  let mime: string
  if (fmt === 'json') {
    content = JSON.stringify(mockAuditLogs, null, 2)
    mime = 'application/json'
  } else {
    const header = 'id,user_id,action,target_type,target_id,ip,ua,gps,detail,created_at'
    const rows = mockAuditLogs.map((l) =>
      [
        l.id,
        l.user_id ?? '',
        l.action,
        l.target_type ?? '',
        l.target_id ?? '',
        l.ip ?? '',
        (l.ua ?? '').replace(/,/g, ' '),
        l.gps ?? '',
        (l.detail ?? '').replace(/,/g, ' '),
        l.created_at,
      ].join(','),
    )
    content = [header, ...rows].join('\n')
    mime = 'text/csv'
  }
  const blob = new Blob([content], { type: mime })
  return ok(ctx.config, blob)
}

// ---------------- v7：管理后台（演示态对齐 app/routers/admin.py） ----------------
const _FORENSIC_FIELDS = [
  'match_id',
  'lost_item_id', 'lost_category', 'lost_title', 'lost_description',
  'lost_images', 'lost_student_no', 'lost_phone',
  'found_item_id', 'found_category', 'found_description',
  'found_images', 'found_student_no', 'found_phone',
  'completed_at',
  'conversation',
]

// CSV 单元格转义（演示用，保证下载文件可被 Excel 解析）
function csvCell(v: unknown): string {
  const s = v == null ? '' : String(v)
  if (/[",\n\r]/.test(s)) return '"' + s.replace(/"/g, '""') + '"'
  return s
}

function buildConversationForMatch(matchId: number): string {
  const sessionIds = mockIMSessions.filter((s) => s.match_id === matchId).map((s) => s.id)
  if (!sessionIds.length) return ''
  const msgs = mockIMMessages
    .filter((mm) => sessionIds.includes(mm.session_id))
    .sort((a, b) => a.id - b.id)
  return msgs
    .map((mm) => {
      const role = mm.sender_role === 0 ? '失主' : '拾得者'
      return `[${mm.sent_at}] ${role}: ${mm.content}`
    })
    .join(' ⏎ ')
}

function buildForensicRow(m: MatchOut): Record<string, string> {
  const lost = m.lost_item
  const found = m.found_item
  const lostUser = lost ? mockUsers.find((u) => u.id === lost.publisher_id) : undefined
  const foundUser = found ? mockUsers.find((u) => u.id === found.finder_id) : undefined
  return {
    match_id: String(m.id),
    lost_item_id: lost ? String(lost.id) : '',
    lost_category: lost?.category_name || '',
    lost_title: lost?.title || '',
    lost_description: lost?.description || '',
    lost_images: (lost?.images || []).join('|'),
    lost_student_no: lostUser?.student_no || '',
    lost_phone: lostUser?.phone || '',
    found_item_id: found ? String(found.id) : '',
    found_category: found?.category_name || '',
    found_description: found?.description || '',
    found_images: (found?.images || []).join('|'),
    found_student_no: foundUser?.student_no || '',
    found_phone: foundUser?.phone || '',
    completed_at: m.completed_at || '',
    conversation: buildConversationForMatch(m.id),
  }
}

// 管理员匹配列表（与后端 GET /admin/matches 一致）。
// v10：新增 all_time —— true 时跳过留存时间窗，返回全部历史匹配（Q4 方案 A）。
function listAdminMatches(ctx: Ctx): AxiosResponse {
  const page = Number(ctx.params.get('page') || '1')
  const pageSize = Number(ctx.params.get('page_size') || '20')
  const s = ctx.params.get('status')
  const allTime = ctx.params.get('all_time') === 'true'
  const cutoff = new Date(Date.now() - 270 * 24 * 3600 * 1000).toISOString()
  const list = mockMatches
    .filter((m) => !!m.lost_item && !!m.found_item)
    .filter((m) => allTime || (m.lost_item?.expires_at || '') > cutoff)
    .filter((m) => allTime || (m.found_item?.expires_at || '') > cutoff)
    .filter((m) => (s == null ? true : m.status === Number(s)))
  return ok(ctx.config, paginate(list, page, pageSize))
}

// ---------------- v10-D1：用户列表（手机号明文，与后端 GET /admin/users 一致） ----------------
function listAdminUsers(ctx: Ctx): AxiosResponse {
  const page = Number(ctx.params.get('page') || '1')
  const pageSize = Number(ctx.params.get('page_size') || '20')
  const keyword = (ctx.params.get('keyword') || '').trim()
  const role = ctx.params.get('role')
  const status = ctx.params.get('status')
  const list = mockUsers
    .filter((u) =>
      !keyword ||
      (u.student_no || '').includes(keyword) ||
      (u.phone || '').includes(keyword) ||
      (u.real_name || '').includes(keyword),
    )
    .filter((u) => (role == null || role === '' ? true : u.role === Number(role)))
    .filter((u) => (status == null || status === '' ? true : u.status === Number(status)))
    .slice()
    .sort((a, b) => b.id - a.id)
  return ok(ctx.config, paginate(list, page, pageSize))
}

// ---------------- v10-D2：匹配详情（双方明文信息 + 结构化对话） ----------------
function getAdminMatchDetail(ctx: Ctx, matchId: number): AxiosResponse {
  const m = mockMatches.find((x) => x.id === matchId)
  if (!m) return fail(ctx.config, 9001, `匹配 ${matchId} 不存在`, 404)
  const lostUser = m.lost_item
    ? mockUsers.find((u) => u.id === m.lost_item!.publisher_id) || null
    : null
  const foundUser = m.found_item
    ? mockUsers.find((u) => u.id === m.found_item!.finder_id) || null
    : null
  const sessionIds = mockIMSessions.filter((s) => s.match_id === matchId).map((s) => s.id)
  const conversation = mockIMMessages
    .filter((mm) => sessionIds.includes(mm.session_id))
    .sort((a, b) => a.id - b.id)
    .map((mm) => ({
      sent_at: mm.sent_at,
      sender_role: mm.sender_role,
      role_label: mm.sender_role === 0 ? '失主' : '拾得者',
      content: mm.content,
    }))
  return ok(ctx.config, { match: m, lost_user: lostUser, found_user: foundUser, conversation })
}

// ---------------- v10-D3：多范围 / 多格式取证导出 ----------------
const _PROFILE_FIELDS = [
  'match_id',
  'lost_item_id', 'lost_category', 'lost_title',
  'lost_student_no', 'lost_phone', 'lost_real_name',
  'found_item_id', 'found_category',
  'found_student_no', 'found_phone', 'found_real_name',
  'match_score', 'status', 'completed_at',
]
const _CONVERSATION_FIELDS = ['match_id', 'sent_at', 'role_label', 'content']

function buildProfileRow(m: MatchOut): Record<string, string> {
  const lost = m.lost_item
  const found = m.found_item
  const lostUser = lost ? mockUsers.find((u) => u.id === lost.publisher_id) : undefined
  const foundUser = found ? mockUsers.find((u) => u.id === found.finder_id) : undefined
  return {
    match_id: String(m.id),
    lost_item_id: lost ? String(lost.id) : '',
    lost_category: lost?.category_name || '',
    lost_title: lost?.title || '',
    lost_student_no: lostUser?.student_no || '',
    lost_phone: lostUser?.phone || '',
    lost_real_name: lostUser?.real_name || '',
    found_item_id: found ? String(found.id) : '',
    found_category: found?.category_name || '',
    found_student_no: foundUser?.student_no || '',
    found_phone: foundUser?.phone || '',
    found_real_name: foundUser?.real_name || '',
    match_score: String(m.match_score),
    status: String(m.status),
    completed_at: m.completed_at || '',
  }
}

function buildConversationRows(m: MatchOut): Record<string, string>[] {
  const sessionIds = mockIMSessions.filter((s) => s.match_id === m.id).map((s) => s.id)
  const msgs = mockIMMessages
    .filter((mm) => sessionIds.includes(mm.session_id))
    .sort((a, b) => a.id - b.id)
  if (!msgs.length) {
    return [{ match_id: String(m.id), sent_at: '', role_label: '', content: '' }]
  }
  return msgs.map((mm) => ({
    match_id: String(m.id),
    sent_at: mm.sent_at || '',
    role_label: mm.sender_role === 0 ? '失主' : '拾得者',
    content: mm.content,
  }))
}

/** Markdown 单元格转义（与后端 `_md_escape` 同口径：`|` 与换行会撑破表格）。 */
function mdCell(v: unknown): string {
  return String(v ?? '').replace(/\|/g, '\\|').replace(/[\n\r]/g, ' ')
}

// 取证导出（与后端 POST /admin/export 一致：合并单文件 blob 下载）。
// v10：支持 scope=profile|conversation|all 与 format=csv|xlsx|md。
// ⚠️ 演示态**不生成真正的 xlsx 二进制**（浏览器侧无 openpyxl 等价物且不引新依赖）：
//    format=xlsx 时降级为「制表符分隔的表格文本」，MIME 仍标 xlsx 以验证下载链路。
function exportMatches(ctx: Ctx): AxiosResponse {
  const b = (ctx.body ?? {}) as { ids?: number[]; scope?: string; format?: string }
  const ids = Array.isArray(b.ids) ? b.ids : []
  const scope = b.scope || 'all'
  const format = b.format || 'csv'
  if (!['profile', 'conversation', 'all'].includes(scope)) {
    return fail(ctx.config, 9001, 'scope 仅支持 profile|conversation|all', 400)
  }
  if (!['csv', 'xlsx', 'md'].includes(format)) {
    return fail(ctx.config, 9001, 'format 仅支持 csv|xlsx|md', 400)
  }
  const matches = mockMatches.filter((m) => ids.includes(m.id))

  const fieldsOf = (sc: string) =>
    sc === 'profile' ? _PROFILE_FIELDS : sc === 'conversation' ? _CONVERSATION_FIELDS : _FORENSIC_FIELDS
  const rowsOf = (sc: string): Record<string, string>[] => {
    if (sc === 'profile') return matches.map(buildProfileRow)
    if (sc === 'conversation') return matches.flatMap(buildConversationRows)
    return matches.map(buildForensicRow)
  }

  let content = ''
  let mime = 'text/csv;charset=utf-8'
  if (format === 'md') {
    const lines: string[] = ['# 失物招领取证导出', '', `- 导出范围：${scope}`, `- 匹配条数：${matches.length}`, '']
    for (const m of matches) {
      lines.push(`## 匹配 #${m.id}`, '')
      if (scope === 'profile' || scope === 'all') {
        const row = buildProfileRow(m)
        lines.push('| 字段 | 值 |', '| --- | --- |')
        for (const f of _PROFILE_FIELDS) lines.push(`| ${mdCell(f)} | ${mdCell(row[f])} |`)
        lines.push('')
      }
      if (scope === 'conversation' || scope === 'all') {
        lines.push('### 对话记录', '')
        const sessionIds = mockIMSessions.filter((s) => s.match_id === m.id).map((s) => s.id)
        const msgs = mockIMMessages
          .filter((mm) => sessionIds.includes(mm.session_id))
          .sort((a, b) => a.id - b.id)
        if (!msgs.length) lines.push('_（无对话）_')
        else
          msgs.forEach((mm, i) => {
            const role = mm.sender_role === 0 ? '失主' : '拾得者'
            lines.push(`${i + 1}. [${mm.sent_at}] ${role}：${mdCell(mm.content)}`)
          })
        lines.push('')
      }
    }
    content = lines.join('\n')
    mime = 'text/markdown;charset=utf-8'
  } else {
    const sep = format === 'xlsx' ? '\t' : ','
    const cell = format === 'xlsx' ? (v: unknown) => String(v ?? '') : csvCell
    const blocks: string[] = []
    const scopes = format === 'xlsx' && scope === 'all' ? ['profile', 'conversation'] : [scope]
    for (const sc of scopes) {
      const fields = fieldsOf(sc)
      const rows = rowsOf(sc)
      if (scopes.length > 1) blocks.push(sc === 'profile' ? '# 个人信息' : '# 对话记录')
      blocks.push(fields.join(sep))
      blocks.push(...rows.map((r) => fields.map((f) => cell(r[f])).join(sep)))
      blocks.push('')
    }
    content = blocks.join('\n')
    mime =
      format === 'xlsx'
        ? 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        : 'text/csv;charset=utf-8'
  }
  const blob = new Blob([content], { type: mime })
  return ok(ctx.config, blob)
}

// 周期清理（演示态无物理库，返回 0 计数，与后端响应体一致）
function triggerCleanup(ctx: Ctx): AxiosResponse {
  return ok(ctx.config, { purged_matches: 0, purged_items: 0 })
}

// ---------------- 路由表 ----------------
interface RouteDef {
  method: string
  re: RegExp
  handler: (ctx: Ctx, m: RegExpMatchArray) => AxiosResponse
}

const ROUTES: RouteDef[] = [
  { method: 'POST', re: /^\/auth\/register$/, handler: (c) => handleRegister(c) },
  { method: 'POST', re: /^\/auth\/login$/, handler: (c) => handleLogin(c) },
  { method: 'POST', re: /^\/auth\/refresh$/, handler: (c) => handleRefresh(c) },
  { method: 'POST', re: /^\/auth\/send-sms$/, handler: (c) => handleSendSms(c) },
  { method: 'POST', re: /^\/auth\/bind-phone$/, handler: (c) => handleBindPhone(c) },
  { method: 'POST', re: /^\/auth\/logout$/, handler: (c) => handleLogout(c) },

  { method: 'POST', re: /^\/lost-items$/, handler: (c) => handleCreateLost(c) },
  { method: 'GET', re: /^\/lost-items$/, handler: (c) => listLost(c) },
  { method: 'GET', re: /^\/lost-items\/(\d+)\/matches$/, handler: (c, m) => matchesForLost(c, Number(m[1])) },
  { method: 'POST', re: /^\/lost-items\/(\d+)\/refresh-matches$/, handler: (c, m) => handleRefreshMatches(c, Number(m[1])) },
  { method: 'GET', re: /^\/lost-items\/(\d+)$/, handler: (c, m) => getLost(c, Number(m[1])) },
  { method: 'DELETE', re: /^\/lost-items\/(\d+)$/, handler: (c, m) => deleteLost(c, Number(m[1])) },

  { method: 'POST', re: /^\/found-items$/, handler: (c) => handleCreateFound(c) },
  { method: 'GET', re: /^\/found-items$/, handler: (c) => listFound(c) },
  { method: 'GET', re: /^\/found-items\/(\d+)$/, handler: (c, m) => getFound(c, Number(m[1])) },
  { method: 'DELETE', re: /^\/found-items\/(\d+)$/, handler: (c, m) => deleteFound(c, Number(m[1])) },

  { method: 'GET', re: /^\/matches$/, handler: (c) => myMatches(c) },
  { method: 'POST', re: /^\/matches\/manual$/, handler: (c) => createManualMatch(c) },
  { method: 'POST', re: /^\/matches\/(\d+)\/claim$/, handler: (c, m) => claimMatch(c, Number(m[1])) },
  { method: 'POST', re: /^\/matches\/(\d+)\/claim-complete$/, handler: (c, m) => claimCompleteMatch(c, Number(m[1])) },
  { method: 'POST', re: /^\/matches\/(\d+)\/revoke$/, handler: (c, m) => revokeMatch(c, Number(m[1])) },
  { method: 'POST', re: /^\/matches\/(\d+)\/confirm-return$/, handler: (c, m) => confirmReturn(c, Number(m[1])) },
  { method: 'POST', re: /^\/matches\/(\d+)\/handover\/generate$/, handler: (c, m) => handoverGenerate(c, Number(m[1])) },
  { method: 'POST', re: /^\/matches\/(\d+)\/handover\/verify$/, handler: (c, m) => handoverVerify(c, Number(m[1])) },
  { method: 'POST', re: /^\/matches\/(\d+)\/self-complete$/, handler: (c, m) => selfCompleteMatch(c, Number(m[1])) },
  { method: 'POST', re: /^\/matches\/(\d+)\/reject$/, handler: (c, m) => rejectMatch(c, Number(m[1])) },
  { method: 'POST', re: /^\/matches\/(\d+)\/giveup$/, handler: (c, m) => giveupMatch(c, Number(m[1])) },

  { method: 'GET', re: /^\/audit-logs$/, handler: (c) => auditLogs(c) },

  { method: 'GET', re: /^\/users\/me\/items$/, handler: (c) => myItems(c) },
  { method: 'POST', re: /^\/im\/sessions$/, handler: (c) => handleCreateSession(c) },
  { method: 'GET', re: /^\/im\/sessions$/, handler: (c) => listMySessions(c) },
  { method: 'DELETE', re: /^\/im\/sessions\/(\d+)$/, handler: (c, m) => deleteSession(c, Number(m[1])) },
  { method: 'POST', re: /^\/im\/sessions\/(\d+)\/success$/, handler: (c, m) => successSession(c, Number(m[1])) },
  { method: 'GET', re: /^\/im\/sessions\/(\d+)\/messages$/, handler: (c, m) => handleGetMessages(c, Number(m[1])) },
  { method: 'POST', re: /^\/im\/sessions\/(\d+)\/messages$/, handler: (c, m) => handleSendMessage(c, Number(m[1])) },

  { method: 'POST', re: /^\/vision\/predict$/, handler: (c) => handleVisionPredict(c) },
  { method: 'GET', re: /^\/admin\/audit-logs\/export$/, handler: (c) => handleExportAudit(c) },

  // v7：管理后台——未失效匹配列表 / 取证导出 / 周期清理
  { method: 'GET', re: /^\/admin\/users$/, handler: (c) => listAdminUsers(c) },
  // ⚠️ detail 路由必须排在 /admin/matches 之前，否则会被前者的正则先匹配掉
  { method: 'GET', re: /^\/admin\/matches\/(\d+)\/detail$/, handler: (c, m) => getAdminMatchDetail(c, Number(m[1])) },
  { method: 'GET', re: /^\/admin\/matches$/, handler: (c) => listAdminMatches(c) },
  { method: 'POST', re: /^\/admin\/export$/, handler: (c) => exportMatches(c) },
  { method: 'POST', re: /^\/admin\/cleanup$/, handler: (c) => triggerCleanup(c) },
]

// ---------------- 适配器实现 ----------------
export const mockAdapter: AxiosAdapter = (config: InternalAxiosRequestConfig) => {
  return new Promise<AxiosResponse>((resolve) => {
    const base = (config.baseURL || '').replace(/\/$/, '')
    const raw = config.url || ''
    const full = /^https?:\/\//i.test(raw) ? raw : base + (raw.startsWith('/') ? raw : '/' + raw)
    let pathname = full
    try {
      pathname = new URL(full, 'http://mock.local').pathname
    } catch {
      pathname = full
    }
    // 去掉可能的前缀 /api/v1，统一按资源路径匹配
    const resource = pathname.replace(/^\/api\/v1/, '')
    const method = (config.method || 'get').toUpperCase()
    const url = new URL(full, 'http://mock.local')
    const ctx: Ctx = { config, body: parseBody(config), params: url.searchParams }

    // 受保护路由鉴权
    const isProtected = !/^\/auth\/(login|register|refresh|send-sms)$/.test(resource)
    if (isProtected && !requireAuth(config)) {
      resolve(fail(config, 1000, '未认证或令牌缺失', 401))
      return
    }

    for (const r of ROUTES) {
      if (r.method !== method) continue
      const m = resource.match(r.re)
      if (m) {
        resolve(r.handler(ctx, m))
        return
      }
    }
    resolve(fail(config, 404, `演示模式未实现该接口: ${method} ${resource}`, 404))
  })
}

// 标记当前演示用户 id，供页面判断“我”在匹配中的角色
export const MOCK_ME = MOCK_CURRENT_USER_ID
export type { UserOut }
