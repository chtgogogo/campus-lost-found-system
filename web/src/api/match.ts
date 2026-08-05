// 匹配 / 认领 / 交接相关接口（对齐 app/routers/match.py）
import { apiGet, apiPost } from './request'
import type {
  AuditLog,
  ClaimRequest,
  HandoverGenerate,
  HandoverVerifyRequest,
  HandoverVerifyResult,
  MatchOut,
  Page,
  RefreshMatchesResult,
} from '@/types'

export interface MatchListParams {
  status?: number | null
  page?: number
  page_size?: number
}

export const matchApi = {
  myMatches(params: MatchListParams = {}): Promise<Page<MatchOut>> {
    return apiGet<Page<MatchOut>>('/matches', params as Record<string, unknown>)
  },
  matchesForLost(itemId: number): Promise<MatchOut[]> {
    return apiGet<MatchOut[]>(`/lost-items/${itemId}/matches`)
  },
  // 2026-08-05 增量：P2-1 手动刷新候选（对单条失物重跑召回+打分，增量补充新发布拾物）
  refreshMatches(lostId: number): Promise<RefreshMatchesResult> {
    return apiPost<RefreshMatchesResult>(`/lost-items/${lostId}/refresh-matches`, {})
  },
  claim(matchId: number, body: ClaimRequest): Promise<MatchOut> {
    return apiPost<MatchOut>(`/matches/${matchId}/claim`, body)
  },
  confirmReturn(matchId: number): Promise<MatchOut> {
    return apiPost<MatchOut>(`/matches/${matchId}/confirm-return`, {})
  },
  handoverGenerate(matchId: number): Promise<HandoverGenerate> {
    return apiPost<HandoverGenerate>(`/matches/${matchId}/handover/generate`, {})
  },
  handoverVerify(matchId: number, body: HandoverVerifyRequest): Promise<HandoverVerifyResult> {
    return apiPost<HandoverVerifyResult>(`/matches/${matchId}/handover/verify`, body)
  },
  reject(matchId: number, reason?: string): Promise<MatchOut> {
    return apiPost<MatchOut>(`/matches/${matchId}/reject`, { reason: reason ?? null })
  },
  // v4：失主手动申请匹配（未挪动自取），生成 status=4 的「待自取」单边匹配
  createManual(lostId: number, foundId: number): Promise<MatchOut> {
    return apiPost<MatchOut>('/matches/manual', { lost_id: lostId, found_id: foundId })
  },
  // v4：失主单边完成「待自取」匹配（status 4 → 2，双端置已解决，不调双码交接）
  selfComplete(matchId: number): Promise<MatchOut> {
    return apiPost<MatchOut>(`/matches/${matchId}/self-complete`, {})
  },
  // v5：未能找回（失主放弃匹配，软删 status=5 + 失物重入匹配池）
  giveup(matchId: number): Promise<MatchOut> {
    return apiPost<MatchOut>(`/matches/${matchId}/giveup`, {})
  },
  // v2（2026-08-05）：keep1「申请即完成」—— 对 status=0 候选一步完成（后端 P0-3）
  claimComplete(matchId: number): Promise<MatchOut> {
    return apiPost<MatchOut>(`/matches/${matchId}/claim-complete`, {})
  },
  // v2（2026-08-05）：keep1 完成记录撤回（后端 P0-4，仅 flow_type=1 && status=2）
  revoke(matchId: number): Promise<MatchOut> {
    return apiPost<MatchOut>(`/matches/${matchId}/revoke`, {})
  },
  // 管理后台审计日志（后端暂未暴露该接口，演示模式由 mock 适配器提供）
  auditLogs(params: MatchListParams = {}): Promise<Page<AuditLog>> {
    return apiGet<Page<AuditLog>>('/audit-logs', params as Record<string, unknown>)
  },
}
