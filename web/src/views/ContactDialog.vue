<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    width="460px"
    @update:model-value="(v: boolean) => emit('update:modelValue', v)"
    @closed="onClosed"
  >
    <!-- 门控：对端 contact_allowed==0 → 禁用并提示 -->
    <el-alert
      v-if="gated"
      type="info"
      :closable="false"
      show-icon
      title="对方暂未开启联系"
      description="该用户关闭了“联系对方”开关，暂无法发起会话。"
    />

    <template v-else>
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
        <el-button type="primary" :loading="im.sending.value" @click="onSend">发送</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { imApi } from '@/api/im'
import { useImSession } from '@/composables/useImSession'
import { useAuthStore } from '@/stores/auth'
import type { FoundItemOut, LostItemOut, MatchOut } from '@/types'

const props = defineProps<{
  modelValue: boolean
  match?: MatchOut | null
  found?: FoundItemOut | null // v4：无 match 的联系入口（绑定具体拾物）
  foundId?: number | null
}>()
const emit = defineEmits<{ 'update:modelValue': [boolean] }>()

const auth = useAuthStore()
const myId = computed(() => auth.userId ?? -1)

const draft = ref('')
const boxRef = ref<HTMLElement | null>(null)

// v5：复用收发 composable（轮询 + 发送）
const im = useImSession()

// v4：无 match 联系入口（绑定具体拾物）时，当前用户即失主侧
const isFoundEntry = computed(() => props.foundId != null)

const myRole = computed<number>(() => {
  const m = props.match
  if (isFoundEntry.value) return 0 // 失主联系拾得者
  if (!m) return 0
  if (m.lost_item && m.lost_item.publisher_id === myId.value) return 0
  return 1
})

const counterpart = computed<LostItemOut | FoundItemOut | null>(() => {
  if (isFoundEntry.value) return props.found ?? null
  const m = props.match
  if (!m) return null
  return myRole.value === 0 ? m.found_item : m.lost_item
})

// 门控（Q5）：唯一来源为 found_item.contact_allowed（对端拾得者开关）
const gated = computed(() => {
  if (isFoundEntry.value) return props.found?.contact_allowed === 0
  return props.match?.found_item?.contact_allowed === 0
})

const title = computed(() => {
  const c = counterpart.value
  const name = c?.category_name || '对方'
  if (isFoundEntry.value) return `联系对方 · ${name}（拾物 #${props.foundId ?? ''}）`
  return `联系对方 · ${name}（匹配 #${props.match?.id ?? ''}）`
})

function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleString('zh-CN', { hour12: false })
  } catch {
    return ''
  }
}

function scrollDown() {
  nextTick(() => {
    const el = boxRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

async function init() {
  if (isFoundEntry.value) {
    if (gated.value) return
    try {
      const session = await imApi.createSession({ found_id: props.foundId as number })
      await im.initSession(session.id)
      scrollDown()
    } catch {
      ElMessage.error('无法创建会话，请稍后重试')
    }
    return
  }
  if (!props.match) return
  if (gated.value) return
  try {
    const session = await imApi.createSession({ match_id: props.match.id })
    await im.initSession(session.id)
    scrollDown()
  } catch {
    ElMessage.error('无法创建会话，请稍后重试')
  }
}

async function onSend() {
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

function onClosed() {
  im.reset()
  draft.value = ''
}

watch(
  () => im.messages.value.length,
  () => scrollDown(),
)

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      void init()
    } else {
      onClosed()
    }
  },
)
</script>

<style scoped>
.chat-box {
  height: 320px;
  overflow-y: auto;
  background: #f7f9fc;
  border-radius: 10px;
  padding: 12px;
  margin-bottom: 12px;
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
}
.chat-input .el-input {
  flex: 1;
}
</style>
