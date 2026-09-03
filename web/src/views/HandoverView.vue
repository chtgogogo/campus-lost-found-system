<template>
  <div class="lf-container">
    <h2 class="lf-page-title">交接确认（双码交叉验证）</h2>

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
          <el-alert
            v-if="!peerCode"
            type="info"
            :closable="false"
            show-icon
            title="你是当前登录用户，请在自己的一方生成码并输入对方码；对方需在其实例中完成另一半验证。"
          />
          <el-alert
            v-else
            type="warning"
            :closable="false"
            show-icon
            title="演示模式：已为你返回对方码，可点击「自动填入」单浏览器完成双方验证。"
          />

          <!-- 步骤 1：生成双方交接码 -->
          <div class="ho-section">
            <div class="ho-section-title">
              <el-icon><Key /></el-icon> 步骤 1：生成交接码（双方各 4 位）
            </div>
            <el-button type="primary" :loading="genLoading" @click="onGenerate">
              生成交接码
            </el-button>

            <div v-if="lostCode || finderCode" class="ho-codes">
              <div class="ho-code-item">
                <span class="ho-code-label">失主码</span>
                <span class="ho-code">{{ lostCode || '—' }}</span>
              </div>
              <div class="ho-code-item">
                <span class="ho-code-label">拾得者码</span>
                <span class="ho-code">{{ finderCode || '—' }}</span>
              </div>
              <div class="lf-muted">有效期剩余：{{ countdownText }}</div>
            </div>
          </div>

          <el-divider />

          <!-- 步骤 2：双方交叉验证 -->
          <div class="ho-section">
            <div class="ho-section-title">
              <el-icon><Switch /></el-icon> 步骤 2：双码交叉验证（失主输入拾得者码 / 拾得者输入失主码）
            </div>

            <div class="ho-ends">
              <!-- 失主端 -->
              <div class="ho-end" :class="{ done: lostEndVerified }">
                <div class="ho-end-head">
                  <el-tag type="danger">失主端</el-tag>
                  <el-tag v-if="lostEndVerified" type="success" size="small">已验证</el-tag>
                </div>
                <el-input v-model="lostInput" placeholder="输入拾得者码" :disabled="!lostCode" />
                <el-button
                  type="danger"
                  plain
                  :disabled="!lostCode || lostEndVerified"
                  :loading="lostLoading"
                  @click="onVerify('lost')"
                >
                  失主端验证
                </el-button>
              </div>

              <!-- 拾得者端 -->
              <div class="ho-end" :class="{ done: finderEndVerified }">
                <div class="ho-end-head">
                  <el-tag type="success">拾得者端</el-tag>
                  <el-tag v-if="finderEndVerified" type="success" size="small">已验证</el-tag>
                </div>
                <el-input v-model="finderInput" placeholder="输入失主码" :disabled="!finderCode" />
                <el-button
                  type="success"
                  plain
                  :disabled="!finderCode || finderEndVerified"
                  :loading="finderLoading"
                  @click="onVerify('finder')"
                >
                  拾得者端验证
                </el-button>
              </div>
            </div>

            <el-button
              v-if="peerCode"
              link
              type="primary"
              class="ho-fill"
              :disabled="!lostCode || !finderCode"
              @click="fillDemo"
            >
              自动填入双方码（演示）
            </el-button>

            <el-result
              v-if="result.both_verified"
              icon="success"
              title="交接已完成"
              sub-title="双方双码交叉验证通过，物品已确认归还，匹配闭环。"
            />
            <el-alert
              v-else-if="lostEndVerified || finderEndVerified"
              type="warning"
              :closable="false"
              show-icon
              :title="`已验证 ${lostEndVerified ? 1 : 0} / 2 端，等待另一端确认`"
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
import { useAuthStore } from '@/stores/auth'
import type { LostItemOut, MatchOut, Page } from '@/types'

const auth = useAuthStore()
const userId = computed(() => auth.userId ?? -1)

const loading = ref(false)
const allMatches = ref<MatchOut[]>([])

// 仅“认领中(1)”可交接
const eligible = computed(() => allMatches.value.filter((m) => m.status === 1))

const selectedId = ref<number | null>(null)
const selected = computed(() => allMatches.value.find((m) => m.id === selectedId.value) || null)

// 当前用户在此匹配中的身份（显示用）：lost=失主 / found=拾得者
const myRole = computed<'lost' | 'found'>(() => {
  const m = selected.value
  if (!m) return 'lost'
  if (m.lost_item && m.lost_item.publisher_id === userId.value) return 'lost'
  return 'found'
})
const myRoleLabel = computed(() => (myRole.value === 'lost' ? '失主' : '拾得者'))

const genLoading = ref(false)
const lostCode = ref('') // 失主码（展示）
const finderCode = ref('') // 拾得者码（展示）
const peerCode = ref<string | null>(null) // 演示模式：对方码
const expireAt = ref<number | null>(null)
const now = ref(Date.now())
let timer: number | undefined

const lostInput = ref('') // 失主端输入（应填拾得者码）
const finderInput = ref('') // 拾得者端输入（应填失主码）
const lostLoading = ref(false)
const finderLoading = ref(false)

const result = reactive({
  both_verified: false,
  lost_code_verified: false,
  finder_code_verified: false,
})

// 失主端验证 → 设置 finder_code_verified；拾得者端验证 → 设置 lost_code_verified
const lostEndVerified = computed(() => result.finder_code_verified)
const finderEndVerified = computed(() => result.lost_code_verified)

const countdownText = computed(() => {
  if (!expireAt.value) return '—'
  const diff = Math.max(0, expireAt.value - now.value)
  const s = Math.floor(diff / 1000)
  return `${String(s).padStart(2, '0')}秒`
})

function counterpartName(m: MatchOut): string {
  const c = m.found_item || m.lost_item
  if (!c) return '物品'
  return (c as LostItemOut).title || c.category_name || '物品'
}

function resetState() {
  lostCode.value = ''
  finderCode.value = ''
  peerCode.value = null
  expireAt.value = null
  lostInput.value = ''
  finderInput.value = ''
  result.both_verified = false
  result.lost_code_verified = false
  result.finder_code_verified = false
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
    // res.role: lost/finder；res.code 是我的码；peer_code 仅演示模式有（对方的码）
    const myCode = res.code
    const peer = res.peer_code ?? null
    if (res.role === 'lost') {
      lostCode.value = myCode
      finderCode.value = peer ?? ''
    } else {
      finderCode.value = myCode
      lostCode.value = peer ?? ''
    }
    peerCode.value = peer
    expireAt.value = new Date(res.expire_at).getTime()
    ElMessage.success(`已生成交接码（${res.role === 'lost' ? '失主' : '拾得者'}）`)
  } catch {
    /* 忽略 */
  } finally {
    genLoading.value = false
  }
}

function fillDemo() {
  // 演示：自动把对方码填入双方输入框，便于单浏览器完成交叉验证
  lostInput.value = finderCode.value
  finderInput.value = lostCode.value
}

async function onVerify(role: 'lost' | 'finder') {
  if (!selected.value) return
  const code = role === 'lost' ? lostInput.value : finderInput.value
  if (!code.trim()) {
    ElMessage.warning('请输入对方交接码')
    return
  }
  if (role === 'lost') lostLoading.value = true
  else finderLoading.value = true
  try {
    const res = await matchApi.handoverVerify(selected.value.id, {
      code: code.trim(),
      role,
      gps: null,
    })
    result.both_verified = res.both_verified
    result.lost_code_verified = res.lost_code_verified
    result.finder_code_verified = res.finder_code_verified
    if (res.both_verified) {
      ElMessage.success('双码交叉验证通过，交接完成！')
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
.ho-codes {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 18px;
}
.ho-code-item {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ho-code-label {
  color: var(--lf-muted);
  font-size: 13px;
}
.ho-code {
  font-size: 28px;
  font-weight: 800;
  letter-spacing: 6px;
  color: var(--lf-primary);
  background: #eef3ff;
  border-radius: 10px;
  padding: 8px 14px;
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
.ho-fill {
  margin-top: 10px;
}
@media (max-width: 640px) {
  .ho-ends {
    grid-template-columns: 1fr;
  }
}
</style>
