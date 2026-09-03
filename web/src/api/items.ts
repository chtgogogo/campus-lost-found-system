// 物品相关接口（对齐 app/routers/items.py）
import { apiDelete, apiGet, apiPost } from './request'
import type {
  FoundItemOut,
  LostItemOut,
  MatchOut,
  Page,
} from '@/types'

// 发布 = 上传图片 + 后端视觉识别/反向匹配，公网下慢；给足 60s（全局 axios 默认 15s 不够）。
const PUBLISH_TIMEOUT = 60000

export interface ItemListParams {
  status?: number | null
  /** 排除已解决项（失物 status!=3 / 拾物 status!=1），用于公示栏主三 tab */
  exclude_resolved?: boolean
  /** 仅返回已解决项（失物 status==3 / 拾物 status==1），用于「已完成交接」tab */
  resolved_only?: boolean
  page?: number
  page_size?: number
}

export interface CreateLostResult {
  item: LostItemOut
  suspected_matches: MatchOut[]
}

export interface CreateFoundResult {
  item: FoundItemOut
  suspected_matches: MatchOut[]
}

export interface MyPublished {
  lost: LostItemOut[]
  found: FoundItemOut[]
}

export const itemsApi = {
  listLost(params: ItemListParams = {}): Promise<Page<LostItemOut>> {
    return apiGet<Page<LostItemOut>>('/lost-items', params as Record<string, unknown>)
  },
  getLost(id: number): Promise<LostItemOut> {
    return apiGet<LostItemOut>(`/lost-items/${id}`)
  },
  deleteLost(id: number): Promise<LostItemOut> {
    return apiDelete<LostItemOut>(`/lost-items/${id}`)
  },
  listFound(params: ItemListParams = {}): Promise<Page<FoundItemOut>> {
    return apiGet<Page<FoundItemOut>>('/found-items', params as Record<string, unknown>)
  },
  getFound(id: number): Promise<FoundItemOut> {
    return apiGet<FoundItemOut>(`/found-items/${id}`)
  },
  deleteFound(id: number): Promise<FoundItemOut> {
    return apiDelete<FoundItemOut>(`/found-items/${id}`)
  },
  // 失物发布：multipart/form-data（由 axios 自动设置带 boundary 的 Content-Type）
  // v8：表单项除既有字段外，可含 appearance / features / location 三列（由发布页追加），
  // 服务端落库后随 LostItemOut 返回（见 @/types 中 LostItemOut.appearance/features/location）。
  createLost(form: FormData): Promise<CreateLostResult> {
    return apiPost<CreateLostResult>('/lost-items', form, { timeout: PUBLISH_TIMEOUT })
  },
  // 拾物发布：multipart/form-data
  // v8：同 createLost，appearance / features / location 随 FoundItemOut 返回。
  createFound(form: FormData): Promise<CreateFoundResult> {
    return apiPost<CreateFoundResult>('/found-items', form, { timeout: PUBLISH_TIMEOUT })
  },
  // 我的发布（v3 需求 E）：当前用户本人的失物与拾物
  myPublished(): Promise<MyPublished> {
    return apiGet<MyPublished>('/users/me/items')
  },
}
