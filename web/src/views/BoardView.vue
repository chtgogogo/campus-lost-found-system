<template>
  <div class="lf-container">
    <h2 class="lf-page-title">公示栏</h2>

    <!-- 过滤区 -->
    <div class="board-filter lf-card">
      <el-radio-group v-model="typeFilter" size="default">
        <el-radio-button value="all">全部</el-radio-button>
        <el-radio-button value="lost">失物</el-radio-button>
        <el-radio-button value="found">拾物</el-radio-button>
        <el-radio-button value="resolved">已完成交接</el-radio-button>
      </el-radio-group>

      <el-input
        v-if="typeFilter !== 'resolved'"
        v-model="keyword"
        placeholder="搜索标题 / 描述"
        clearable
        style="flex: 1; min-width: 160px"
        :prefix-icon="Search"
      />
      <el-input
        v-else
        v-model="resolvedKeyword"
        placeholder="搜索已完成的拾物交接记录"
        clearable
        style="flex: 1; min-width: 160px"
        :prefix-icon="Search"
      />
    </div>

    <!-- 列表 -->
    <div v-loading="loading" class="board-grid">
      <ItemCard
        v-for="it in pagedItems"
        :key="it.kind + '-' + it.data.id"
        :item="it"
        :resolved="typeFilter === 'resolved'"
        :counterpart="counterpartFor(it)"
        :completed-at="completedAtFor(it)"
        :revokable="revokableFor(it)"
        @click="openDetail(it)"
        @contact="onContact"
        @apply-match="onApplyMatch"
        @revoke="onRevoke"
      />
    </div>

    <el-empty
      v-if="!loading && filteredItems.length === 0"
      :description="typeFilter === 'resolved' ? '暂无已完成的拾物交接记录' : '暂无符合条件的物品'"
    />

    <div class="board-pager" v-if="filteredItems.length > pageSize">
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="filteredItems.length"
        layout="prev, pager, next"
        background
      />
    </div>

    <!-- 详情弹窗 -->
    <el-dialog v-model="detailVisible" :title="detailTitle" width="520px">
      <div v-if="current">
        <el-carousel v-if="current.data.images.length" height="240px" indicator-position="outside">
          <el-carousel-item v-for="(img, i) in current.data.images" :key="i">
            <img :src="fullImageUrl(img)" class="detail-img" alt="物品图片" />
          </el-carousel-item>
        </el-carousel>
        <div v-else class="detail-noimg lf-muted">无图片</div>

        <el-descriptions :column="1" border class="detail-desc">
          <el-descriptions-item label="类型">
            {{ current.kind === 'lost' ? '失物' : '拾物' }}
          </el-descriptions-item>
          <el-descriptions-item label="分类">
            {{ current.data.category_name || '未分类' }}
          </el-descriptions-item>
          <el-descriptions-item v-if="current.kind === 'lost'" label="标题">
            {{ (current.data as LostItemOut).title }}
          </el-descriptions-item>
          <el-descriptions-item label="描述">
            {{ current.data.description || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="标签">
            <template v-if="current.data.tags && current.data.tags.length">
              <el-tag
                v-for="t in current.data.tags"
                :key="t"
                size="small"
                type="info"
                class="detail-tag"
              >
                {{ t }}
              </el-tag>
            </template>
            <span v-else class="lf-muted">—</span>
          </el-descriptions-item>
          <!-- v8：外观 / 特征 / 地点 结构化字段 -->
          <el-descriptions-item label="外观">
            {{ current.data.appearance || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="特征">
            {{ current.data.features || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="地点">
            {{ current.data.location || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="时间">
            {{
              formatChineseDateTime(
                current.kind === 'lost'
                  ? (current.data as LostItemOut).lost_time
                  : (current.data as FoundItemOut).found_time
              )
            }}
          </el-descriptions-item>
        </el-descriptions>
        <p class="lf-muted detail-tip">
          公示栏已对联系方式脱敏，如需认领请通过“发布”匹配后在我们平台内沟通。
        </p>
      </div>
    </el-dialog>

    <!-- v4：无 match 联系（绑定具体拾物，强溯源） -->
    <ContactDialog
      v-model="contactVisible"
      :found="contactFound"
      :found-id="contactFoundId"
    />

    <!-- v4：申请匹配 —— 选择我方进行中的失物（keep1 留在原地的拾物申请后立即完成交接，R2） -->
    <el-dialog v-model="applyVisible" title="申请匹配 · 选择我的失物" width="480px">
      <p class="lf-muted" style="margin-top: 0">
        请选择你正在寻找的失物发起申请匹配；留在原地未挪动的拾物，申请后将立即完成交接（可随时撤回）。
      </p>
      <el-radio-group v-model="applyLostId" class="apply-lost-group">
        <el-radio
          v-for="l in myProgressLost"
          :key="l.id"
          :value="l.id"
          class="apply-lost-item"
        >
          <span class="apply-lost-title">{{ l.title || l.category_name }}</span>
          <span class="lf-muted apply-lost-cat">{{ l.category_name }}</span>
        </el-radio>
      </el-radio-group>
      <template #footer>
        <el-button @click="applyVisible = false">取消</el-button>
        <el-button
          type="success"
          :disabled="!applyLostId"
          :loading="applyLoading"
          @click="submitApplyMatch"
        >
          确认申请
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import ItemCard, { type BoardItem } from '@/components/ItemCard.vue'
import { itemsApi } from '@/api/items'
import { matchApi } from '@/api/match'
import { fullImageUrl } from '@/api/request'
import { formatChineseDateTime } from '@/utils/format'
import { useAuthStore } from '@/stores/auth'
import type { FoundItemOut, LostItemOut, MatchOut, Page } from '@/types'
import ContactDialog from '@/views/ContactDialog.vue'

const loading = ref(false)
const typeFilter = ref<'all' | 'lost' | 'found' | 'resolved'>('all')
const keyword = ref('')
const resolvedKeyword = ref('')
const page = ref(1)
const pageSize = 8

const auth = useAuthStore()
const myId = computed(() => auth.userId ?? -1)

const lostItems = ref<LostItemOut[]>([])
const foundItems = ref<FoundItemOut[]>([])
const resolvedFound = ref<FoundItemOut[]>([])

// v6/v2：「已完成交接」tab 的匹配对方索引：found:{id} → 对方失物 + 完成时间 + 关联 match（撤回入口用）
type CounterpartEntry = {
  item: LostItemOut | FoundItemOut
  completedAt: string
  matchId: number
  flowType: number
}
const counterpartIndex = ref<Record<string, CounterpartEntry>>({})

const merged = computed<BoardItem[]>(() => {
  // P0 保底：即使后端未过滤，也硬性排除已解决项
  // 失物已解决 = status===3（LostItemStatus.RESOLVED）；拾物已解决 = status===1（FoundItemStatus.RESOLVED）
  const lost: BoardItem[] = lostItems.value
    .filter((d) => d.status !== 3)
    .map((d) => ({ kind: 'lost' as const, data: d }))
  const found: BoardItem[] = foundItems.value
    .filter((d) => d.status !== 1)
    .map((d) => ({ kind: 'found' as const, data: d }))
  return [...lost, ...found].sort((a, b) =>
    (b.data.created_at || '').localeCompare(a.data.created_at || ''),
  )
})

// R1（2026-08-05）：已完成交接 tab 只展示已解决**拾物**（FoundItem.status==1）；
// 对方失物信息由 counterpart 索引（MatchRecord status=2）提供，不再拼接失物卡片（去重）。
const resolvedMerged = computed<BoardItem[]>(() =>
  resolvedFound.value
    .filter((d) => d.status === 1)
    .map((d) => ({ kind: 'found' as const, data: d }))
    .sort((a, b) => (b.data.created_at || '').localeCompare(a.data.created_at || '')),
)

// v6：「已完成交接」tab 卡片的匹配对方与完成时间（仅该 tab 生效）
function counterpartFor(it: BoardItem): LostItemOut | FoundItemOut | null {
  if (typeFilter.value !== 'resolved') return null
  const key = it.kind === 'lost' ? `lost:${it.data.id}` : `found:${it.data.id}`
  return counterpartIndex.value[key]?.item ?? null
}

function completedAtFor(it: BoardItem): string | undefined {
  if (typeFilter.value !== 'resolved') return undefined
  const key = it.kind === 'lost' ? `lost:${it.data.id}` : `found:${it.data.id}`
  return counterpartIndex.value[key]?.completedAt
}

// v2（2026-08-05）：已完成交接 tab 的 keep1 撤回入口（仅拾物卡片 + flowType=1 + 失主本人）
function revokableFor(it: BoardItem): boolean {
  if (typeFilter.value !== 'resolved' || it.kind !== 'found') return false
  const entry = counterpartIndex.value[`found:${it.data.id}`]
  if (!entry || entry.flowType !== 1) return false
  const counterpart = entry.item as LostItemOut
  return counterpart.publisher_id === myId.value
}

async function onRevoke(it: BoardItem) {
  const entry = counterpartIndex.value[`found:${it.data.id}`]
  if (!entry) return
  try {
    await ElMessageBox.confirm(
      '撤回后该拾物将恢复可申请。',
      '撤回完成记录',
      {
        confirmButtonText: '撤回',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }
  try {
    await matchApi.revoke(entry.matchId)
    ElMessage.success('已撤回，该拾物恢复可申请')
    await load()
  } catch {
    /* 错误已由拦截器提示 */
  }
}

const filteredItems = computed(() => {
  if (typeFilter.value === 'resolved') {
    const k = resolvedKeyword.value.trim().toLowerCase()
    return resolvedMerged.value.filter((it) => {
      if (!k) return true
      const hay = (
        (it.kind === 'lost' ? (it.data as LostItemOut).title : '') +
        ' ' +
        (it.data.description || '')
      ).toLowerCase()
      return hay.includes(k)
    })
  }
  return merged.value.filter((it) => {
    if (typeFilter.value !== 'all' && it.kind !== typeFilter.value) return false
    if (keyword.value.trim()) {
      const k = keyword.value.trim().toLowerCase()
      const hay = (
        (it.kind === 'lost' ? (it.data as LostItemOut).title : '') +
        ' ' +
        (it.data.description || '')
      ).toLowerCase()
      if (!hay.includes(k)) return false
    }
    return true
  })
})

const pagedItems = computed(() => {
  const start = (page.value - 1) * pageSize
  return filteredItems.value.slice(start, start + pageSize)
})

const detailVisible = ref(false)
const current = ref<BoardItem | null>(null)
const detailTitle = computed(() =>
  current.value?.kind === 'lost'
    ? (current.value.data as LostItemOut).title || '失物详情'
    : '拾物详情',
)

function openDetail(it: BoardItem) {
  current.value = it
  detailVisible.value = true
}

// ---------------- v4：无 match 联系 / 申请匹配（未挪动自取） ----------------
// 联系：绑定到具体拾物（强溯源）
const contactVisible = ref(false)
const contactFound = ref<FoundItemOut | null>(null)
const contactFoundId = ref<number | null>(null)

function onContact(found: FoundItemOut) {
  contactFound.value = found
  contactFoundId.value = found.id
  contactVisible.value = true
}

// 申请匹配：选择我方“进行中”的失物（status ∈ {0,1}）发起待自取匹配
const myProgressLost = ref<LostItemOut[]>([])
const applyVisible = ref(false)
const applyLostId = ref<number | null>(null)
const applyFoundId = ref<number | null>(null)
const applyLoading = ref(false)

async function loadMyProgressLost() {
  try {
    const res = await itemsApi.myPublished()
    const lost = (res as { lost: LostItemOut[] }).lost || []
    myProgressLost.value = lost.filter((l) => l.status === 0 || l.status === 1)
  } catch {
    /* 忽略 */
  }
}

function onApplyMatch(found: FoundItemOut) {
  applyFoundId.value = found.id
  applyLostId.value = null
  if (myProgressLost.value.length === 0) {
    ElMessage.warning('请先发布您的失物，再进行申请匹配')
    return
  }
  applyVisible.value = true
}

async function submitApplyMatch() {
  if (!applyLostId.value || applyFoundId.value == null) return
  applyLoading.value = true
  try {
    const m = await matchApi.createManual(applyLostId.value, applyFoundId.value)
    // v2（2026-08-05）：keep1（留在原地未挪动）分流为一步完成；keep0 仍为待自取
    if (m.flow_type === 1 || m.status === 2) {
      ElMessage.success(`已申请并完成交接（匹配度 ${Math.round(m.match_score)}）`)
    } else {
      ElMessage.success(`已发起待自取匹配（匹配度 ${Math.round(m.match_score)}）`)
    }
    applyVisible.value = false
    await loadMyProgressLost()
  } catch {
    /* 错误已由拦截器提示 */
  } finally {
    applyLoading.value = false
  }
}

async function load() {
  loading.value = true
  try {
    const [lost, found, rFound, completed] = await Promise.all([
      // 主三 tab：排除已解决（后端过滤 + merged 前端 P0 保底）
      itemsApi.listLost({ exclude_resolved: true, page: 1, page_size: 100 }),
      itemsApi.listFound({ exclude_resolved: true, page: 1, page_size: 100 }),
      // R1：已完成交接 tab 仅拉已解决拾物（不再拉 resolvedLost，避免同笔交接双卡）
      itemsApi.listFound({ resolved_only: true, page: 1, page_size: 100 }),
      // Q3：已完成匹配（status=2）用于构建 counterpart 索引（含 matchId/flowType 供撤回入口）
      matchApi.myMatches({ status: 2, page: 1, page_size: 100 }),
    ])
    lostItems.value = (lost as Page<LostItemOut>).items
    foundItems.value = (found as Page<FoundItemOut>).items
    resolvedFound.value = (rFound as Page<FoundItemOut>).items
    // 构建 counterpart 索引：拾物卡片(id=found_id) → 对方失物；
    // 完成时间取 completed_at || created_at（修正现状用 created_at 的小问题）；
    // 索引带 matchId/flowType 供撤回入口使用（R1 + P2-1）。
    const idx: Record<string, CounterpartEntry> = {}
    const matches = (completed as Page<MatchOut>).items
    for (const m of matches) {
      if (m.lost_item) {
        idx[`found:${m.found_id}`] = {
          item: m.lost_item,
          completedAt: m.completed_at || m.created_at,
          matchId: m.id,
          flowType: m.flow_type ?? 0,
        }
      }
    }
    counterpartIndex.value = idx
  } catch {
    /* 错误已由拦截器提示 */
  } finally {
    loading.value = false
  }
}

watch([typeFilter, keyword, resolvedKeyword], () => {
  page.value = 1
})

onMounted(() => {
  load()
  loadMyProgressLost()
})
</script>

<style scoped>
.board-filter {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.board-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 14px;
  min-height: 120px;
}
.board-pager {
  display: flex;
  justify-content: center;
  margin-top: 18px;
}
.detail-img {
  width: 100%;
  height: 240px;
  object-fit: cover;
  border-radius: 8px;
}
.detail-noimg {
  height: 240px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f4f6fb;
  border-radius: 8px;
}
.detail-desc {
  margin-top: 14px;
}
.detail-tag {
  margin: 0 6px 6px 0;
}
.detail-tip {
  font-size: 12px;
  margin-top: 10px;
}
.apply-lost-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.apply-lost-item {
  height: auto;
  padding: 8px 4px;
  white-space: normal;
}
.apply-lost-title {
  font-weight: 600;
  margin-right: 8px;
}
.apply-lost-cat {
  font-size: 12px;
}
</style>
