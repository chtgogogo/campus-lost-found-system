// request.ts 单测（审查 P1 前端最小门禁，2026-09-24）：
// 覆盖令牌存取、图片 URL 拼接、信封解包（成功/业务错误/401 清token）——纯逻辑，不发网络。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AxiosError } from 'axios'

// element-plus 的 ElMessage 依赖真实 DOM 渲染，mock 掉只记录调用
vi.mock('element-plus', () => ({
  ElMessage: { error: vi.fn() },
}))

import { ElMessage } from 'element-plus'
import {
  apiGet,
  apiPost,
  clearToken,
  fullImageUrl,
  getToken,
  http,
  setToken,
} from './request'
import { ApiError } from '@/types'

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

describe('token 存取', () => {
  it('setToken/getToken/clearToken 往返', () => {
    expect(getToken()).toBeNull()
    setToken('tok-1')
    expect(getToken()).toBe('tok-1')
    clearToken()
    expect(getToken()).toBeNull()
  })
})

describe('fullImageUrl', () => {
  it('空值返回空串', () => {
    expect(fullImageUrl(null)).toBe('')
    expect(fullImageUrl('')).toBe('')
  })
  it('绝对地址原样返回', () => {
    expect(fullImageUrl('http://a/b.png')).toBe('http://a/b.png')
    expect(fullImageUrl('https://a/b.png')).toBe('https://a/b.png')
    expect(fullImageUrl('data:image/png;base64,xx')).toBe('data:image/png;base64,xx')
    expect(fullImageUrl('blob:xx')).toBe('blob:xx')
    expect(fullImageUrl('//cdn/a.png')).toBe('//cdn/a.png')
  })
  it('相对路径拼 API_ORIGIN', () => {
    expect(fullImageUrl('/uploads/a.png')).toBe('/uploads/a.png')
  })
})

describe('信封解包', () => {
  // 在 adapter 层 mock（保留真实拦截器链）；spy 实例方法会绕过拦截器，测不到解包逻辑
  const originalAdapter = http.defaults.adapter
  function mockResponse(payload: unknown) {
    http.defaults.adapter = async () => ({
      data: payload,
      status: 200,
      statusText: 'OK',
      headers: {},
      config: {} as never,
    })
  }

  afterEach(() => {
    http.defaults.adapter = originalAdapter
  })

  it('code=0 返回 data 本体', async () => {
    mockResponse({ code: 0, message: 'success', data: { ok: 7 } })
    await expect(apiGet('/x')).resolves.toEqual({ ok: 7 })
  })

  it('业务错误码：弹提示并 reject ApiError', async () => {
    mockResponse({ code: 3003, message: '该匹配已处理', data: null })
    await expect(apiPost('/x', {})).rejects.toMatchObject({
      code: 3003,
      message: '该匹配已处理',
    })
    expect(ElMessage.error).toHaveBeenCalledWith('该匹配已处理')
  })

  it('401/1001：清 token 并 reject ApiError（ApiError 为 Error 子类）', async () => {
    setToken('will-be-cleared')
    // HTTP 401 + 业务码 1000：走响应拦截器错误分支（clearToken + 跳登录）
    http.defaults.adapter = async (config) => {
      throw new AxiosError('Request failed with status code 401', '401', config, null, {
        data: { code: 1000, message: '未认证或令牌缺失', data: null },
        status: 401,
        statusText: 'Unauthorized',
        headers: {},
      } as never)
    }
    await expect(apiPost('/x', {})).rejects.toBeInstanceOf(ApiError)
    expect(getToken()).toBeNull()
    expect(ElMessage.error).toHaveBeenCalled()
  })

  it('非信封响应原样透传', async () => {
    mockResponse('plain')
    await expect(apiGet('/x')).resolves.toBe('plain')
  })
})
