// 中文时间格式化（增量设计 v2 / 决策 E / Q3）。
// 统一来源：卡片与详情弹窗均调用 formatChineseDateTime，禁止组件内散写英文月份或裸数字。

const CN_MONTHS = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十', '十一', '十二']
const CN_WEEK = ['日', '一', '二', '三', '四', '五', '六']

/**
 * 将 ISO 时间字符串格式化为中文「YYYY年M月D日 周X」。
 * - 非法/空值返回 '—'。
 * - 月份/星期使用内联中文映射表，不依赖 moment / dayjs。
 */
export function formatChineseDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const y = d.getFullYear()
  const m = d.getMonth()
  const day = d.getDate()
  const w = d.getDay()
  return `${y}年${CN_MONTHS[m]}月${day}日 周${CN_WEEK[w]}`
}
