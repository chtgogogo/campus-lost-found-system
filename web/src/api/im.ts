// IM 即时通讯接口（对齐 app/routers/im.py，v3 需求 D：联系对方）
import { apiDelete, apiGet, apiPost } from './request'
import type {
  IMMessageCreate,
  IMMessageOut,
  IMSessionListItem,
  IMSessionOut,
} from '@/types'

export const imApi = {
  // 创建 / 复用会话：
  // - 传 match_id：既有匹配会话
  // - 传 found_id：v4 无 match 的联系入口（绑定到具体拾物，强溯源 + 发送端二次门控）
  // 门控：对端 contact_allowed==0 时后端返回 403
  createSession(body: { match_id?: number; found_id?: number }): Promise<IMSessionOut> {
    return apiPost<IMSessionOut>('/im/sessions', body)
  },
  // v5：「我的消息」会话列表（status=0 且参与者含当前用户，富化）
  listSessions(): Promise<IMSessionListItem[]> {
    return apiGet<IMSessionListItem[]>('/im/sessions')
  },
  // v5：删除此对话（软删 status=1）
  deleteSession(sessionId: number): Promise<{ id: number; status: number }> {
    return apiDelete<{ id: number; status: number }>(`/im/sessions/${sessionId}`)
  },
  // v5：招领成功（软删 status=1 + 关联未完成 match 归档）
  successSession(sessionId: number): Promise<{
    id: number
    status: number
    match_archived: boolean
  }> {
    return apiPost<{ id: number; status: number; match_archived: boolean }>(
      `/im/sessions/${sessionId}/success`,
      {},
    )
  },
  // 轮询历史消息（since_id 增量游标）
  getMessages(sessionId: number, sinceId = 0, limit = 50): Promise<IMMessageOut[]> {
    return apiGet<IMMessageOut[]>(`/im/sessions/${sessionId}/messages`, {
      since_id: sinceId,
      limit,
    })
  },
  // 发送消息（JWT 鉴权 + 禁链接由后端校验）
  sendMessage(sessionId: number, body: IMMessageCreate): Promise<IMMessageOut> {
    return apiPost<IMMessageOut>(`/im/sessions/${sessionId}/messages`, body)
  },
}
