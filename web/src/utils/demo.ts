// 演示（mock）模式管理：开关持久化到 localStorage。
// 规则：
//  - 用户手动切换的开关保存在 localStorage('lf_demo_mode')；
//  - 若用户从未手动设置过（值为 null），则启动时对后端做健康探测，
//    探测不到（后端不可用）自动开启演示模式，保证 UI 可完整渲染。

// v7：演示身份切换（需求 A）——实际状态与 setter 由 mockData 持有（避免循环依赖）。
import { currentMockRole, setMockRole } from '@/api/mockData'

const STORAGE_KEY = 'lf_demo_mode'

/** 内存缓存，避免重复读 localStorage */
let _demo: boolean | null = null

/** 切换演示身份：0 普通用户 / 1 管理员（演示态以管理员进入管理后台）。 */
export const setDemoRole = setMockRole

/** 读取当前演示身份（0 普通 / 1 管理员）。 */
export function getDemoRole(): number {
  return currentMockRole
}

export function readStoredDemo(): boolean | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === null) return null
    return v === '1'
  } catch {
    return null
  }
}

/** 当前是否处于演示模式。
 *  2026-08-20 按用户要求永久关闭：本系统经 cpolar 对外提供服务，一律走真实后端，
 *  不再使用本地 mock 假数据（避免家人看到空账号/假数据）。无论 localStorage 曾经如何设置，均强制 false。 */
export function getDemo(): boolean {
  return false
}

/** 设置演示模式（true 演示数据 / false 真实后端），并持久化 */
export function setDemo(on: boolean): void {
  _demo = on
  try {
    localStorage.setItem(STORAGE_KEY, on ? '1' : '0')
  } catch {
    /* 忽略持久化失败 */
  }
}

/** 清除用户手动设置，恢复“自动探测”语义 */
export function clearDemoPreference(): void {
  _demo = null
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* 忽略 */
  }
}

/** 后端可达性探测：请求 {origin}/health，期望 {code:0} */
export async function probeBackend(): Promise<boolean> {
  const origin = API_ORIGIN
  try {
    const resp = await fetch(`${origin}/health`, { method: 'GET' })
    if (!resp.ok) return false
    const json = (await resp.json()) as { code?: number }
    return json.code === 0
  } catch {
    return false
  }
}

/** 由 API_BASE 推导后端源站（去掉 /api/v1） */
export const API_ORIGIN = (() => {
  const base = import.meta.env.VITE_API_BASE || '/api/v1'
  return base.replace(/\/api\/v1\/?$/i, '')
})()
