<template>
  <div class="item-card lf-card" @click="$emit('click')">
    <div class="item-thumb-wrap">
      <img
        v-if="firstImage"
        :src="firstImage"
        class="lf-thumb"
        alt="物品图片"
      />
      <div v-else class="item-thumb-empty">
        <el-icon><Picture /></el-icon>
      </div>
      <span class="item-kind" :class="kind">{{ kindLabel }}</span>
    </div>

    <div class="item-body">
      <div class="item-title-row">
        <el-tag size="small" effect="light" type="primary">{{ data.category_name || '未分类' }}</el-tag>
        <span class="item-status" :class="statusClass">{{ statusLabel }}</span>
        <span v-if="isResolved" class="item-resolved-badge">{{ RESOLVED_BADGE_LABEL }}</span>
      </div>

      <div class="item-title">{{ title }}</div>
      <div class="item-desc lf-muted">{{ description }}</div>

      <div v-if="tags.length" class="item-tags">
        <el-tag
          v-for="t in tags"
          :key="t"
          size="small"
          effect="plain"
          type="info"
          class="item-tag"
        >
          {{ t }}
        </el-tag>
      </div>

      <!-- v8：外观 / 特征 / 地点 结构化字段（任一存在即展示为一行可读文本） -->
      <div v-if="extraInfo" class="item-extra lf-muted">{{ extraInfo }}</div>

      <div class="item-meta lf-muted">
        <span><el-icon><Clock /></el-icon> {{ timeText }}</span>
      </div>

      <!-- v7：失效倒计时（红色小字；N<=0 不渲染，因后端已过滤隐藏） -->
      <div v-if="expiresInDays !== null" class="item-expiry">失效时间：{{ expiresInDays }}天</div>

      <!-- v6：「已完成交接」tab 展示增强：匹配对方 + 完成时间 -->
      <div v-if="counterpartSummary" class="item-counterpart lf-muted">
        交接配对：{{ counterpartSummary }}<template v-if="counterpartTitle">（{{ counterpartTitle }}）</template>
      </div>
      <div v-if="completedAtText" class="item-completed-at lf-muted">
        完成时间：{{ completedAtText }}
      </div>

      <!-- v2（2026-08-05）：keep1 完成记录「撤回」入口（仅已完成交接 tab 且 flowType=1 且失主本人） -->
      <div v-if="revokable" class="item-actions">
        <el-button size="small" type="danger" plain @click.stop="emit('revoke', props.item)">
          撤回
        </el-button>
      </div>

      <!-- v4：拾物行动区（仅他人发布的拾物显示） -->
      <div v-if="kind === 'found' && !isMyFound && !isResolved" class="item-actions">
        <template v-if="(data as FoundItemOut).keep_status === 0">
          <!-- 暂为保管：强制开启联系，仅“联系” -->
          <el-button size="small" type="primary" plain @click.stop="emit('contact', foundItem)">
            联系
          </el-button>
        </template>
        <template v-else>
          <!-- 未挪动：可申请匹配；若开启联系也可“联系” -->
          <el-button size="small" type="success" plain @click.stop="emit('applyMatch', foundItem)">
            申请匹配
          </el-button>
          <el-button
            v-if="(data as FoundItemOut).contact_allowed === 1"
            size="small"
            type="primary"
            plain
            @click.stop="emit('contact', foundItem)"
          >
            联系
          </el-button>
        </template>
      </div>

      <!-- v7：我的发布删除按钮 -->
      <div v-if="showDelete" class="item-actions item-delete-row">
        <el-button size="small" type="danger" plain @click.stop="emit('delete', props.item)">
          删除
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { fullImageUrl } from '@/api/request'
import { formatChineseDateTime } from '@/utils/format'
import {
  FOUND_STATUS_LABEL,
  KEEP_STATUS_LABEL,
  LOST_STATUS_LABEL,
  RESOLVED_BADGE_LABEL,
} from '@/api/constants'
import { useAuthStore } from '@/stores/auth'
import type { FoundItemOut, LostItemOut } from '@/types'

export interface BoardItem {
  kind: 'lost' | 'found'
  data: LostItemOut | FoundItemOut
}

const props = defineProps<{
  item: BoardItem
  /** 是否渲染「已完成交接」徽标（仅「已完成交接」tab 传 true） */
  resolved?: boolean
  /** 匹配对方物品（复用 MatchOut.lost_item / found_item），用于展示交接配对 */
  counterpart?: LostItemOut | FoundItemOut | null
  /** 交接完成时间（ISO 字符串） */
  completedAt?: string
  /** v2：keep1 完成记录是否可撤回（仅已完成交接 tab 传 true） */
  revokable?: boolean
  /** v7：是否显示删除按钮（我的发布页传 true） */
  showDelete?: boolean
}>()
const emit = defineEmits<{
  click: []
  contact: [FoundItemOut]
  applyMatch: [FoundItemOut]
  delete: [BoardItem]
  revoke: [BoardItem]
}>()

const auth = useAuthStore()
const myId = computed(() => auth.userId ?? -1)

const kind = computed(() => props.item.kind)
const data = computed(() => props.item.data)
const kindLabel = computed(() => (kind.value === 'lost' ? '失物' : '拾物'))
const foundItem = computed(() => data.value as FoundItemOut)
// 不对自己发布的拾物展示行动按钮
const isMyFound = computed(() => kind.value === 'found' && foundItem.value.finder_id === myId.value)

const firstImage = computed(() => {
  const imgs = data.value.images || []
  return imgs.length ? fullImageUrl(imgs[0]) : ''
})

const title = computed(() => {
  if (kind.value === 'lost') return (data.value as LostItemOut).title || '未命名失物'
  return '拾物招领'
})

const description = computed(() => {
  const d = data.value.description || ''
  return d.length > 48 ? d.slice(0, 48) + '…' : d
})

// v3：结构化标签 chips（视觉 label + 颜色词 + 地点词）
const tags = computed<string[]>(() => {
  const t = (data.value as LostItemOut | FoundItemOut).tags
  return Array.isArray(t) ? (t as string[]) : []
})

// v8：外观/特征/地点拼接为一行可读文本（任一存在即展示）
const extraInfo = computed<string>(() => {
  const d = data.value as LostItemOut | FoundItemOut
  const parts: string[] = []
  if (d.appearance) parts.push(`外观：${d.appearance}`)
  if (d.features) parts.push(`特征：${d.features}`)
  if (d.location) parts.push(`地点：${d.location}`)
  return parts.join('；')
})

const statusLabel = computed(() => {
  if (kind.value === 'lost') {
    const s = (data.value as LostItemOut).status
    return LOST_STATUS_LABEL[s] ?? '未知'
  }
  const f = data.value as FoundItemOut
  if (f.status === 1) return FOUND_STATUS_LABEL[1]
  // 待认领时额外展示保管状态
  return `${FOUND_STATUS_LABEL[0]} · ${KEEP_STATUS_LABEL[f.keep_status] ?? ''}`
})

const statusClass = computed(() => {
  const s = kind.value === 'lost' ? (data.value as LostItemOut).status : (data.value as FoundItemOut).status
  return `s${s}`
})

const timeText = computed(() => {
  const t =
    kind.value === 'lost'
      ? (data.value as LostItemOut).lost_time
      : (data.value as FoundItemOut).found_time
  return formatChineseDateTime(t)
})

// ---------------- v6：「已完成交接」tab 展示增强 ----------------
const isResolved = computed(() => props.resolved === true)

// 对方物品与卡片自身类型相反：卡片为失物 → 对方是拾物；卡片为拾物 → 对方是失物
const counterpartKindLabel = computed(() => {
  if (!props.counterpart) return ''
  return kind.value === 'lost' ? '拾物' : '失物'
})

const counterpartTitle = computed(() => {
  if (!props.counterpart) return ''
  const c = props.counterpart as LostItemOut | FoundItemOut
  if ('title' in c && c.title) return c.title
  return '拾物招领'
})

const counterpartSummary = computed(() => {
  if (!props.counterpart) return ''
  const c = props.counterpart as LostItemOut | FoundItemOut
  const cat = c.category_name || '未分类'
  return `${counterpartKindLabel.value} · ${cat}`
})

const completedAtText = computed(() => {
  if (!props.completedAt) return ''
  return formatChineseDateTime(props.completedAt)
})

// v7：失效倒计时（天），N = ceil((expires_at - now)/86400000)；N<=0 或缺失返回 null（不渲染）
const expiresInDays = computed<number | null>(() => {
  const exp = (data.value as LostItemOut | FoundItemOut).expires_at
  if (!exp) return null
  const diff = new Date(exp).getTime() - Date.now()
  if (diff <= 0) return null
  return Math.ceil(diff / 86400000)
})
</script>

<style scoped>
.item-card {
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
  display: flex;
  flex-direction: column;
}
.item-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 26px rgba(31, 39, 51, 0.1);
}
.item-thumb-wrap {
  position: relative;
  width: 100%;
  aspect-ratio: 4 / 3;
  background: #eef1f7;
}
.item-thumb-empty {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 40px;
  color: #c2cad6;
}
.item-kind {
  position: absolute;
  top: 8px;
  left: 8px;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 999px;
  color: #fff;
}
.item-kind.lost {
  background: #ef4444;
}
.item-kind.found {
  background: #16a34a;
}
.item-body {
  padding: 10px 12px 12px;
}
.item-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.item-status {
  font-size: 12px;
}
.item-status.s0 {
  color: #6b7785;
}
.item-status.s1 {
  color: #2f6fed;
}
.item-status.s2 {
  color: #f59e0b;
}
.item-status.s3 {
  color: #16a34a;
}
.item-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.item-desc {
  font-size: 13px;
  line-height: 1.4;
  height: 36px;
  overflow: hidden;
}
.item-extra {
  font-size: 12px;
  margin-top: 6px;
  line-height: 1.45;
}
.item-meta {
  display: flex;
  gap: 12px;
  font-size: 12px;
  margin-top: 8px;
}
.item-meta span {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
.item-resolved-badge {
  margin-left: auto;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 999px;
  color: #fff;
  background: #16a34a;
  white-space: nowrap;
}
.item-counterpart,
.item-completed-at {
  font-size: 12px;
  margin-top: 6px;
  line-height: 1.4;
}
.item-actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed #e7ebf2;
}
.item-expiry {
  font-size: 12px;
  margin-top: 6px;
  color: #ef4444;
  font-weight: 500;
}
.item-delete-row {
  justify-content: flex-end;
  border-top: 1px dashed #e7ebf2;
}
</style>
