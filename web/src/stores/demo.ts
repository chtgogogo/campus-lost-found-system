// 演示模式状态（Pinia）：管理“演示数据”开关与后端可达性探测。
import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  clearDemoPreference,
  getDemo,
  getDemoRole,
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

  /** 启动初始化：2026-08-20 演示模式已永久关闭（getDemo 恒 false），
   *  一律走真实后端，不再因"探测不到"自动开启演示模式。 */
  async function init() {
    enabled.value = false
    autoDetected.value = false
    backendReachable.value = null
    applyDemoMode()
  }

  /** 手动切换演示模式：已永久关闭，恒为真实后端（保留签名防调用方断裂）。 */
  function setEnabled(_on: boolean) {
    setDemo(false)
    enabled.value = false
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

  /** 恢复“自动探测”语义（演示模式已关闭，等同直接回到真实后端） */
  function resetToAuto() {
    clearDemoPreference()
    enabled.value = false
    autoDetected.value = false
    backendReachable.value = null
    init()
  }

  /** 网络错误回退：2026-08-20 起演示模式永久关闭，
   *  网络错误只由请求层提示，不再自动切换（保留签名防调用方断裂）。 */
  function notifyNetworkFallback() {
    setDemo(false)
    enabled.value = false
    autoDetected.value = false
    bannerVisible.value = false
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
