// axios 实例：统一挂载 JWT、解包 {code,message,data} 信封、处理 401 跳转，
// 并根据“演示模式”在请求拦截器中切换为本地 mock 适配器（不影响真实后端请求）。

import axios, { type AxiosAdapter } from 'axios'
import { ElMessage } from 'element-plus'
import type { ApiEnvelope } from '@/types'
import { ApiError } from '@/types'
import { API_BASE } from '@/api/constants'
import { API_ORIGIN, getDemo } from '@/utils/demo'
import { useDemoStore } from '@/stores/demo'
import { mockAdapter } from '@/api/mockAdapter'

const TOKEN_KEY = 'lf_token'
const USER_KEY = 'lf_user'

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}
export function setToken(t: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, t)
  } catch {
    /* ignore */
  }
}
export function clearToken(): void {
  try {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  } catch {
    /* ignore */
  }
}

/** 将相对/绝对图片路径补全为可访问 URL（演示模式 data URI 原样返回） */
export function fullImageUrl(url?: string | null): string {
  if (!url) return ''
  if (
    url.startsWith('http') ||
    url.startsWith('data:') ||
    url.startsWith('blob:') ||
    url.startsWith('//')
  ) {
    return url
  }
  return API_ORIGIN + url
}

export const http = axios.create({
  baseURL: API_BASE,
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
})

// 请求拦截：附加 Bearer 令牌；演示模式使用本地 mock 适配器
http.interceptors.request.use((config) => {
  const t = getToken()
  if (t) {
    ;(config.headers as Record<string, string>).Authorization = `Bearer ${t}`
  }
  // 关键修复：当请求体为 FormData（含图片上传，如 /found-items、/lost-items、
  // /vision/predict）时，删除实例默认的 application/json 头，让 axios 自动设置
  // multipart/form-data; boundary=...，否则后端 multipart 解析收不到字段导致 422。
  if (config.data instanceof FormData) {
    delete (config.headers as Record<string, string>)['Content-Type']
  }
  if (getDemo()) {
    config.adapter = mockAdapter as AxiosAdapter
  }
  return config
})

// 响应拦截：解包信封；业务错误弹窗并 reject
http.interceptors.response.use(
  (resp) => {
    const env = resp.data as ApiEnvelope<unknown>
    if (env && typeof env === 'object' && 'code' in env) {
      if (env.code === 0) return env.data as never
      ElMessage.error(env.message || '请求失败')
      return Promise.reject(new ApiError(env.code, env.message, env.data))
    }
    return resp.data as never
  },
  (error) => {
    const resp = error?.response
    if (
      resp &&
      resp.data &&
      typeof resp.data === 'object' &&
      'code' in resp.data
    ) {
      const env = resp.data as ApiEnvelope<unknown> & { code: number; message: string }
      ElMessage.error(env.message || '请求失败')
      if (env.code === 1000 || env.code === 1001) {
        clearToken()
        import('@/router').then((m) => m.default.push('/login'))
      }
      return Promise.reject(new ApiError(env.code, env.message, env.data))
    }
    ElMessage.error(error?.message || '网络错误，已切换为演示模式')
    // 网络级错误（后端不可达）：自动降级演示 + 显示 Banner
    try {
      useDemoStore().notifyNetworkFallback()
    } catch {
      /* Pinia 未就绪时忽略 */
    }
    return Promise.reject(error)
  },
)

/** 应用演示模式（已在请求拦截器中按请求粒度处理，这里保留以便启动时显式调用） */
export function applyDemoMode(): void {
  /* 适配器按请求在拦截器中切换，无需在此修改实例默认值 */
}

// ---------------- 工具：清理空参数 ----------------
function cleanParams(params?: Record<string, unknown>): Record<string, unknown> | undefined {
  if (!params) return undefined
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && v !== '') out[k] = v
  }
  return Object.keys(out).length ? out : undefined
}

// ---------------- 类型安全的请求封装（自动解包 data） ----------------
export async function apiGet<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  return (await http.get(url, { params: cleanParams(params) })) as unknown as T
}

export async function apiPost<T>(
  url: string,
  data?: unknown,
  config?: Record<string, unknown>,
): Promise<T> {
  return (await http.post(url, data, config as never)) as unknown as T
}

export async function apiDelete<T>(url: string): Promise<T> {
  return (await http.delete(url)) as unknown as T
}
