// 演示模式状态（Pinia）：管理“演示数据”开关与后端可达性探测。
import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  clearDemoPreference,
  getDemo,
  getDemoRole,
  probeBackend,
  setDemo,
  setDemoRole,
} from '@/utils/demo'
import { applyDemoMode } from '@/api/request'

export const useDemoStore = defineStore('demo', () => {
  // enabled：当前是否使用演示数据
  const enabled = ref<boolean>(getDemo())
  // backendReachable：后端是否可达（null 表示尚未探测）
  const backendReachable = ref<boolean | null>(null)
  // autoDetected：是否因后端不可达而自动开启（用于提示）
  const autoDetected = ref<boolean>(false)
  // bannerVisible：是否展示“当前为演示模式”全局提示条
  const bannerVisible = ref<boolean>(false)
  // dataVersion：切换演示模式时自增，用于强制页面重渲染重新拉取数据
  const dataVersion = ref<number>(0)
  // demoRole：演示身份（0 普通用户 / 1 管理员），用于演示态进入管理后台
  const demoRole = ref<number>(getDemoRole())

  /** 启动时探测：用户未手动设置过时，后端不可达则自动开启演示模式 */
  async function init() {
    const stored = getDemo()
    // 注意 getDemo() 在 null 时返回 false；这里需要判断是否“从未手动设置”
    const raw = (() => {
      try {
        return localStorage.getItem('lf_demo_mode')
      } catch {
        return null
      }
    })()
    if (raw === null) {
      const ok = await probeBackend()
      backendReachable.value = ok
      if (!ok) {
        setDemo(true)
        enabled.value = true
        autoDetected.value = true
        bannerVisible.value = true
      } else {
        enabled.value = false
        autoDetected.value = false
      }
    } else {
      enabled.value = stored
      autoDetected.value = false
    }
    applyDemoMode()
  }

  /** 手动切换演示模式 */
  function setEnabled(on: boolean) {
    setDemo(on)
    enabled.value = on
    autoDetected.value = false
    applyDemoMode()
    dataVersion.value += 1
  }

  /** 切换演示身份（0 普通 / 1 管理员），演示态进入管理后台用 */
  function setRole(role: number) {
    setDemoRole(role)
    demoRole.value = role === 1 ? 1 : 0
    dataVersion.value += 1
  }

  /** 恢复“自动探测”语义 */
  function resetToAuto() {
    clearDemoPreference()
    enabled.value = false
    autoDetected.value = false
    backendReachable.value = null
    init()
  }

  /** 网络错误时由请求层调用：自动切演示模式并弹出 Banner（不重复切换） */
  function notifyNetworkFallback() {
    if (!enabled.value) {
      setDemo(true)
      enabled.value = true
    }
    autoDetected.value = true
    bannerVisible.value = true
  }

  /** 用户手动关闭 Banner（不退出演示模式，仅隐藏提示条） */
  function dismissBanner() {
    bannerVisible.value = false
  }

  return {
    enabled,
    backendReachable,
    autoDetected,
    bannerVisible,
    dataVersion,
    demoRole,
    init,
    setEnabled,
    setRole,
    resetToAuto,
    notifyNetworkFallback,
    dismissBanner,
  }
})
