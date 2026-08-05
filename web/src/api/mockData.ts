// 演示用静态样本数据：严格对齐后端各 Pydantic Schema 字段，
// 使得“演示模式”下每个页面都能渲染与真实后端一致的结构。
//
// v3 增量：失物/拾物移除 lost_location/found_location（地点语义并入 description），
// 新增 tags（结构化标签数组）与 image_hash（16-hex 感知哈希）；新增 IM 会话/消息样本。
// v8 增量：失物/拾物补齐 appearance/features/location 三列示例值。
// flow-v2（2026-08-05）增量：匹配维度改为五维
//   photo/category/text/location/time（权重 15/20/50/10/5），appearance/feature 保留 0 占位；
//   匹配补 flow_type（0=双向交接 / 1=keep1 单边）、text/text_match_rate/shared_text；
//   新增 keep1 完成样本（match 10，flow_type=1，可撤回）与撤回灰显样本（match 11，status=6）。

import type {
  AuditLog,
  FoundItemOut,
  IMMessageOut,
  IMSessionOut,
  LostItemOut,
  MatchOut,
  Token,
  UserOut,
} from '@/types'

// ---------------- 工具 ----------------
function daysAgo(n: number, hour = 10, minute = 0): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  d.setHours(hour, minute, 0, 0)
  return d.toISOString()
}

// 由种子生成确定性的 16-hex 感知哈希（演示用，模拟 pHash）
function hex16(n: number): string {
  return n.toString(16).padStart(16, '0').slice(0, 16)
}

const PALETTE = ['#2f6fed', '#16a34a', '#f59e0b', '#ef4444', '#8b5cf6', '#0ea5e9']

/** 生成离线可渲染的 SVG 占位图（data URI），保证无后端时图片也能显示 */
export function phImage(label: string, idx = 0): string {
  const bg = PALETTE[idx % PALETTE.length]
  const svg =
    `<svg xmlns='http://www.w3.org/2000/svg' width='320' height='220'>` +
    `<rect width='100%' height='100%' fill='${bg}'/>` +
    `<text x='50%' y='50%' fill='#ffffff' font-size='22' font-family='sans-serif' ` +
    `text-anchor='middle' dominant-baseline='middle'>${label}</text></svg>`
  return 'data:image/svg+xml;utf8,' + encodeURIComponent(svg)
}

// ---------------- 演示身份（v7：管理员入口切换，Q7） ----------------
const DEMO_ROLE_KEY = 'lf_demo_role'

function readStoredRole(): number {
  try {
    const v = localStorage.getItem(DEMO_ROLE_KEY)
    return v === '1' ? 1 : 0
  } catch {
    return 0
  }
}

/** 当前演示身份：0 普通用户 / 1 管理员（默认 0，需求 A：演示态以管理员进入）。 */
export let currentMockRole: number = readStoredRole()

/** 在给定 ISO 时间基础上加 n 天（用于 expires_at = created_at + 90d）。 */
function daysLaterIso(iso: string, n: number): string {
  const d = new Date(iso)
  d.setDate(d.getDate() + n)
  return d.toISOString()
}

/** 切换演示身份（0 普通 / 1 管理员），持久化并同步当前用户 role。 */
export function setMockRole(role: number): void {
  currentMockRole = role === 1 ? 1 : 0
  mockCurrentUser.role = currentMockRole
  try {
    localStorage.setItem(DEMO_ROLE_KEY, currentMockRole ? '1' : '0')
  } catch {
    /* ignore */
  }
}

// ---------------- 当前演示用户（模拟已登录） ----------------
export const MOCK_CURRENT_USER_ID = 1

export const mockCurrentUser: UserOut = {
  id: MOCK_CURRENT_USER_ID,
  student_no: '2021110101',
  phone: '138****8001',
  real_name: '张同学',
  role: 0,
  credit_score: 100,
  status: 0,
  created_at: daysAgo(60),
}

// 当前用户身份跟随 currentMockRole（演示态管理员入口）
mockCurrentUser.role = currentMockRole

export const mockAdminUser: UserOut = {
  id: 99,
  student_no: 'admin',
  phone: '139****0000',
  real_name: '系统管理员',
  role: 1,
  credit_score: 100,
  status: 0,
  created_at: daysAgo(120),
}

let tokenSeq = 1
export function makeMockToken(): Token {
  const t = `mock.token.${tokenSeq++}.${Date.now()}`
  return {
    access_token: t,
    refresh_token: t + '.refresh',
    token_type: 'bearer',
    expires_in: 120 * 60,
  }
}

// ---------------- 失物 ----------------
export const mockLostItems: LostItemOut[] = [
  {
    id: 1,
    publisher_id: 1,
    category_id: 6,
    category_name: '手机',
    title: '黑色 iPhone 13 一部',
    description: '在图书馆三楼自习区遗失，手机壳为蓝色硅胶。屏幕无明显划痕，锁屏壁纸为雪山。',
    images: [phImage('手机', 0)],
    color: '黑色',
    tags: ['黑色', '手机', 'iPhone', '图书馆'],
    image_hash: hex16(101),
    // v8：外观 / 特征 / 地点
    appearance: '黑色直板机身，配蓝色硅胶保护壳，屏幕无明显划痕',
    features: '锁屏壁纸为雪山风景，背面摄像头无破损，IMEI 尾号 8821',
    location: '图书馆三楼自习区 A 区',
    lost_time: daysAgo(2, 15),
    status: 1,
    created_at: daysAgo(2, 16),
  },
  {
    id: 2,
    publisher_id: 1,
    category_id: 5,
    category_name: '水杯',
    title: '白色膳魔师保温杯',
    description: '体育馆更衣室遗失，杯身贴有蓝色姓名贴，底部有磕痕。',
    images: [phImage('水杯', 1)],
    color: '白色',
    tags: ['白色', '水杯', '体育馆'],
    image_hash: hex16(202),
    // v8：外观 / 特征 / 地点
    appearance: '白色磨砂保温杯，高约 22cm',
    features: '杯身贴有蓝色姓名贴，底部有一处磕痕',
    location: '体育馆更衣室',
    lost_time: daysAgo(3, 9),
    status: 0,
    created_at: daysAgo(3, 10),
  },
  {
    id: 3,
    publisher_id: 1,
    category_id: 10,
    category_name: '校园卡',
    title: '校园一卡通（遗失）',
    description: '食堂门口掉落，卡面有轻微磨损，姓名李某某。',
    images: [phImage('校园卡', 3)],
    color: null,
    tags: ['校园卡', '食堂'],
    image_hash: hex16(303),
    // v8：外观 / 特征 / 地点
    appearance: '蓝色校园一卡通，卡面有轻微磨损',
    features: '姓名李某某，学号 2021110xxx',
    location: '第一食堂门口',
    lost_time: daysAgo(1, 12),
    status: 2,
    created_at: daysAgo(1, 13),
  },
  {
    id: 4,
    publisher_id: 7,
    category_id: 11,
    category_name: '钥匙',
    title: '一串钥匙（含门禁卡）',
    description: '教学楼A区楼梯间遗失，红色钥匙扣，共5把钥匙。',
    images: [phImage('钥匙', 5)],
    color: '红色',
    tags: ['钥匙', '红色', '教学楼'],
    image_hash: hex16(404),
    // v8：外观 / 特征 / 地点
    appearance: '红色钥匙扣，共 5 把钥匙',
    features: '含一张门禁卡，钥匙齿纹清晰',
    location: '教学楼 A 区楼梯间',
    lost_time: daysAgo(4, 18),
    status: 0,
    created_at: daysAgo(4, 19),
  },
  {
    id: 5,
    publisher_id: 7,
    category_id: 8,
    category_name: '书籍',
    title: '《高等数学》第七版',
    description: '封面写有“计科2101”，内页有笔记。',
    images: [phImage('书籍', 2)],
    color: null,
    tags: ['书籍', '高等数学'],
    image_hash: hex16(505),
    // v8：外观 / 特征 / 地点
    appearance: '蓝色封面教材，边角略卷',
    features: '封面写有“计科2101”，内页有蓝色钢笔笔记',
    location: '逸夫楼自习室',
    lost_time: daysAgo(5, 14),
    status: 3,
    created_at: daysAgo(5, 15),
  },
  {
    id: 6,
    publisher_id: 7,
    category_id: 1,
    category_name: '书包',
    title: '黑色双肩背包',
    description: '操场看台遗失，内有课本若干。',
    images: [phImage('书包', 0)],
    color: '黑色',
    tags: ['黑色', '书包', '操场'],
    image_hash: hex16(606),
    // v8：外观 / 特征 / 地点
    appearance: '黑色双肩背包，约 40cm 高',
    features: '主仓拉链完好，侧袋有磨损',
    location: '操场看台第三排',
    lost_time: daysAgo(6, 17),
    status: 1,
    created_at: daysAgo(6, 18),
  },
  {
    id: 7,
    publisher_id: 1,
    category_id: 4,
    category_name: '雨伞',
    title: '黑色长柄雨伞（已找回示例）',
    description: '教学楼走廊遗失的黑色长柄雨伞，后由同学捡到并交接完成。',
    images: [phImage('雨伞', 4)],
    color: '黑色',
    tags: ['黑色', '雨伞', '教学楼'],
    image_hash: hex16(707),
    // v8：外观 / 特征 / 地点
    appearance: '黑色长柄雨伞，伞面有细纹',
    features: '木质手柄，伞骨无变形',
    location: '教学楼二楼走廊',
    lost_time: daysAgo(8, 9),
    status: 3, // 已解决（v6 演示：已完成交接）
    created_at: daysAgo(8, 10),
  },
  {
    // 2026-08-05 增量：拾得者侧低分候选样本——「书籍·大学英语」（发布者 7）与 found 5（拾得者=当前用户 1）
    id: 8,
    publisher_id: 7,
    category_id: 8,
    category_name: '书籍',
    title: '《大学英语》第四册',
    description: '逸夫楼自习室遗失的大学英语教材，封面写有姓名。',
    images: [phImage('书籍', 2)],
    color: null,
    tags: ['书籍', '大学英语', '逸夫楼'],
    image_hash: hex16(888),
    // v8：外观 / 特征 / 地点
    appearance: '蓝色封面教材，书脊有磨损',
    features: '封面写有姓名，扉页有课堂笔记',
    location: '逸夫楼自习室',
    lost_time: daysAgo(1, 15),
    status: 0,
    created_at: daysAgo(1, 16),
  },
  {
    // 2026-08-05 flow-v2 增量：keep1 演示失物（发布者=当前用户 1）——复现 PRD §5.2 行李箱可测断言
    id: 9,
    publisher_id: 1,
    category_id: 5,
    category_name: '行李箱',
    title: '两个行李箱',
    description: '黄色和粉色，在教学楼看见',
    images: [phImage('行李箱', 1)],
    color: null,
    tags: ['黄色', '粉色', '教学楼'],
    image_hash: hex16(909),
    // v8：外观 / 特征 / 地点
    appearance: '黄色和粉色两个行李箱',
    features: null,
    location: '教学楼',
    lost_time: daysAgo(0, 8),
    status: 3, // keep1 申请即完成后已解决（演示：可撤回）
    created_at: daysAgo(0, 9),
  },
  {
    // 2026-08-05 flow-v2 增量：撤回灰显演示失物（发布者=当前用户 1）
    id: 10,
    publisher_id: 1,
    category_id: 5,
    category_name: '行李箱',
    title: '蓝色行李箱',
    description: '食堂门口遗失蓝色行李箱，拉杆有贴纸',
    images: [phImage('行李箱', 3)],
    color: '蓝色',
    tags: ['蓝色', '行李箱', '食堂'],
    image_hash: hex16(1010),
    appearance: '蓝色行李箱，拉杆有贴纸',
    features: null,
    location: '食堂门口',
    lost_time: daysAgo(3, 8),
    status: 0,
    created_at: daysAgo(3, 9),
  },
]

// ---------------- 拾物 ----------------
export const mockFoundItems: FoundItemOut[] = [
  {
    id: 1,
    finder_id: 2,
    category_id: 6,
    category_name: '手机',
    description: '在图书馆三楼捡到一部黑色 iPhone，已代为保管。',
    images: [phImage('手机', 0)],
    tags: ['黑色', '手机', 'iPhone', '图书馆'],
    image_hash: hex16(101),
    // v8：外观 / 特征 / 地点
    appearance: '黑色 iPhone，蓝色硅胶保护壳',
    features: '锁屏壁纸为雪山，背面摄像头无划痕',
    location: '图书馆三楼',
    found_time: daysAgo(2, 16),
    keep_status: 0,
    contact_allowed: 1,
    status: 0,
    created_at: daysAgo(2, 17),
  },
  {
    id: 2,
    finder_id: 2,
    category_id: 5,
    category_name: '水杯',
    description: '体育馆捡到白色保温杯，暂存失物招领处。',
    images: [phImage('水杯', 1)],
    tags: ['白色', '水杯', '体育馆'],
    image_hash: hex16(202),
    // v8：外观 / 特征 / 地点
    appearance: '白色保温杯',
    features: '贴有蓝色姓名贴，底部有磕痕',
    location: '体育馆失物招领处',
    found_time: daysAgo(3, 11),
    keep_status: 0,
    contact_allowed: 1,
    status: 0,
    created_at: daysAgo(3, 12),
  },
  {
    id: 3,
    finder_id: 2,
    category_id: 10,
    category_name: '校园卡',
    description: '食堂门口捡到校园卡一张。',
    images: [phImage('校园卡', 3)],
    tags: ['校园卡', '食堂'],
    image_hash: hex16(303),
    // v8：外观 / 特征 / 地点
    appearance: '蓝色校园一卡通',
    features: '姓名李某某',
    location: '第一食堂门口',
    found_time: daysAgo(1, 13),
    keep_status: 1,
    contact_allowed: 1,
    status: 0,
    created_at: daysAgo(1, 14),
  },
  {
    id: 4,
    finder_id: 8,
    category_id: 11,
    category_name: '钥匙',
    description: '教学楼捡到一串钥匙。',
    images: [phImage('钥匙', 5)],
    tags: ['钥匙', '红色', '教学楼'],
    image_hash: hex16(404),
    // v8：外观 / 特征 / 地点
    appearance: '红色钥匙扣',
    features: '含一张门禁卡，共 5 把钥匙',
    location: '教学楼 A 区',
    found_time: daysAgo(4, 19),
    keep_status: 0,
    contact_allowed: 0,
    status: 0,
    created_at: daysAgo(4, 20),
  },
  {
    id: 5,
    finder_id: 1,
    category_id: 8,
    category_name: '书籍',
    description: '自习室捡到《高等数学》，内页有笔记。',
    images: [phImage('书籍', 2)],
    tags: ['书籍', '高等数学'],
    image_hash: hex16(505),
    // v8：外观 / 特征 / 地点
    appearance: '蓝色封面《高等数学》',
    features: '封面写有“计科2101”，内页有笔记',
    location: '逸夫楼自习室',
    found_time: daysAgo(5, 16),
    keep_status: 1,
    contact_allowed: 1,
    status: 0,
    created_at: daysAgo(5, 17),
  },
  {
    id: 6,
    finder_id: 8,
    category_id: 1,
    category_name: '书包',
    description: '操场看台捡到黑色双肩包。',
    images: [phImage('书包', 0)],
    tags: ['黑色', '书包', '操场'],
    image_hash: hex16(606),
    // v8：外观 / 特征 / 地点
    appearance: '黑色双肩背包',
    features: '侧袋有磨损',
    location: '操场看台',
    found_time: daysAgo(6, 18),
    keep_status: 0,
    contact_allowed: 1,
    status: 0,
    created_at: daysAgo(6, 19),
  },
  {
    id: 7,
    finder_id: 8,
    category_id: 4,
    category_name: '雨伞',
    description: '教学楼捡到黑色长柄雨伞，已交还给失主（v6 演示：已完成交接）。',
    images: [phImage('雨伞', 4)],
    tags: ['黑色', '雨伞', '教学楼'],
    image_hash: hex16(707),
    // v8：外观 / 特征 / 地点
    appearance: '黑色长柄雨伞',
    features: '木质手柄，伞骨完好',
    location: '教学楼二楼走廊',
    found_time: daysAgo(8, 11),
    keep_status: 0,
    contact_allowed: 1,
    status: 1, // 已解决（v6 演示：已完成交接）
    created_at: daysAgo(8, 12),
  },
  {
    // 2026-08-05 增量：低分候选样本（失主侧）——同「水杯」类目但外观差异大
    id: 8,
    finder_id: 8,
    category_id: 5,
    category_name: '水杯',
    description: '操场看台捡到一只黑色塑料水杯，非保温杯，杯身无贴纸。',
    images: [phImage('水杯', 6)],
    tags: ['黑色', '水杯', '操场'],
    image_hash: hex16(808),
    // v8：外观 / 特征 / 地点
    appearance: '黑色塑料水杯，无贴纸',
    features: '杯身无刻字',
    location: '操场看台',
    found_time: daysAgo(1, 17),
    keep_status: 1,
    contact_allowed: 1,
    status: 0,
    created_at: daysAgo(1, 18),
  },
  {
    // 2026-08-05 flow-v2 增量：keep1 演示拾物（拾得者 8，留在原地未挪动）——失物 9 的匹配对端
    id: 9,
    finder_id: 8,
    category_id: 5,
    category_name: '行李箱',
    description: '行李箱两个，黄色的和粉色，在教学楼',
    images: [phImage('行李箱', 1)],
    tags: ['黄色', '粉色', '教学楼', '行李箱'],
    image_hash: hex16(909),
    appearance: '黄色和粉色两个行李箱',
    features: null,
    location: '教学楼',
    found_time: daysAgo(0, 10),
    keep_status: 1, // R2：留在原地未挪动 → 申请即完成 / 可撤回
    contact_allowed: 1,
    status: 1, // keep1 申请即完成后已解决（演示撤回入口）
    created_at: daysAgo(0, 11),
  },
  {
    // 2026-08-05 flow-v2 增量：撤回灰显演示拾物（拾得者 8，keep1）
    id: 10,
    finder_id: 8,
    category_id: 5,
    category_name: '行李箱',
    description: '食堂门口蓝色行李箱，没有挪动',
    images: [phImage('行李箱', 3)],
    tags: ['蓝色', '行李箱', '食堂'],
    image_hash: hex16(1010),
    appearance: '蓝色行李箱',
    features: null,
    location: '食堂门口',
    found_time: daysAgo(3, 10),
    keep_status: 1,
    contact_allowed: 1,
    status: 0, // 撤回后恢复待认领
    created_at: daysAgo(3, 11),
  },
]

// ---------------- 匹配（含 counter-part 物品，按 score 降序） ----------------
export const mockMatches: MatchOut[] = [
  {
    id: 1,
    lost_id: 1,
    found_id: 1,
    match_score: 94.5,
    status: 1, // 认领中（已生成交接码）
    claim_reason: '手机壳为蓝色硅胶，锁屏壁纸是雪山，IMEI 尾号 8821。',
    created_at: daysAgo(2, 17),
    lost_item: mockLostItems[0],
    found_item: mockFoundItems[0],
    suspected: true,
    flow_type: 0, // 双向交接（keep0）
    // flow-v2 五维明细（图像15/类别20/文字50/地点10/时间5，总分=加权和）
    photo: 14,
    category: 20,
    text: 46,
    text_match_rate: 0.92,
    appearance: 0,
    feature: 0,
    time: 5,
    location: 10,
    shared_text: ['黑色', '手机', '图书馆'],
    total: 95,
  },
  {
    id: 2,
    lost_id: 2,
    found_id: 2,
    match_score: 91.0,
    status: 0, // 待认领
    claim_reason: null,
    created_at: daysAgo(3, 12),
    lost_item: mockLostItems[1],
    found_item: mockFoundItems[1],
    suspected: true,
    flow_type: 0,
    // flow-v2 五维明细
    photo: 14,
    category: 19,
    text: 44,
    text_match_rate: 0.88,
    appearance: 0,
    feature: 0,
    time: 5,
    location: 9,
    shared_text: ['白色', '水杯', '体育馆'],
    total: 91,
  },
  {
    id: 3,
    lost_id: 3,
    found_id: 3,
    match_score: 96.0,
    status: 2, // 已完成
    claim_reason: '卡面姓名李某某，学号 2021110xxx。',
    created_at: daysAgo(1, 14),
    lost_item: mockLostItems[2],
    found_item: mockFoundItems[2],
    suspected: true,
    flow_type: 0,
    // flow-v2 五维明细
    photo: 14,
    category: 20,
    text: 47,
    text_match_rate: 0.94,
    appearance: 0,
    feature: 0,
    time: 5,
    location: 10,
    shared_text: ['校园卡', '食堂'],
    total: 96,
  },
  {
    id: 4,
    lost_id: 5,
    found_id: 5,
    match_score: 88.0,
    status: 0, // 待认领（我作为拾得者，可确认归还/拒绝）
    claim_reason: null,
    created_at: daysAgo(5, 17),
    lost_item: mockLostItems[4],
    found_item: mockFoundItems[4],
    suspected: true,
    flow_type: 0,
    // flow-v2 五维明细
    photo: 13,
    category: 18,
    text: 43,
    text_match_rate: 0.86,
    appearance: 0,
    feature: 0,
    time: 5,
    location: 9,
    shared_text: ['书籍', '高等数学'],
    total: 88,
  },
  {
    id: 5,
    lost_id: 6,
    found_id: 6,
    match_score: 83.0,
    status: 3, // 已拒绝
    claim_reason: null,
    created_at: daysAgo(6, 19),
    lost_item: mockLostItems[5],
    found_item: mockFoundItems[5],
    suspected: true,
    flow_type: 0,
    // flow-v2 五维明细
    photo: 12,
    category: 17,
    text: 41,
    text_match_rate: 0.82,
    appearance: 0,
    feature: 0,
    time: 5,
    location: 8,
    shared_text: ['书包', '黑色'],
    total: 83,
  },
  {
    // v4：未挪动自取（手动申请匹配）示例，status=4 待自取
    id: 6,
    lost_id: 2,
    found_id: 2,
    match_score: 79.0,
    status: 4, // 待自取（失主可单边完成）
    claim_reason: null,
    created_at: daysAgo(1, 8),
    lost_item: mockLostItems[1],
    found_item: mockFoundItems[1],
    suspected: false,
    flow_type: 0,
    // flow-v2 五维明细
    photo: 12,
    category: 16,
    text: 39,
    text_match_rate: 0.78,
    appearance: 0,
    feature: 0,
    time: 5,
    location: 7,
    shared_text: ['水杯', '白色'],
    total: 79,
  },
  {
    // v6：已完成交接演示配对（status=2 COMPLETED），关联一对已解决物品
    id: 7,
    lost_id: 7,
    found_id: 7,
    match_score: 90.5,
    status: 2, // 已完成
    claim_reason: '黑色长柄雨伞，教学楼走廊遗失，由同学捡到并交接完成。',
    created_at: daysAgo(7, 15),
    lost_item: mockLostItems[6],
    found_item: mockFoundItems[6],
    suspected: true,
    flow_type: 0,
    // flow-v2 五维明细
    photo: 14,
    category: 19,
    text: 44,
    text_match_rate: 0.88,
    appearance: 0,
    feature: 0,
    time: 5,
    location: 9,
    shared_text: ['黑色', '雨伞', '教学楼'],
    total: 91,
  },
  {
    // 2026-08-05 增量：失主侧低分候选（suspected=false，Q1/P0-4 演示）
    // lost 2（白色保温杯，发布者=当前用户 1）↔ found 8（黑色塑料杯，同「水杯」类目但外观差异大）
    id: 8,
    lost_id: 2,
    found_id: 8,
    match_score: 58.0,
    status: 0, // 待认领（失主侧：低分「申请匹配」需二次确认）
    claim_reason: null,
    created_at: daysAgo(1, 19),
    lost_item: mockLostItems[1],
    found_item: mockFoundItems[7],
    suspected: false,
    flow_type: 0,
    // flow-v2 五维明细（按比例，总分与 match_score 对齐）
    photo: 9,
    category: 12,
    text: 28,
    text_match_rate: 0.56,
    appearance: 0,
    feature: 0,
    time: 4,
    location: 5,
    shared_text: ['水杯'],
    total: 58,
  },
  {
    // flow-v3：低分（<60）演示候选 —— 失主侧弱化标签/虚线卡片 + 低分二次确认；
    // 拾得者侧「低分不打扰」已删除，keep0 候选无论分数一律显示「确认归还 / 拒绝」。
    // lost 8（《大学英语》第四册，发布者 7）↔ found 5（书籍，拾得者=当前用户 1）
    id: 9,
    lost_id: 8,
    found_id: 5,
    match_score: 55.0,
    status: 0, // 待认领（keep0 低分：拾得者侧仍显示「确认归还 / 拒绝」）
    claim_reason: null,
    created_at: daysAgo(1, 17),
    lost_item: mockLostItems[7],
    found_item: mockFoundItems[4],
    suspected: false,
    flow_type: 0,
    // flow-v2 五维明细（按比例，总分与 match_score 对齐）
    photo: 8,
    category: 11,
    text: 27,
    text_match_rate: 0.54,
    appearance: 0,
    feature: 0,
    time: 4,
    location: 5,
    shared_text: ['书籍'],
    total: 55,
  },
  {
    // 2026-08-05 flow-v2 增量：keep1「申请即完成」演示——lost 9 ↔ found 9（lost 9 发布者=当前用户 1）
    // 复现 PRD §5.2 行李箱场景：失物词集 5 词，拾物命中 4/5 → text 40 分档。
    id: 10,
    lost_id: 9,
    found_id: 9,
    match_score: 82.5,
    status: 2, // 已完成（keep1 申请即完成，终态）
    claim_reason: null,
    created_at: daysAgo(0, 9),
    lost_item: mockLostItems[8],
    found_item: mockFoundItems[8],
    suspected: true,
    flow_type: 1, // keep1 单边（申请即完成）→ 演示撤回入口
    // flow-v2 五维明细：text 40 分档（命中 4/5）
    photo: 15,
    category: 20,
    text: 40,
    text_match_rate: 0.8,
    appearance: 0,
    feature: 0,
    time: 2.5,
    location: 5,
    shared_text: ['两个', '行李箱', '黄色', '粉色'],
    total: 82.5,
  },
  {
    // 2026-08-05 flow-v2 增量：撤回灰显演示——lost 10 ↔ found 10（keep1 完成记录已撤回，status=6 终态）
    id: 11,
    lost_id: 10,
    found_id: 10,
    match_score: 78.0,
    status: 6, // 已撤回（keep1 完成记录撤回后的终态，Q7 拍板）
    claim_reason: null,
    created_at: daysAgo(3, 11),
    lost_item: mockLostItems[9],
    found_item: mockFoundItems[9],
    suspected: false,
    flow_type: 1, // keep1 单边（撤回后灰显「已撤回」）
    photo: 12,
    category: 16,
    text: 38,
    text_match_rate: 0.76,
    appearance: 0,
    feature: 0,
    time: 5,
    location: 7,
    shared_text: ['蓝色', '行李箱', '食堂'],
    total: 78,
  },
]

// v7：为演示数据补齐生命周期字段，与后端 0004 迁移/模型默认一致：
//  - 失物/拾物 expires_at = created_at + 90d；deleted_at 默认 null（软删标记）
//  - 已完成（status=2）匹配补齐 completed_at = created_at
for (const it of mockLostItems) {
  if (it.expires_at == null) it.expires_at = daysLaterIso(it.created_at, 90)
  it.deleted_at = it.deleted_at ?? null
}
for (const it of mockFoundItems) {
  if (it.expires_at == null) it.expires_at = daysLaterIso(it.created_at, 90)
  it.deleted_at = it.deleted_at ?? null
}
for (const m of mockMatches) {
  // flow-v2：keep1 完成（status=2）与撤回（status=6）记录均保留 completed_at（撤回保留原完成时间）
  if ((m.status === 2 || m.status === 6) && m.completed_at == null) m.completed_at = m.created_at
}

// ---------------- 用户（会话对方摘要源，v5「我的消息」） ----------------
export const mockUsers: UserOut[] = [
  mockCurrentUser, // id 1（当前演示用户）
  {
    id: 2,
    student_no: '2021110102',
    phone: '138****8002',
    real_name: '李同学',
    role: 0,
    credit_score: 100,
    status: 0,
    created_at: daysAgo(60),
  },
  {
    id: 7,
    student_no: '2021110107',
    phone: '138****8007',
    real_name: '王同学',
    role: 0,
    credit_score: 100,
    status: 0,
    created_at: daysAgo(60),
  },
  {
    id: 8,
    student_no: '2021110108',
    phone: '138****8008',
    real_name: '赵同学',
    role: 0,
    credit_score: 100,
    status: 0,
    created_at: daysAgo(60),
  },
]

// ---------------- IM 会话 / 消息（v3 需求 D，演示态可变） ----------------
// v5：预置若干「我的消息」样本（含 match_id 与 found_id 两类），供演示闭环。
const IM_RETENTION_MS = 30 * 24 * 3600 * 1000

export const mockIMSessions: IMSessionOut[] = [
  {
    id: 1,
    match_id: 1, // 失主视角（我=失主，对方=拾得者 李同学），物品=手机
    found_id: null,
    lost_user_id: 1,
    finder_user_id: 2,
    status: 0,
    created_at: daysAgo(1, 10),
    last_message_at: daysAgo(0, 9, 12),
    expires_at: new Date(Date.now() + IM_RETENTION_MS).toISOString(),
  },
  {
    id: 2,
    match_id: null,
    found_id: 3, // 无 match 联系（我=失主联系拾得者），物品=校园卡
    lost_user_id: 1,
    finder_user_id: 2,
    status: 0,
    created_at: daysAgo(2, 10),
    last_message_at: daysAgo(1, 14),
    expires_at: new Date(Date.now() + IM_RETENTION_MS).toISOString(),
  },
  {
    id: 3,
    match_id: 4, // 拾得者视角（我=拾得者，对方=失主 王同学），物品=书籍
    found_id: null,
    lost_user_id: 7,
    finder_user_id: 1,
    status: 0,
    created_at: daysAgo(5, 17),
    last_message_at: daysAgo(3, 16),
    expires_at: new Date(Date.now() + IM_RETENTION_MS).toISOString(),
  },
]

export const mockIMMessages: IMMessageOut[] = [
  {
    id: 1,
    session_id: 1,
    sender_id: 1,
    sender_role: 0,
    content_type: 0,
    content: '对的没动过',
    sent_at: daysAgo(0, 9, 10),
  },
  {
    id: 2,
    session_id: 1,
    sender_id: 2,
    sender_role: 1,
    content_type: 0,
    content: '好的我来取',
    sent_at: daysAgo(0, 9, 12),
  },
  {
    id: 3,
    session_id: 2,
    sender_id: 1,
    sender_role: 0,
    content_type: 0,
    content: '你好，这张校园卡是你捡到的吗？',
    sent_at: daysAgo(1, 14),
  },
  {
    id: 4,
    session_id: 3,
    sender_id: 7,
    sender_role: 0,
    content_type: 0,
    content: '请问《高等数学》还在吗？',
    sent_at: daysAgo(3, 16),
  },
]

// ---------------- 审计日志（管理后台） ----------------
export const mockAuditLogs: AuditLog[] = [
  {
    id: 1,
    user_id: 1,
    action: 'publish_lost',
    target_type: 'lost',
    target_id: 1,
    ip: '10.12.3.21',
    ua: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)',
    gps: null,
    detail: 'title=黑色 iPhone 13 一部;category_id=6',
    created_at: daysAgo(2, 16),
  },
  {
    id: 2,
    user_id: 2,
    action: 'publish_found',
    target_type: 'found',
    target_id: 1,
    ip: '10.12.3.22',
    ua: 'Mozilla/5.0 (Linux; Android 14)',
    gps: '30.64,104.07',
    detail: 'keep_status=0;category_id=6',
    created_at: daysAgo(2, 17),
  },
  {
    id: 3,
    user_id: 1,
    action: 'claim',
    target_type: 'match',
    target_id: 1,
    ip: '10.12.3.21',
    ua: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)',
    gps: null,
    detail: '手机壳为蓝色硅胶，锁屏壁纸是雪山，IMEI 尾号 8821。',
    created_at: daysAgo(2, 18),
  },
  {
    id: 4,
    user_id: 1,
    action: 'handover_generate',
    target_type: 'match',
    target_id: 1,
    ip: '10.12.3.21',
    ua: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)',
    gps: null,
    detail: 'seq=1;code=A1B2C3',
    created_at: daysAgo(2, 18),
  },
  {
    id: 5,
    user_id: 7,
    action: 'publish_lost',
    target_type: 'lost',
    target_id: 4,
    ip: '10.12.5.10',
    ua: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    gps: null,
    detail: 'title=一串钥匙（含门禁卡）;category_id=11',
    created_at: daysAgo(4, 19),
  },
  {
    id: 6,
    user_id: 8,
    action: 'publish_found',
    target_type: 'found',
    target_id: 4,
    ip: '10.12.5.11',
    ua: 'Mozilla/5.0 (Linux; Android 13)',
    gps: '30.65,104.08',
    detail: 'keep_status=0;category_id=11',
    created_at: daysAgo(4, 20),
  },
  {
    id: 7,
    user_id: 7,
    action: 'claim',
    target_type: 'match',
    target_id: 4,
    ip: '10.12.5.10',
    ua: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    gps: null,
    detail: '红色钥匙扣，共5把钥匙。',
    created_at: daysAgo(3, 20),
  },
  {
    id: 8,
    user_id: 1,
    action: 'handover_complete',
    target_type: 'match',
    target_id: 3,
    ip: '10.12.3.21',
    ua: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)',
    gps: '30.64,104.07|30.64,104.07',
    detail: 'code=Z9X8Y7',
    created_at: daysAgo(1, 14),
  },
  {
    id: 9,
    user_id: 8,
    action: 'reject',
    target_type: 'match',
    target_id: 5,
    ip: '10.12.5.11',
    ua: 'Mozilla/5.0 (Linux; Android 13)',
    gps: null,
    detail: '物品特征不符，非本人遗失。',
    created_at: daysAgo(6, 19),
  },
  {
    id: 10,
    user_id: 99,
    action: 'ban',
    target_type: 'user',
    target_id: 22,
    ip: '127.0.0.1',
    ua: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
    gps: null,
    detail: '多次发布虚假信息，封禁 7 天。',
    created_at: daysAgo(7, 10),
  },
  // v3：IM 消息镜像（冒领溯源）
  {
    id: 11,
    user_id: 1,
    action: 'im_message',
    target_type: 'im_session',
    target_id: 1,
    ip: '10.12.3.21',
    ua: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)',
    gps: null,
    detail: '[0] 你好，这把雨伞是我捡的',
    created_at: daysAgo(1, 14),
  },
]
