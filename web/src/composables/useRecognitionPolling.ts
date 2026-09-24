/**
 * v17④：AI 识别中物品的轮询（发布后识别异步完成，前端定时重拉列表刷新状态）。
 *
 * 用法：列表页在每次 load() 完成后调 maybeStart()；
 * hasPending 返回当前列表是否还有识别中（recognize_status 0/1）的物品。
 * 有则每 4s 静默重拉一次（不走 loading 骨架），全部识别完成或达到轮询上限自动停止。
 */
import { onBeforeUnmount } from 'vue'

const POLL_INTERVAL_MS = 4000
const MAX_POLLS = 15 // 4s × 15 = 1 分钟窗口；超限停止（识别失败/ worker 停摆不至于无限转）

export function useRecognitionPolling(
  hasPending: () => boolean,
  refresh: (silent?: boolean) => Promise<void> | void,
) {
  let timer: ReturnType<typeof setInterval> | null = null
  let polls = 0

  function stop() {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
  }

  function maybeStart() {
    if (timer !== null || !hasPending()) return
    polls = 0
    timer = setInterval(async () => {
      polls += 1
      if (polls > MAX_POLLS || !hasPending()) {
        stop()
        return
      }
      await refresh(true)
      if (!hasPending()) stop()
    }, POLL_INTERVAL_MS)
  }

  onBeforeUnmount(stop)
  return { maybeStart, stop }
}
