<template>
  <div class="lf-container messages-view">
    <h2 class="lf-page-title">我的消息</h2>

    <div class="messages-layout lf-card">
      <!-- 左栏：会话列表 -->
      <aside class="session-list">
        <div v-if="loadingList" class="lf-muted list-hint">加载中…</div>
        <el-empty v-else-if="sessions.length === 0" description="暂无会话" :image-size="56" />
        <div
          v-for="s in sessions"
          :key="s.id"
          class="session-item"
          :class="{ active: selectedId === s.id }"
          @click="openConversation(s)"
        >
          <div class="session-avatar">{{ avatarText(s.peer_user.nickname) }}</div>
          <div class="session-main">
            <div class="session-top">
              <span class="session-title">{{ s.title }}</span>
              <span class="session-time">{{ formatTime(s.last_message_at) }}</span>
            </div>
            <div class="session-bottom">
              <span class="session-preview">{{ s.last_message_preview || '暂无消息' }}</span>
              <span v-if="s.unread" class="unread-dot" />
            </div>
          </div>
        </div>
      </aside>

      <!-- 右栏：对话面板 -->
      <section class="chat-panel">
        <template v-if="selected">
          <div class="chat-header">
            <span class="chat-title">{{ selected.title }}</span>
            <span v-if="selected.match_id" class="lf-muted chat-meta">
              匹配 #{{ selected.match_id }}
            </span>
            <span v-else-if="selected.found_id" class="lf-muted chat-meta">
              拾物 #{{ selected.found_id }}
            </span>
          </div>

          <div v-loading="im.loading.value" class="chat-box" ref="boxRef">
            <div
              v-for="m in im.messages.value"
              :key="m.id"
              class="bubble-row"
              :class="m.sender_role === myRole ? 'me' : 'peer'"
            >
              <div class="bubble">{{ m.content }}</div>
              <div class="bubble-time">{{ formatTime(m.sent_at) }}</div>
            </div>
            <el-empty
              v-if="!im.loading.value && im.messages.value.length === 0"
              description="还没有消息，打个招呼吧"
              :image-size="60"
            />
          </div>

          <div class="chat-input">
            <el-input
              v-model="draft"
              type="textarea"
              :rows="2"
              maxlength="500"
              resize="none"
              placeholder="输入消息（不可包含外部链接）"
              @keyup.enter.exact.prevent="onSend"
            />
            <el-button type="primary" :loading="im.sending.value" @click="onSend">
              发送
            </el-button>
          </div>

          <div class="chat-actions">
            <el-button plain @click="onDelete">删除此对话</el-button>
            <el-button type="success" @click="onSuccess">招领成功</el-button>
          </div>
        </template>

        <div v-else class="chat-empty">
          <el-empty description="选择一个会话开始聊天" />
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { imApi } from '@/api/im'
import { MOCK_ME } from '@/api/mockAdapter'
import { useImSession } from '@/composables/useImSession'
import { useAuthStore } from '@/stores/auth'
import type { IMSessionListItem } from '@/types'

const auth = useAuthStore()

const loadingList = ref(false)
const sessions = ref<IMSessionListItem[]>([])
const selected = ref<IMSessionListItem | null>(null)
const selectedId = ref<number | null>(null)
const draft = ref('')
const boxRef = ref<HTMLElement | null>(null)
const myRole = ref(0) // 在当前会话中的角色：0 失主 / 1 拾得者

// 复用收发 composable（轮询 + 发送）
const im = useImSession()

// 进入会话即视为已读（粗粒度，清除红点由前端维护）
const readSet = new Set<number>()

function currentUserId(): number {
  const id = auth.userId
  if (id != null) return id
  return MOCK_ME
}

async function loadSessions(): Promise<void> {
  loadingList.value = true
  try {
    const list = await imApi.listSessions()
    sessions.value = list.map((s) => (readSet.has(s.id) ? { ...s, unread: false } : s))
  } catch {
    sessions.value = []
  } finally {
    loadingList.value = false
  }
}

function avatarText(name?: string): string {
  return (name || '?').slice(0, 1)
}

function formatTime(iso?: string | null): string {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    const now = new Date()
    const sameDay =
      d.getFullYear() === now.getFullYear() &&
      d.getMonth() === now.getMonth() &&
      d.getDate() === now.getDate()
    if (sameDay)
      return d.toLocaleTimeString('zh-CN', {
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      })
    return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
  } catch {
    return ''
  }
}

function scrollDown(): void {
  nextTick(() => {
    const el = boxRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

async function openConversation(s: IMSessionListItem): Promise<void> {
  selected.value = s
  selectedId.value = s.id
  // 当前用户在会话中的角色（用于气泡对齐：0 失主 / 1 拾得者）
  myRole.value = s.lost_user_id === currentUserId() ? 0 : 1
  readSet.add(s.id)
  s.unread = false
  await im.initSession(s.id)
  scrollDown()
}

async function onSend(): Promise<void> {
  const content = draft.value.trim()
  if (!content) {
    ElMessage.warning('消息内容不能为空')
    return
  }
  const m = await im.send({ type: 'text', content })
  if (m) {
    draft.value = ''
    scrollDown()
  }
}

async function onDelete(): Promise<void> {
  if (!selected.value) return
  try {
    await ElMessageBox.confirm(
      '确定删除此对话吗？删除后将从列表隐藏（后台保留一段时间）。',
      '删除此对话',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }
  try {
    await imApi.deleteSession(selected.value.id)
    ElMessage.success('已删除此对话')
    selected.value = null
    selectedId.value = null
    im.reset()
    await loadSessions()
  } catch {
    /* 忽略 */
  }
}

async function onSuccess(): Promise<void> {
  if (!selected.value) return
  try {
    await ElMessageBox.confirm(
      '招领成功后对话将隐藏，关联匹配将归档为已完成。',
      '招领成功',
      {
        confirmButtonText: '确认招领',
        cancelButtonText: '取消',
        type: 'success',
      },
    )
  } catch {
    return
  }
  try {
    const res = await imApi.successSession(selected.value.id)
    ElMessage.success(res.match_archived ? '已归档至我的匹配-已完成' : '操作成功')
    selected.value = null
    selectedId.value = null
    im.reset()
    await loadSessions()
  } catch {
    /* 忽略 */
  }
}

// 轮询新消息时自动滚动到底
watch(
  () => im.messages.value.length,
  () => scrollDown(),
)

// 进入页面加载列表
loadSessions()
</script>

<style scoped>
.messages-layout {
  display: flex;
  height: calc(100vh - 220px);
  min-height: 420px;
  padding: 0;
  overflow: hidden;
}
.session-list {
  width: 300px;
  flex: 0 0 300px;
  border-right: 1px solid var(--lf-border, #ebeef5);
  overflow-y: auto;
  padding: 8px 0;
}
.list-hint {
  padding: 16px;
  text-align: center;
}
.session-item {
  display: flex;
  gap: 10px;
  padding: 12px 14px;
  cursor: pointer;
  border-bottom: 1px solid #f2f4f7;
}
.session-item:hover {
  background: #f7f9fc;
}
.session-item.active {
  background: #eef3ff;
}
.session-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: var(--lf-primary, #2f6fed);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex: 0 0 40px;
}
.session-main {
  flex: 1;
  min-width: 0;
}
.session-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.session-title {
  font-weight: 600;
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.session-time {
  font-size: 12px;
  color: #9aa4b2;
  flex: 0 0 auto;
}
.session-bottom {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}
.session-preview {
  font-size: 13px;
  color: #9aa4b2;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.unread-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #f56c6c;
  flex: 0 0 8px;
}
.chat-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.chat-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-bottom: 1px solid #f2f4f7;
}
.chat-title {
  font-weight: 600;
}
.chat-meta {
  font-size: 12px;
}
.chat-box {
  flex: 1;
  overflow-y: auto;
  background: #f7f9fc;
  padding: 12px;
}
.chat-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
.bubble-row {
  display: flex;
  flex-direction: column;
  margin-bottom: 10px;
  max-width: 80%;
}
.bubble-row.me {
  align-items: flex-end;
  margin-left: auto;
}
.bubble-row.peer {
  align-items: flex-start;
}
.bubble {
  padding: 8px 12px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.45;
  word-break: break-word;
  white-space: pre-wrap;
}
.bubble-row.me .bubble {
  background: var(--lf-primary, #2f6fed);
  color: #fff;
  border-bottom-right-radius: 2px;
}
.bubble-row.peer .bubble {
  background: #fff;
  color: #1f2733;
  border-bottom-left-radius: 2px;
}
.bubble-time {
  font-size: 11px;
  color: #9aa4b2;
  margin-top: 2px;
}
.chat-input {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  padding: 12px 16px;
  border-top: 1px solid #f2f4f7;
}
.chat-input .el-input {
  flex: 1;
}
.chat-actions {
  display: flex;
  gap: 12px;
  padding: 0 16px 14px;
}
</style>
