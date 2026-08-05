// 即时通讯会话收发 composable（v5 抽取，供 MessagesView 与 ContactDialog 复用）。
// 封装：会话消息加载、增量轮询、发送；消除双栏面板与联系对话框的重复收发逻辑。
import { onUnmounted, ref } from 'vue'
import { imApi } from '@/api/im'
import { IM_POLL_INTERVAL_MS } from '@/api/constants'
import type { IMMessageCreate, IMMessageOut } from '@/types'

export function useImSession() {
  const messages = ref<IMMessageOut[]>([])
  const loading = ref(false)
  const sending = ref(false)
  const sessionId = ref<number | null>(null)
  let timer: ReturnType<typeof setInterval> | null = null

  function lastId(): number {
    return messages.value.length ? messages.value[messages.value.length - 1].id : 0
  }

  async function poll(): Promise<void> {
    if (sessionId.value == null) return
    try {
      const msgs = await imApi.getMessages(sessionId.value, lastId())
      if (msgs.length) messages.value.push(...msgs)
    } catch {
      /* 轮询失败静默重试 */
    }
  }

  function startPoll(): void {
    stopPoll()
    timer = setInterval(poll, IM_POLL_INTERVAL_MS)
  }

  function stopPoll(): void {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  /** 进入会话：加载历史并启动轮询。 */
  async function initSession(id: number): Promise<void> {
    sessionId.value = id
    loading.value = true
    messages.value = []
    try {
      const history = await imApi.getMessages(id, 0)
      messages.value = history
    } catch {
      messages.value = []
    } finally {
      loading.value = false
    }
    startPoll()
  }

  /** 发送消息；返回新消息或 null（空内容 / 未就绪）。 */
  async function send(body: IMMessageCreate): Promise<IMMessageOut | null> {
    if (sessionId.value == null) return null
    const content = (body.content || '').trim()
    if (!content) return null
    sending.value = true
    try {
      const m = await imApi.sendMessage(sessionId.value, body)
      messages.value.push(m)
      return m
    } catch {
      return null
    } finally {
      sending.value = false
    }
  }

  /** 清空会话状态并停止轮询（关闭 / 切换会话前调用）。 */
  function reset(): void {
    stopPoll()
    messages.value = []
    sessionId.value = null
    loading.value = false
    sending.value = false
  }

  onUnmounted(stopPoll)

  return {
    messages,
    loading,
    sending,
    sessionId,
    initSession,
    send,
    poll,
    startPoll,
    stopPoll,
    reset,
  }
}
