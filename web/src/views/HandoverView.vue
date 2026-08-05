<template>
  <div class="lf-container">
    <h2 class="lf-page-title">交接确认</h2>

    <div v-loading="loading">
      <el-empty v-if="!loading && eligible.length === 0" description="暂无可交接的匹配（需处于“认领中”状态）" />

      <template v-else>
        <div class="lf-card handover-select">
          <el-form label-position="top">
            <el-form-item label="选择匹配（认领中）">
              <el-select v-model="selectedId" placeholder="请选择" style="width: 100%" @change="onSelect">
                <el-option
                  v-for="m in eligible"
                  :key="m.id"
                  :label="`#${m.id} ${counterpartName(m)} · 匹配度 ${Math.round(m.match_score)}%`"
                  :value="m.id"
                />
              </el-select>
            </el-form-item>
          </el-form>
        </div>

        <div v-if="selected" class="lf-card handover-card">
          <!-- 生成交接码 -->
          <div class="ho-section">
            <div class="ho-section-title">
              <el-icon><Key /></el-icon> 步骤 1：生成 6 位动态交接码
            </div>
            <el-button type="primary" :loading="genLoading" @click="onGenerate">
              生成交接码
            </el-button>

            <div v-if="generatedCode" class="ho-code-box">
              <div class="ho-code">{{ generatedCode }}</div>
              <div class="lf-muted">有效期剩余：{{ countdownText }}</div>
            </div>
          </div>

          <el-divider />

          <!-- 双端验证 -->
          <div class="ho-section">
            <div class="ho-section-title">
              <el-icon><Switch /></el-icon> 步骤 2：双端验证（失主端与拾得者端各自确认）
            </div>

            <div class="ho-ends">
              <!-- 失主端 -->
              <div class="ho-end" :class="{ done: result.verified_by_lost }">
                <div class="ho-end-head">
                  <el-tag type="danger">失主端</el-tag>
                  <el-tag v-if="result.verified_by_lost" type="success" size="small">已验证</el-tag>
                </div>
                <el-input v-model="lostCode" placeholder="输入交接码" :disabled="!generatedCode" />
                <el-input v-model="lostGps" placeholder="GPS（选填）" :disabled="!generatedCode" class="ho-gps" />
                <el-button
                  type="danger"
                  plain
                  :disabled="!generatedCode || result.verified_by_lost"
                  :loading="lostLoading"
                  @click="onVerify('lost')"
                >
                  失主端验证
                </el-button>
              </div>

              <!-- 拾得者端 -->
              <div class="ho-end" :class="{ done: result.verified_by_finder }">
                <div class="ho-end-head">
                  <el-tag type="success">拾得者端</el-tag>
                  <el-tag v-if="result.verified_by_finder" type="success" size="small">已验证</el-tag>
                </div>
                <el-input v-model="finderCode" placeholder="输入交接码" :disabled="!generatedCode" />
                <el-input v-model="finderGps" placeholder="GPS（选填）" :disabled="!generatedCode" class="ho-gps" />
                <el-button
                  type="success"
                  plain
                  :disabled="!generatedCode || result.verified_by_finder"
                  :loading="finderLoading"
                  @click="onVerify('finder')"
                >
                  拾得者端验证
                </el-button>
              </div>
            </div>

            <el-result
              v-if="result.both_verified"
              icon="success"
              title="交接已完成"
              sub-title="双方均已验证，物品已确认归还，匹配闭环。"
            />
            <el-alert
              v-else-if="result.verified_by_lost || result.verified_by_finder"
              type="warning"
              :closable="false"
              show-icon
              :title="`已验证 ${verifiedCount} / 2 端，等待另一端确认`"
            />
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Key, Switch } from '@element-plus/icons-vue'
import { matchApi } from '@/api/match'
import type { LostItemOut, MatchOut, Page } from '@/types'

const loading = ref(false)
const allMatches = ref<MatchOut[]>([])

// 仅“认领中(1)”可交接
const eligible = computed(() => allMatches.value.filter((m) => m.status === 1))

const selectedId = ref<number | null>(null)
const selected = computed(() => allMatches.value.find((m) => m.id === selectedId.value) || null)

const genLoading = ref(false)
const generatedCode = ref('')
const expireAt = ref<number | null>(null)
const now = ref(Date.now())
let timer: number | undefined

const lostCode = ref('')
const finderCode = ref('')
const lostGps = ref('')
const finderGps = ref('')
const lostLoading = ref(false)
const finderLoading = ref(false)

const result = reactive({
  both_verified: false,
  verified_by_lost: false,
  verified_by_finder: false,
})

const verifiedCount = computed(
  () => (result.verified_by_lost ? 1 : 0) + (result.verified_by_finder ? 1 : 0),
)

const countdownText = computed(() => {
  if (!expireAt.value) return '—'
  const diff = Math.max(0, expireAt.value - now.value)
  const m = Math.floor(diff / 60000)
  const s = Math.floor((diff % 60000) / 1000)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
})

function counterpartName(m: MatchOut): string {
  const c = m.found_item || m.lost_item
  if (!c) return '物品'
  return (c as LostItemOut).title || c.category_name || '物品'
}

function resetState() {
  generatedCode.value = ''
  expireAt.value = null
  lostCode.value = ''
  finderCode.value = ''
  lostGps.value = ''
  finderGps.value = ''
  result.both_verified = false
  result.verified_by_lost = false
  result.verified_by_finder = false
}

function onSelect() {
  resetState()
}

async function load() {
  loading.value = true
  try {
    const res = await matchApi.myMatches({ page: 1, page_size: 100 })
    allMatches.value = (res as Page<MatchOut>).items
  } catch {
    /* 忽略 */
  } finally {
    loading.value = false
  }
}

async function onGenerate() {
  if (!selected.value) return
  genLoading.value = true
  try {
    const res = await matchApi.handoverGenerate(selected.value.id)
    generatedCode.value = res.code
    expireAt.value = new Date(res.expire_at).getTime()
    lostCode.value = res.code
    finderCode.value = res.code
    ElMessage.success(`已生成交接码：${res.code}`)
  } catch {
    /* 忽略 */
  } finally {
    genLoading.value = false
  }
}

async function onVerify(role: 'lost' | 'finder') {
  if (!selected.value) return
  const code = role === 'lost' ? lostCode.value : finderCode.value
  if (!code.trim()) {
    ElMessage.warning('请输入交接码')
    return
  }
  if (role === 'lost') lostLoading.value = true
  else finderLoading.value = true
  try {
    const res = await matchApi.handoverVerify(selected.value.id, {
      code: code.trim(),
      role,
      gps: role === 'lost' ? lostGps.value || null : finderGps.value || null,
    })
    result.both_verified = res.both_verified
    result.verified_by_lost = res.verified_by_lost
    result.verified_by_finder = res.verified_by_finder
    if (res.both_verified) {
      ElMessage.success('双方验证通过，交接完成！')
    } else {
      ElMessage.success('本端验证成功，等待另一端确认')
    }
  } catch {
    /* 忽略 */
  } finally {
    if (role === 'lost') lostLoading.value = false
    else finderLoading.value = false
  }
}

onMounted(() => {
  load()
  timer = window.setInterval(() => (now.value = Date.now()), 1000)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.handover-select {
  padding: 16px;
  margin-bottom: 14px;
}
.handover-card {
  padding: 16px;
}
.ho-section {
  margin-bottom: 8px;
}
.ho-section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  margin-bottom: 12px;
}
.ho-code-box {
  margin-top: 12px;
  text-align: center;
}
.ho-code {
  font-size: 34px;
  font-weight: 800;
  letter-spacing: 8px;
  color: var(--lf-primary);
  background: #eef3ff;
  border-radius: 10px;
  padding: 12px;
  margin-bottom: 6px;
}
.ho-ends {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
.ho-end {
  border: 1px solid var(--lf-border);
  border-radius: 12px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.ho-end.done {
  background: #f0fdf4;
  border-color: #bbf7d0;
}
.ho-end-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.ho-gps {
  margin-top: -4px;
}
@media (max-width: 640px) {
  .ho-ends {
    grid-template-columns: 1fr;
  }
}
</style>
