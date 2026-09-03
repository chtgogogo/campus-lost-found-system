<template>
  <div class="lf-container">
    <div class="lf-page-title-row">
      <h2 class="lf-page-title">我的匹配</h2>
      <!-- P2-1：刷新候选入口（对当前用户未解决失物逐个增量补候选） -->
      <el-button size="small" plain :loading="refreshLoading" @click="onRefreshCandidates">
        刷新候选
      </el-button>
    </div>

    <el-tabs v-model="tab" class="lf-tabs">
      <el-tab-pane label="进行中" name="active" />
      <el-tab-pane label="已完成" name="done" />
    </el-tabs>

    <!-- P2-2：候选上限提示（部分失物已达 10 条候选上限） -->
    <el-alert
      v-if="anyLostAtCap && tab === 'active'"
      type="warning"
      :closable="false"
      show-icon
      class="lf-cap-alert"
      title="部分失物已达 10 条候选上限，查看更多请前往拾物广场。"
    />

    <div v-loading="loading">
      <el-empty v-if="!loading && visibleMatches.length === 0" :description="emptyText" />

      <div
        v-for="m in visibleMatches"
        :key="m.id"
        class="match-card lf-card"
        :class="{ 'match-card--low': isLowScore(m) }"
      >
        <div class="match-score">
          <el-progress
            type="circle"
            :width="62"
            :percentage="Math.min(100, Math.round(m.match_score))"
            :color="scoreColor(m.match_score)"
            :stroke-width="7"
          />
          <div class="match-score-label">匹配度</div>
        </div>

        <div class="match-main">
          <div class="match-head">
            <el-tag size="small" :type="myRole(m) === 'lost' ? 'danger' : 'success'">
              {{ myRole(m) === 'lost' ? '我是失主' : '我是拾得者' }}
            </el-tag>
            <el-tag size="small" :type="statusType(m.status)">{{ MATCH_STATUS_LABEL[m.status] }}</el-tag>
            <!-- flow-v3：低分候选弱化标签（suspected 语义不变，前端用 match_score<60 独立派生） -->
            <el-tag v-if="isLowScore(m)" size="small" type="warning" effect="plain">低匹配度·谨慎申请</el-tag>
            <span v-if="m.suspected" class="lf-muted match-sus">疑似匹配</span>
            <!-- v11：CLIP 后台精排过渡态（图片相似度计算中，稍后刷新可见最终排序） -->
            <el-tooltip
              v-if="isClipPending(m)"
              content="系统正在比对双方照片相似度，稍后刷新可见最终排序"
              placement="top"
            >
              <el-tag size="small" type="info" effect="plain">AI 精排中…</el-tag>
            </el-tooltip>
          </div>

          <!-- 对方物品 -->
          <div class="counterpart">
            <img
              v-if="counterpart(m)?.images?.length"
              :src="fullImageUrl(counterpart(m)!.images[0])"
              class="counterpart-img"
              alt="对方物品"
            />
            <div class="counterpart-info">
              <div class="counterpart-cat">
                <el-tag size="small" effect="plain">{{ counterpart(m)?.category_name || '未分类' }}</el-tag>
                <span class="lf-muted">{{ myRole(m) === 'lost' ? '拾得者发布的拾物' : '失主发布的失物' }}</span>
              </div>
              <div class="counterpart-title">
                {{ myRole(m) === 'lost' ? '拾物' : (counterpart(m) as LostItemOut)?.title || '失物' }}
              </div>
              <div class="lf-muted counterpart-desc">{{ counterpart(m)?.description || '—' }}</div>
              <!-- v8：匹配对方物品的外观 / 特征 / 地点（T8 结构化字段） -->
              <div v-if="counterpartExtra(m)" class="lf-muted counterpart-extra">{{ counterpartExtra(m) }}</div>
            </div>
          </div>

          <!-- 三重融合：失物/拾物共享特征（可解释匹配依据） -->
          <div v-if="m.shared_attributes && m.shared_attributes.length" class="match-shared">
            <span class="lf-muted match-shared-label">共享特征：</span>
            <el-tag
              v-for="tag in m.shared_attributes"
              :key="tag"
              size="small"
              type="info"
              effect="light"
              class="match-shared-tag"
            >{{ tag }}</el-tag>
          </div>

          <!-- v2（2026-08-05）：共享文字词（R4 可解释：命中相似词越多分越高） -->
          <div v-if="m.shared_text && m.shared_text.length" class="match-shared">
            <span class="lf-muted match-shared-label">共享文字：</span>
            <el-tag
              v-for="w in m.shared_text"
              :key="w"
              size="small"
              type="warning"
              effect="plain"
              class="match-shared-tag"
            >{{ w }}</el-tag>
          </div>

          <!-- v10：匹配维度明细（分类 20 / 文字 70 可展开 5 子项 / 时间 10；flow-v2 五维与 v8 六维自动回退） -->
          <div v-if="hasDimensions(m)" class="match-dims">
            <div class="match-dims-head">
              <span class="lf-muted match-dims-label">匹配维度：</span>
              <el-tag v-if="m.suspected" size="small" type="warning" effect="light">疑似匹配</el-tag>
              <el-tag
                v-for="label in signalLabels(m)"
                :key="label"
                size="small"
                type="danger"
                effect="dark"
                class="match-signal-tag"
              >{{ label }}</el-tag>
              <span class="match-dims-total">总分 {{ m.total }}/100</span>
            </div>
            <template v-for="dim in dimsFor(m)" :key="dim.key">
              <div class="match-dim">
                <span class="match-dim-label">
                  {{ dim.label }}
                  <el-button
                    v-if="isV2(m) && dim.key === 'text'"
                    link
                    size="small"
                    class="match-dim-toggle"
                    @click="toggleTextDims(m.id)"
                  >{{ expandedText.has(m.id) ? '收起' : '展开' }}</el-button>
                </span>
                <el-progress
                  :percentage="dimPercent(m, dim)"
                  :stroke-width="6"
                  :show-text="false"
                  class="match-dim-bar"
                />
                <span class="match-dim-val">{{ m[dim.key] }}/{{ dim.weight }}</span>
              </div>
              <!-- 文字 70 的 5 个子维度（量词/颜色/状态/地点/关键词），展开后显示 -->
              <div
                v-for="sub in (dim.key === 'text' && expandedText.has(m.id) ? textSubDims(m) : [])"
                :key="sub.key"
                class="match-dim match-dim-sub"
              >
                <span class="match-dim-label">{{ sub.label }}</span>
                <el-progress
                  :percentage="dimPercent(m, sub)"
                  :stroke-width="4"
                  :show-text="false"
                  class="match-dim-bar"
                />
                <span class="match-dim-val">{{ m[sub.key] }}/{{ sub.weight }}</span>
              </div>
            </template>
            <div v-if="normHint(m)" class="match-dims-norm lf-muted">{{ normHint(m) }}</div>
          </div>

          <div v-if="m.claim_reason" class="match-reason lf-muted">
            认领理由：{{ m.claim_reason }}
          </div>

          <!-- 操作区 -->
          <div class="match-actions">
            <template v-if="myRole(m) === 'lost'">
              <!-- P0-3/Q3：失主侧 status=0 统一主按钮（低分先二次确认）；
                   flow-v3：keep1（留在原地未挪动）候选文案改为「我要领走」，点击走 claim-complete 一步完成 -->
              <el-button
                v-if="m.status === 0"
                type="primary"
                size="small"
                @click="onApplyMatch(m)"
              >
                {{ isKeep1Candidate(m) ? '我要领走' : '申请匹配' }}
              </el-button>
              <el-button
                v-else-if="m.status === 1"
                type="warning"
                size="small"
                @click="goHandover"
              >
                去交接确认
              </el-button>
              <el-button
                v-else-if="m.status === 4"
                type="success"
                size="small"
                @click="onSelfComplete(m)"
              >
                完成匹配
              </el-button>
              <span v-else-if="m.status === 2" class="lf-muted">交接已完成</span>
              <span v-else-if="m.status === 6" class="lf-muted match-revoked">已撤回</span>
              <span v-else class="lf-muted">已拒绝</span>
              <!-- v2（2026-08-05）：keep1 完成记录「撤回」（仅 flow_type=1 && status=2；status=6 灰显无操作） -->
              <el-button
                v-if="canRevoke(m)"
                size="small"
                type="danger"
                plain
                @click="onRevoke(m)"
              >
                撤回
              </el-button>
              <!-- v5：未能找回（失主侧仅 status 0/1/4 显示，终态 2/3 隐藏，纯前端判断）。
                   flow-v3（§2.7 R-2 重构）：移入失主 template 内部，避免打断下方 v-if / v-else-if 角色链 -->
              <el-button
                v-if="[0, 1, 4].includes(m.status)"
                size="small"
                plain
                type="danger"
                @click="onGiveUp(m)"
              >
                未能找回
              </el-button>
            </template>

            <template v-else-if="myRole(m) === 'found'">
              <template v-if="m.status === 0">
                <!-- flow-v3 U2=完全隐藏：keep1 候选已在后端 as_found 分支过滤，拾得者侧不可见；
                     此处仅渲染 keep0 候选的操作按钮（确认归还 / 拒绝），无需 isKeep1 分支 -->
                <el-button type="success" size="small" @click="onConfirmReturn(m)">确认归还</el-button>
                <el-button type="danger" size="small" plain @click="onReject(m)">拒绝</el-button>
              </template>
              <!-- Q3 闭环：失主申请后（status=1）拾得者侧显示「确认归还/拒绝」 -->
              <template v-else-if="m.status === 1">
                <el-button type="success" size="small" @click="onConfirmReturn(m)">确认归还</el-button>
                <el-button type="danger" size="small" plain @click="onReject(m)">拒绝</el-button>
              </template>
              <span v-else-if="m.status === 4" class="lf-muted">待失主自取完成</span>
              <span v-else-if="m.status === 2" class="lf-muted">交接已完成</span>
              <span v-else-if="m.status === 6" class="lf-muted match-revoked">已撤回</span>
              <span v-else class="lf-muted">已拒绝</span>
            </template>

            <!-- v3 需求 D：联系对方（对端 contact_allowed==0 置灰） -->
            <el-tooltip
              v-if="isGated(m)"
              content="对方暂未开启联系"
              placement="top"
            >
              <span class="contact-btn-wrap">
                <el-button size="small" plain disabled>联系对方</el-button>
              </span>
            </el-tooltip>
            <el-button
              v-else
              size="small"
              plain
              type="primary"
              @click="openContact(m)"
            >
              联系对方
            </el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- 认领理由弹窗 -->
    <el-dialog v-model="claimVisible" title="填写认领理由" width="480px">
      <el-input
        v-model="claimReason"
        type="textarea"
        :rows="4"
        placeholder="请填写认领理由与独有凭证（如物品特征、序列号等），必填"
      />
      <template #footer>
        <el-button @click="claimVisible = false">取消</el-button>
        <el-button type="primary" :loading="claimLoading" @click="submitClaim">提交认领</el-button>
      </template>
    </el-dialog>

    <!-- v3 需求 D：联系对方对话框 -->
    <ContactDialog v-model="contactVisible" :match="contactMatch" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { matchApi } from '@/api/match'
import { itemsApi } from '@/api/items'
import { fullImageUrl } from '@/api/request'
import {
  MATCH_DIM_LABEL,
  MATCH_LOW_SCORE,
  MATCH_SIGNAL_LABEL,
  MATCH_STATUS_LABEL,
  MATCH_TEXT_MAX,
  MATCH_TOP_N,
  MATCH_WEIGHTS,
  MATCH_WEIGHTS_V2,
} from '@/api/constants'
import { useAuthStore } from '@/stores/auth'
import ContactDialog from '@/views/ContactDialog.vue'
import type { FoundItemOut, LostItemOut, MatchOut, Page } from '@/types'

const router = useRouter()
const auth = useAuthStore()

const loading = ref(false)
const matches = ref<MatchOut[]>([])
const tab = ref<'active' | 'done'>('active')

const claimVisible = ref(false)
const claimLoading = ref(false)
const claimReason = ref('')
const activeMatch = ref<MatchOut | null>(null)

const contactVisible = ref(false)
const contactMatch = ref<MatchOut | null>(null)

// P2-1：刷新候选按钮 loading 态
const refreshLoading = ref(false)

const myId = computed(() => auth.userId ?? -1)

// Q10 / Q7：Match 进行中={0,1,4(待自取)}/已完成={2,3,6(已撤回)}
const visibleMatches = computed<MatchOut[]>(() =>
  matches.value.filter((m) =>
    (tab.value === 'active' ? [0, 1, 4] : [2, 3, 6]).includes(m.status),
  ),
)

const emptyText = computed(() =>
  tab.value === 'active'
    ? '暂时没有符合匹配的项。可完善物品外观/特征/地点信息后点「刷新候选」，或前往拾物广场浏览。'
    : '暂无已完成的匹配。',
)

// flow-v3：低分判定（独立视觉阈值 MATCH_LOW_SCORE=60）。
// 仅驱动失主侧弱化视觉（弱化标签 / 虚线卡片 / 低分二次确认），与后端 suspected(80) 完全解耦；
// 拾得者侧不存在任何低分判定（「低分不打扰」已整体删除）。
function isLowScore(m: MatchOut): boolean {
  return m.match_score < MATCH_LOW_SCORE
}

// v11（2026-08-27）：CLIP 精排过渡态——进行中候选且图片相似度尚未算完
// （发布后后台任务几秒内完成，刷新列表即消失；CLIP 不可用则恒为 null，不影响展示）。
function isClipPending(m: MatchOut): boolean {
  return m.status === 0 && m.clip_sim == null
}

// flow-v3：keep1（留在原地未挪动）候选判定。
// 失主侧 → 主按钮文案「我要领走」（走 claim-complete 一步完成）。
// U2=完全隐藏：拾得者侧不再看到 keep1 候选（后端 as_found 分支已过滤），此函数仅用于失主侧。
function isKeep1Candidate(m: MatchOut): boolean {
  return m.found_item?.keep_status === 1
}

// P2-2：候选上限提示——进行中列表按 lost_id 分组，任一组数量 ≥ MATCH_TOP_N 时提示
const anyLostAtCap = computed(() => {
  const counts = new Map<number, number>()
  for (const m of visibleMatches.value) {
    counts.set(m.lost_id, (counts.get(m.lost_id) ?? 0) + 1)
  }
  return [...counts.values()].some((n) => n >= MATCH_TOP_N)
})

function myRole(m: MatchOut): 'lost' | 'found' | null {
  if (m.lost_item && m.lost_item.publisher_id === myId.value) return 'lost'
  if (m.found_item && m.found_item.finder_id === myId.value) return 'found'
  return null
}

function counterpart(m: MatchOut): LostItemOut | FoundItemOut | null {
  const role = myRole(m)
  if (role === 'lost') return m.found_item
  if (role === 'found') return m.lost_item
  return m.found_item || m.lost_item
}

// 门控（Q5）：唯一来源为 found_item.contact_allowed（对端拾得者开关）
function isGated(m: MatchOut): boolean {
  return m.found_item?.contact_allowed === 0
}

// ---------------- v10 评分引擎 v2：匹配维度明细 ----------------
// 顶层展示三条：分类 20 / 文字 70 / 时间 10；文字 70 可展开为 5 个子项。
// 旧记录（无 photo_category 键）自动回退到 flow-v2 五维 / v8 六维，保证历史数据不崩溃。
interface MatchDimension {
  key: keyof MatchOut
  label: string
  weight: number
}

/** v10 顶层三维（分类 / 文字 / 时间） */
const V2_TOP_DIMENSIONS: MatchDimension[] = [
  { key: 'photo_category', label: '照片/分类', weight: MATCH_WEIGHTS_V2.photo_category },
  { key: 'text', label: '文字描述', weight: MATCH_TEXT_MAX },
  { key: 'time', label: '时间', weight: MATCH_WEIGHTS_V2.time },
]

/** v10 文字 70 的 5 个子维度（展开后显示） */
const V2_TEXT_SUB_DIMENSIONS: MatchDimension[] = [
  { key: 'qty', label: MATCH_DIM_LABEL.qty, weight: MATCH_WEIGHTS_V2.qty },
  { key: 'color', label: MATCH_DIM_LABEL.color, weight: MATCH_WEIGHTS_V2.color },
  { key: 'state', label: MATCH_DIM_LABEL.state, weight: MATCH_WEIGHTS_V2.state },
  { key: 'place', label: MATCH_DIM_LABEL.place, weight: MATCH_WEIGHTS_V2.place },
  { key: 'keyword', label: MATCH_DIM_LABEL.keyword, weight: MATCH_WEIGHTS_V2.keyword },
]

// [deprecated] flow-v2 五维：仅当记录无 v10 键但有 text 键时回退
const MATCH_DIMENSIONS: MatchDimension[] = [
  { key: 'photo', label: '图像', weight: MATCH_WEIGHTS.photo },
  { key: 'category', label: '类别', weight: MATCH_WEIGHTS.category },
  { key: 'text', label: '文字', weight: MATCH_WEIGHTS.text },
  { key: 'location', label: '地点', weight: MATCH_WEIGHTS.location },
  { key: 'time', label: '时间', weight: MATCH_WEIGHTS.time },
]
// 旧六维（v8）：仅当历史记录无 text 键时回退渲染，保证旧记录不崩溃
const OLD_MATCH_DIMENSIONS: MatchDimension[] = [
  { key: 'photo', label: '图像', weight: 20 },
  { key: 'category', label: '类别', weight: 30 },
  { key: 'appearance', label: '外观', weight: 20 },
  { key: 'feature', label: '特征', weight: 15 },
  { key: 'time', label: '时间', weight: 10 },
  { key: 'location', label: '地点', weight: 5 },
]

/** 该记录是否为 v10 评分引擎 v2 产出（存在 photo_category 数值键即为 v2）。 */
function isV2(m: MatchOut): boolean {
  return typeof m.photo_category === 'number'
}

// 维度区是否可渲染（v2 键 → v2；text 键 → flow-v2 五维；appearance/feature → v8 六维；否则隐藏）
function hasDimensions(m: MatchOut): boolean {
  if (isV2(m)) return true
  if (typeof m.text === 'number') return true
  return typeof m.appearance === 'number' || typeof m.feature === 'number'
}

function dimsFor(m: MatchOut): MatchDimension[] {
  if (isV2(m)) return V2_TOP_DIMENSIONS
  return typeof m.text === 'number' ? MATCH_DIMENSIONS : OLD_MATCH_DIMENSIONS
}

/** 文字 70 的子维度列表（仅 v2 记录有）。 */
function textSubDims(m: MatchOut): MatchDimension[] {
  return isV2(m) ? V2_TEXT_SUB_DIMENSIONS : []
}

// 单维占比（相对权重，封顶 100%）
function dimPercent(m: MatchOut, dim: MatchDimension): number {
  const v = (m[dim.key] as number) ?? 0
  return Math.max(0, Math.min(100, Math.round((v / dim.weight) * 100)))
}

// ---- v10：冲突信号角标 + 归一化提示 ----
/** 该候选的冲突信号中文文案列表（signals 为空则不展示角标）。 */
function signalLabels(m: MatchOut): string[] {
  return (m.signals || []).map((s) => MATCH_SIGNAL_LABEL[s] || s)
}

/** 归一化提示：k>1 说明失主描述不完整，分数已按「实际填写的维度」重新归一到 100。 */
function normHint(m: MatchOut): string {
  if (!isV2(m) || typeof m.norm_factor !== 'number' || m.norm_factor <= 1.0001) return ''
  const raw = typeof m.raw_total === 'number' ? m.raw_total : 0
  return `原始分 ${raw}/100，已按你填写的 ${(m.provided_dims || []).length} 个维度归一（×${m.norm_factor}）`
}

/** 文字 70 子项展开状态（按 match id 记忆，默认收起，避免卡片过高）。 */
const expandedText = ref<Set<number>>(new Set())
function toggleTextDims(id: number): void {
  const next = new Set(expandedText.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedText.value = next
}

// v8：匹配对方物品的外观/特征/地点拼接（T8 在匹配卡片内展示）
function counterpartExtra(m: MatchOut): string {
  const c = counterpart(m)
  if (!c) return ''
  const parts: string[] = []
  if (c.appearance) parts.push(`外观：${c.appearance}`)
  if (c.features) parts.push(`特征：${c.features}`)
  if (c.location) parts.push(`地点：${c.location}`)
  return parts.join('；')
}

function scoreColor(score: number): string {
  if (score >= 90) return '#16a34a'
  if (score >= 80) return '#2f6fed'
  return '#f59e0b'
}

function statusType(status: number): '' | 'success' | 'warning' | 'info' | 'danger' {
  switch (status) {
    case 0:
      return 'warning'
    case 1:
      return ''
    case 2:
      return 'success'
    case 3:
      return 'info'
    case 4:
      return 'info' // 待自取（v4）
    case 6:
      return 'info' // 已撤回（v2：keep1 撤回终态，灰显）
    default:
      return ''
  }
}

async function load() {
  loading.value = true
  try {
    // P1-4：page_size 200（对齐后端 /matches le=200，多件失物 × 10 候选场景）
    const res = await matchApi.myMatches({ page: 1, page_size: 200 })
    matches.value = (res as Page<MatchOut>).items
  } catch {
    /* 忽略 */
  } finally {
    loading.value = false
  }
}

function openClaim(m: MatchOut) {
  activeMatch.value = m
  claimReason.value = ''
  claimVisible.value = true
}

// P0-3/Q4：低分候选「申请匹配」二次确认后再弹认领理由；高分直接弹认领理由（流程零变化）
// flow-v3：keep1（留在原地未挪动）候选「我要领走」= 一步完成（claim-complete，不填理由）。
// ⚠️ keep1 分支必须早退在低分判定之前：低分 keep1 只弹「确认领走」，不叠加低分二次确认。
async function onApplyMatch(m: MatchOut) {
  if (isKeep1Candidate(m)) {
    try {
      await ElMessageBox.confirm(
        '该拾物留在原地未挪动，确认后将立即标记为已完成交接（可随时撤回）。',
        '确认领走',
        {
          confirmButtonText: '确认领走',
          cancelButtonText: '取消',
          type: 'warning',
        },
      )
    } catch {
      return
    }
    try {
      await matchApi.claimComplete(m.id)
      ElMessage.success('已完成交接，请前往原地取回物品')
      await load()
    } catch {
      /* 忽略 */
    }
    return
  }
  if (isLowScore(m)) {
    try {
      await ElMessageBox.confirm(
        `该候选匹配度较低（<${MATCH_LOW_SCORE}），请确认对方物品与你的失物一致后谨慎申请。`,
        '低匹配度申请',
        {
          confirmButtonText: '继续申请',
          cancelButtonText: '取消',
          type: 'warning',
        },
      )
    } catch {
      return
    }
  }
  openClaim(m)
}

// v2（2026-08-05）：keep1 完成记录可撤回（仅失主侧、flow_type=1 && status=2；keep0 无撤回入口）
function canRevoke(m: MatchOut): boolean {
  return myRole(m) === 'lost' && m.status === 2 && m.flow_type === 1
}

async function onRevoke(m: MatchOut) {
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
    await matchApi.revoke(m.id)
    ElMessage.success('已撤回，该拾物恢复可申请')
    await load()
  } catch {
    /* 忽略 */
  }
}

// P2-1：刷新候选——遍历当前用户未解决失物逐个增量补候选（候选满 10 条的后端幂等返回，不报错）
async function onRefreshCandidates() {
  refreshLoading.value = true
  try {
    let lostIds: number[] = []
    try {
      const mine = await itemsApi.myPublished()
      lostIds = (mine.lost || [])
        .filter((l) => l.status !== 3 && !l.deleted_at)
        .map((l) => l.id)
    } catch {
      // 兜底：退化为遍历当前列表去重后的 lost_id（局限：无候选的失物不会被刷新）
      lostIds = [...new Set(matches.value.map((m) => m.lost_id))]
    }
    for (const id of lostIds) {
      try {
        await matchApi.refreshMatches(id)
      } catch {
        /* 单条失败（已解决/已删除等）不阻断整体刷新 */
      }
    }
    ElMessage.success('候选已刷新')
    await load()
  } catch {
    ElMessage.error('候选刷新失败')
  } finally {
    refreshLoading.value = false
  }
}

async function submitClaim() {
  if (!claimReason.value.trim()) {
    ElMessage.warning('认领理由必填')
    return
  }
  if (!activeMatch.value) return
  claimLoading.value = true
  try {
    await matchApi.claim(activeMatch.value.id, {
      claim_reason: claimReason.value.trim(),
    })
    ElMessage.success('认领成功，等待交接')
    claimVisible.value = false
    await load()
  } catch {
    /* 忽略 */
  } finally {
    claimLoading.value = false
  }
}

async function onConfirmReturn(m: MatchOut) {
  try {
    await matchApi.confirmReturn(m.id)
    ElMessage.success('已确认归还')
    await load()
  } catch {
    /* 忽略 */
  }
}

async function onReject(m: MatchOut) {
  try {
    await matchApi.reject(m.id)
    ElMessage.success('已拒绝该认领')
    await load()
  } catch {
    /* 忽略 */
  }
}

// v4：失主单边完成「待自取」匹配（不调双码交接）
async function onSelfComplete(m: MatchOut) {
  try {
    await matchApi.selfComplete(m.id)
    ElMessage.success('已确认自取完成')
    await load()
  } catch {
    /* 忽略 */
  }
}

function openContact(m: MatchOut) {
  if (isGated(m)) {
    ElMessage.warning('对方暂未开启联系')
    return
  }
  contactMatch.value = m
  contactVisible.value = true
}

function goHandover() {
  router.push('/handover')
}

// v5：未能找回（失主放弃匹配，软删 status=5 + 失物重入匹配池）
async function onGiveUp(m: MatchOut) {
  try {
    await ElMessageBox.confirm(
      '确定「未能找回」吗？该匹配将被撤销，关联失物会重新进入匹配池。',
      '未能找回',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }
  try {
    await matchApi.giveup(m.id)
    ElMessage.success('已退回匹配池，可重新发起匹配')
    await load()
  } catch {
    /* 忽略 */
  }
}

onMounted(load)
</script>

<style scoped>
.lf-page-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.lf-tabs {
  margin-bottom: 12px;
}
.lf-cap-alert {
  margin-bottom: 12px;
}
/* 2026-08-05 增量：低分候选弱化样式（灰/橙虚线边框 + 浅底色） */
.match-card--low {
  border: 1px dashed var(--lf-warn, #f59e0b);
  background: #fffdf7;
}
.match-card {
  display: flex;
  gap: 16px;
  padding: 16px;
  margin-bottom: 14px;
}
.match-score {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 0 0 80px;
}
.match-score-label {
  font-size: 12px;
  color: var(--lf-text-sub);
  margin-top: 4px;
}
.match-main {
  flex: 1;
  min-width: 0;
}
.match-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.match-sus {
  font-size: 12px;
}
/* v2（2026-08-05）：status=6 已撤回灰显 */
.match-revoked {
  color: #b0b8c4;
}
.counterpart {
  display: flex;
  gap: 12px;
  background: #f7f9fc;
  border-radius: 10px;
  padding: 10px;
}
.counterpart-img {
  width: 88px;
  height: 88px;
  object-fit: cover;
  border-radius: 8px;
  flex: 0 0 88px;
}
.counterpart-info {
  min-width: 0;
}
.counterpart-cat {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.counterpart-title {
  font-weight: 600;
  margin-bottom: 2px;
}
.counterpart-desc {
  font-size: 13px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.match-reason {
  font-size: 13px;
  margin-top: 10px;
}
.match-shared {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.match-shared-label {
  font-size: 13px;
}
.match-shared-tag {
  font-weight: 500;
}
.match-dims {
  margin-top: 10px;
  background: #f7f9fc;
  border-radius: 10px;
  padding: 10px;
}
.match-dims-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.match-dims-label {
  font-size: 13px;
}
.match-dims-total {
  margin-left: auto;
  font-size: 13px;
  font-weight: 600;
  color: var(--lf-text-sub);
}
.match-dim {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.match-dim:last-child {
  margin-bottom: 0;
}
.match-dim-label {
  /* v10：标签从「图像/类别」的 2 字扩到「照片/分类」+ 展开按钮，需要更宽 */
  flex: 0 0 96px;
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #606266;
}
.match-dim-bar {
  flex: 1;
  margin-bottom: 0;
}
.match-dim-val {
  flex: 0 0 56px;
  text-align: right;
  font-size: 12px;
  color: #606266;
}
/* v10：文字 70 展开后的 5 个子维度（缩进 + 弱化，视觉上从属于「文字描述」） */
.match-dim-sub {
  padding-left: 16px;
  opacity: 0.85;
}
.match-dim-sub .match-dim-label {
  flex: 0 0 80px;
  font-size: 11px;
}
.match-dim-toggle {
  padding: 0;
  height: auto;
  font-size: 11px;
}
/* v10：color_conflict / state_conflict 红色角标 */
.match-signal-tag {
  font-weight: 600;
}
/* v10：归一化说明（失主描述不完整时解释「为什么分数被放大」） */
.match-dims-norm {
  margin-top: 8px;
  font-size: 11px;
  line-height: 1.5;
}
.counterpart-extra {
  font-size: 12px;
  margin-top: 6px;
  line-height: 1.45;
}
.match-actions {
  margin-top: 12px;
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}
.contact-btn-wrap {
  display: inline-flex;
}
</style>
