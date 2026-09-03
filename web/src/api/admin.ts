// 管理后台接口（对齐 app/routers/admin.py）
//
// v10 变更 D 新增/扩展：
//   - D1 `GET  /admin/users`                 用户列表（手机号明文）
//   - D2 `GET  /admin/matches/{id}/detail`   匹配详情（双方明文 + 结构化对话）
//   - D3 `POST /admin/export`                导出扩 scope（profile|conversation|all）
//                                            与 format（csv|xlsx|md）
//   - D4 `GET  /admin/matches?all_time=true` 跳过留存时间窗，返回全部历史匹配
//
// ⚠️ 合规：`AdminUserOut.phone` 与导出文件均为**明文**，任何展示入口都必须
//    带合规提示，且仅对 role=1 可见（后端由 require_admin 兜底）。
import { http } from './request'
import type {
  AdminMatchDetailOut,
  AdminUserOut,
  AuditLog,
  ExportFormat,
  ExportScope,
  MatchOut,
  Page,
} from '@/types'

/** 后端 `export_filename()` 的前端镜像，保证下载文件名与服务端一致。 */
function forensicFilename(scope: ExportScope, ext: ExportFormat): string {
  const dateStr = new Date().toISOString().slice(0, 10).replace(/-/g, '')
  return `forensic_matches_${scope}_${dateStr}.${ext}`
}

/** 把 Blob 存成本地文件（统一下载实现，避免各处重复 createObjectURL 逻辑）。 */
function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export const adminApi = {
  /** 导出审计日志为 CSV / JSON（触发浏览器下载）。 */
  exportAudit(format: 'csv' | 'json' = 'csv'): Promise<void> {
    return http
      .get(`/admin/audit-logs/export?format=${format}`, { responseType: 'blob' } as never)
      .then((resp) => {
        saveBlob(resp as unknown as Blob, `audit_logs.${format}`)
      })
  },

  /** 审计日志列表（管理后台页内时间线；与导出同源）。 */
  auditLogs(
    params: { page?: number; page_size?: number } = {},
  ): Promise<Page<AuditLog>> {
    return http.get('/admin/audit-logs', { params })
  },

  /**
   * v10-D1：用户列表（手机号**明文**，仅管理员可见）。
   *
   * @param params.keyword 学号 / 手机号 / 真实姓名模糊匹配（任一命中）
   * @param params.role    0=普通 1=管理员，省略为全部
   * @param params.status  User.status 过滤，省略为全部
   */
  listUsers(
    params: {
      keyword?: string
      role?: number
      status?: number
      page?: number
      page_size?: number
    } = {},
  ): Promise<Page<AdminUserOut>> {
    return http.get('/admin/users', { params })
  },

  /**
   * v7 + v10-D4：管理员匹配列表。
   *
   * @param params.all_time true 时跳过留存时间窗，返回全部历史匹配（默认 false，
   *   行为与 v7 完全一致）。
   */
  listAdminMatches(
    params: {
      status?: number
      all_time?: boolean
      page?: number
      page_size?: number
    } = {},
  ): Promise<Page<MatchOut>> {
    return http.get('/admin/matches', { params })
  },

  /** v10-D2：匹配详情（双方明文信息 + 结构化对话）。任意 status 均可查看。 */
  getMatchDetail(matchId: number): Promise<AdminMatchDetailOut> {
    return http.get(`/admin/matches/${matchId}/detail`)
  },

  /**
   * v7 + v10-D3：取证导出（POST /admin/export），触发浏览器下载。
   *
   * 默认 `scope='all'` + `format='csv'`，与 v7 老调用 `exportMatches(ids)` 行为一致。
   *
   * @throws 后端未装 openpyxl 时 xlsx 会返回 400 + code 9001（**不是 500**），
   *   由 request 拦截器统一抛 ApiError，调用方需提示"服务器不支持 xlsx"。
   */
  exportMatches(
    ids: number[],
    format: ExportFormat = 'csv',
    scope: ExportScope = 'all',
  ): Promise<void> {
    return http
      .post('/admin/export', { ids, format, scope }, { responseType: 'blob' } as never)
      .then((resp) => {
        saveBlob(resp as unknown as Blob, forensicFilename(scope, format))
      })
  },

  /** v7：触发周期清理（POST /admin/cleanup）。 */
  triggerCleanup(): Promise<{ purged_matches: number; purged_items: number }> {
    return http.post('/admin/cleanup')
  },
}
