<template>
  <div class="lf-container">
    <!-- ⚠️ 合规提示：本页所有手机号/导出文件均为明文，仅 role=1 可见 -->
    <el-alert
      type="warning"
      :closable="false"
      show-icon
      title="敏感信息合规提示"
      description="本页用户手机号与取证导出文件均为明文，仅管理员可见。请勿截屏外传，导出后按校方留存规范保管。"
      style="margin-bottom: 14px"
    />

    <el-tabs v-model="activeTab" class="admin-tabs">
      <!-- ============ D1：用户列表 ============ -->
      <el-tab-pane label="用户管理" name="users">
        <div class="lf-toolbar">
          <el-input
            v-model="userKeyword"
            placeholder="学号 / 手机号 / 姓名"
            clearable
            size="small"
            style="width: 220px"
            @keyup.enter="loadUsers(1)"
            @clear="loadUsers(1)"
          />
          <el-select
            v-model="userRole"
            placeholder="角色"
            clearable
            size="small"
            style="width: 130px"
            @change="loadUsers(1)"
          >
            <el-option label="普通用户" :value="0" />
            <el-option label="管理员" :value="1" />
          </el-select>
          <el-select
            v-model="userStatus"
            placeholder="状态"
            clearable
            size="small"
            style="width: 130px"
            @change="loadUsers(1)"
          >
            <el-option label="正常" :value="0" />
            <el-option label="封禁" :value="1" />
          </el-select>
          <el-button type="primary" size="small" :loading="userLoading" @click="loadUsers(1)">
            查询
          </el-button>
        </div>

        <el-alert
          v-if="userBackendMissing"
          type="info"
          :closable="false"
          show-icon
          title="后端未暴露 /admin/users 接口"
          description="当前后端未提供用户列表接口；开启“演示数据”可查看本地示例用户。"
          style="margin-bottom: 14px"
        />

        <div v-loading="userLoading">
          <el-empty v-if="!userLoading && users.length === 0" description="暂无用户" />
          <el-table v-else :data="users" border size="small">
            <el-table-column prop="id" label="ID" width="70" />
            <el-table-column prop="student_no" label="学号" min-width="120" />
            <el-table-column label="姓名" width="100">
              <template #default="{ row }">{{ row.real_name || '—' }}</template>
            </el-table-column>
            <el-table-column label="手机号（明文）" min-width="130">
              <template #default="{ row }">
                <span class="plain-phone">{{ row.phone }}</span>
              </template>
            </el-table-column>
            <el-table-column label="角色" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="row.role === 1 ? 'danger' : 'info'">
                  {{ row.role === 1 ? '管理员' : '普通' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="信用分" width="90">
              <template #default="{ row }">{{ row.credit_score }}</template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="row.status === 1 ? 'danger' : 'success'">
                  {{ row.status === 1 ? '封禁' : '正常' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="注册时间" width="170" />
          </el-table>

          <el-pagination
            v-if="userTotal > userPageSize"
            class="lf-pager"
            layout="prev, pager, next, total"
            :current-page="userPage"
            :page-size="userPageSize"
            :total="userTotal"
            @current-change="loadUsers"
          />
        </div>
      </el-tab-pane>

      <!-- ============ D2 + D3 + D4：匹配记录 / 详情 / 导出 ============ -->
      <el-tab-pane label="匹配记录" name="matches">
        <div class="lf-toolbar">
          <el-select
            v-model="matchStatus"
            placeholder="状态筛选"
            clearable
            size="small"
            style="width: 130px"
            @change="loadMatches"
          >
            <el-option
              v-for="(label, idx) in MATCH_STATUS_LABELS"
              :key="idx"
              :label="label"
              :value="idx"
            />
          </el-select>
          <!-- D4：all_time 默认关闭，保持 v7 的 270 天留存窗行为 -->
          <el-checkbox v-model="allTime" size="small" @change="loadMatches">
            含历史（跳过留存窗）
          </el-checkbox>
          <el-button size="small" :loading="matchLoading" @click="loadMatches">刷新</el-button>
          <el-button size="small" :loading="cleaning" @click="onCleanup">触发周期清理</el-button>
        </div>

        <!-- D3：导出范围 × 格式 -->
        <div class="lf-toolbar export-bar">
          <span class="lf-muted">导出范围</span>
          <el-select v-model="exportScope" size="small" style="width: 150px">
            <el-option label="双方资料" value="profile" />
            <el-option label="对话记录" value="conversation" />
            <el-option label="全部" value="all" />
          </el-select>
          <span class="lf-muted">格式</span>
          <el-select v-model="exportFormat" size="small" style="width: 110px">
            <el-option label="CSV" value="csv" />
            <el-option label="XLSX" value="xlsx" />
            <el-option label="Markdown" value="md" />
          </el-select>
          <el-button
            type="primary"
            size="small"
            :disabled="selectedIds.length === 0"
            :loading="exporting"
            @click="onExportMatches"
          >
            导出选中（{{ selectedIds.length }}）
          </el-button>
        </div>

        <el-alert
          v-if="matchBackendMissing"
          type="info"
          :closable="false"
          show-icon
          title="后端未暴露 /admin/matches 接口"
          description="当前后端未提供管理员匹配接口；开启“演示数据”可查看本地示例未失效匹配。"
          style="margin-bottom: 14px"
        />

        <div v-loading="matchLoading">
          <el-empty v-if="!matchLoading && matches.length === 0" description="暂无匹配记录" />
          <el-table v-else :data="matches" border size="small" @selection-change="onSelectionChange">
            <el-table-column type="selection" width="44" />
            <el-table-column prop="id" label="匹配ID" width="80" />
            <el-table-column label="失物" min-width="120">
              <template #default="{ row }">{{ row.lost_item?.title || '—' }}</template>
            </el-table-column>
            <el-table-column label="拾物" min-width="120">
              <template #default="{ row }">{{ row.found_item?.title || '—' }}</template>
            </el-table-column>
            <el-table-column label="分数" width="80">
              <template #default="{ row }">{{ formatScore(row.match_score) }}</template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag size="small">{{ matchStatusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="完成时间" width="170">
              <template #default="{ row }">{{ row.completed_at || '—' }}</template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" width="170" />
            <el-table-column label="操作" width="90" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="openDetail(row.id)">
                  详情
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <!-- ============ v7：审计日志 ============ -->
      <el-tab-pane label="审计日志" name="audit">
        <div class="lf-toolbar">
          <el-button type="primary" size="small" :loading="exporting" @click="onExport('csv')">
            导出 CSV
          </el-button>
          <el-button size="small" :loading="exporting" @click="onExport('json')">
            导出 JSON
          </el-button>
        </div>

        <el-alert
          v-if="backendMissing"
          type="info"
          :closable="false"
          show-icon
          title="后端未暴露审计日志接口"
          description="当前后端 app/routers 未提供 /audit-logs 接口，本页在“演示数据”开启时展示本地示例审计流；开启演示数据即可查看完整时间线。"
          style="margin-bottom: 14px"
        />

        <div v-loading="loading">
          <el-empty v-if="!loading && logs.length === 0" description="暂无审计记录" />

          <el-timeline v-else class="audit-timeline">
            <el-timeline-item
              v-for="log in logs"
              :key="log.id"
              :timestamp="formatTime(log.created_at)"
              placement="top"
              :type="actionType(log.action)"
              :hollow="log.action === 'handover_verify'"
            >
              <div class="lf-card audit-item">
                <div class="audit-head">
                  <el-tag size="small" :type="actionType(log.action)">
                    {{ auditActionLabel(log.action) }}
                  </el-tag>
                  <span class="lf-muted audit-target">
                    目标：{{ log.target_type || '—' }} #{{ log.target_id ?? '—' }}
                  </span>
                  <span v-if="log.user_id" class="lf-muted audit-uid">
                    操作人 #{{ log.user_id }}
                  </span>
                </div>
                <div class="audit-row lf-muted">
                  <span><el-icon><LocationFilled /></el-icon> IP：{{ log.ip || '—' }}</span>
                </div>
                <div v-if="log.detail" class="audit-detail">
                  <span class="lf-muted">原文摘要：</span>
                  <code>{{ log.detail }}</code>
                </div>
                <div v-if="log.ua" class="audit-ua lf-muted">UA：{{ truncate(log.ua, 60) }}</div>
              </div>
            </el-timeline-item>
          </el-timeline>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- ============ D2：匹配详情抽屉 ============ -->
    <el-drawer v-model="detailVisible" title="匹配详情（取证视图）" size="46%">
      <div v-loading="detailLoading">
        <el-empty v-if="!detailLoading && !detail" description="未获取到详情" />
        <template v-else-if="detail">
          <el-descriptions :column="2" border size="small" title="匹配">
            <el-descriptions-item label="匹配ID">{{ detail.match.id }}</el-descriptions-item>
            <el-descriptions-item label="分数">
              {{ formatScore(detail.match.match_score) }}
            </el-descriptions-item>
            <el-descriptions-item label="状态">
              {{ matchStatusLabel(detail.match.status) }}
            </el-descriptions-item>
            <el-descriptions-item label="创建时间">
              {{ detail.match.created_at }}
            </el-descriptions-item>
            <el-descriptions-item label="失物">
              {{ detail.match.lost_item?.title || '—' }}
            </el-descriptions-item>
            <!-- FoundItemOut 无 title 字段：沿用 MatchesView 的「类目名」展示约定，
                 描述作为兜底，避免出现空白单元格。 -->
            <el-descriptions-item label="拾物">
              {{ detail.match.found_item?.category_name || detail.match.found_item?.description || '—' }}
            </el-descriptions-item>
          </el-descriptions>

          <el-descriptions
            v-for="side in userSides"
            :key="side.key"
            :column="2"
            border
            size="small"
            :title="side.title"
            style="margin-top: 16px"
          >
            <template v-if="side.user">
              <el-descriptions-item label="用户ID">{{ side.user.id }}</el-descriptions-item>
              <el-descriptions-item label="学号">{{ side.user.student_no }}</el-descriptions-item>
              <el-descriptions-item label="姓名">
                {{ side.user.real_name || '—' }}
              </el-descriptions-item>
              <el-descriptions-item label="手机号（明文）">
                <span class="plain-phone">{{ side.user.phone }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="信用分">
                {{ side.user.credit_score }}
              </el-descriptions-item>
              <el-descriptions-item label="状态">
                {{ side.user.status === 1 ? '封禁' : '正常' }}
              </el-descriptions-item>
            </template>
            <el-descriptions-item v-else label="信息">该侧用户信息缺失</el-descriptions-item>
          </el-descriptions>

          <h4 class="conv-title">对话记录（{{ detail.conversation.length }} 条）</h4>
          <el-empty
            v-if="detail.conversation.length === 0"
            description="双方无对话记录"
            :image-size="70"
          />
          <div v-else class="conv-list">
            <div
              v-for="(msg, i) in detail.conversation"
              :key="i"
              class="conv-item"
              :class="{ 'conv-finder': msg.sender_role === 1 }"
            >
              <div class="conv-meta lf-muted">
                <!-- role_label 由后端下发，前端不再做角色映射 -->
                <strong>{{ msg.role_label }}</strong>
                <span>{{ msg.sent_at || '—' }}</span>
              </div>
              <div class="conv-body">{{ msg.content }}</div>
            </div>
          </div>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { LocationFilled } from '@element-plus/icons-vue'
import { matchApi } from '@/api/match'
import { adminApi } from '@/api/admin'
import { auditActionLabel } from '@/api/constants'
import type {
  AdminMatchDetailOut,
  AdminUserOut,
  AuditLog,
  ExportFormat,
  ExportScope,
  MatchOut,
  Page,
} from '@/types'

/** 匹配状态中文名（索引即 status 值，与后端 MatchRecord.status 对齐）。 */
const MATCH_STATUS_LABELS = [
  '待认领',
  '认领中',
  '已完成',
  '已拒绝',
  '待自取',
  '已放弃',
  '已撤回',
] as const

const activeTab = ref<'users' | 'matches' | 'audit'>('users')

// ---------------- D1：用户列表 ----------------
const users = ref<AdminUserOut[]>([])
const userLoading = ref(false)
const userBackendMissing = ref(false)
const userKeyword = ref('')
const userRole = ref<number | undefined>(undefined)
const userStatus = ref<number | undefined>(undefined)
const userPage = ref(1)
const userPageSize = ref(20)
const userTotal = ref(0)

async function loadUsers(page = 1): Promise<void> {
  userPage.value = page
  userLoading.value = true
  userBackendMissing.value = false
  try {
    const res = await adminApi.listUsers({
      keyword: userKeyword.value || undefined,
      role: userRole.value,
      status: userStatus.value,
      page,
      page_size: userPageSize.value,
    })
    const pageData = res as Page<AdminUserOut>
    users.value = pageData.items
    userTotal.value = pageData.total
  } catch {
    userBackendMissing.value = true
    users.value = []
    userTotal.value = 0
  } finally {
    userLoading.value = false
  }
}

// ---------------- v7 + D4：匹配列表 ----------------
const matches = ref<MatchOut[]>([])
const matchLoading = ref(false)
const matchBackendMissing = ref(false)
const matchStatus = ref<number | undefined>(undefined)
const allTime = ref(false)
const selectedIds = ref<number[]>([])
const cleaning = ref(false)

function onSelectionChange(rows: MatchOut[]): void {
  selectedIds.value = rows.map((r) => r.id)
}

function matchStatusLabel(s: number): string {
  return MATCH_STATUS_LABELS[s] ?? String(s)
}

function formatScore(s: number | null | undefined): string {
  return typeof s === 'number' ? s.toFixed(2) : '—'
}

async function loadMatches(): Promise<void> {
  matchLoading.value = true
  matchBackendMissing.value = false
  try {
    const res = await adminApi.listAdminMatches({
      status: matchStatus.value,
      // 仅在勾选时传 true：不传即保持 v7 的 270 天留存窗（C-4 向后兼容）
      all_time: allTime.value || undefined,
      page: 1,
      page_size: 100,
    })
    matches.value = (res as Page<MatchOut>).items
  } catch {
    matchBackendMissing.value = true
    matches.value = []
  } finally {
    matchLoading.value = false
  }
}

// ---------------- D2：匹配详情抽屉 ----------------
const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<AdminMatchDetailOut | null>(null)

/** 抽屉里「失主 / 拾得者」两块资料的统一渲染源，避免模板重复。 */
const userSides = computed(() => [
  { key: 'lost', title: '失主资料', user: detail.value?.lost_user ?? null },
  { key: 'found', title: '拾得者资料', user: detail.value?.found_user ?? null },
])

async function openDetail(matchId: number): Promise<void> {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await adminApi.getMatchDetail(matchId)
  } catch {
    ElMessage.error('获取匹配详情失败，请确认后端已启动并具备管理员权限')
  } finally {
    detailLoading.value = false
  }
}

// ---------------- D3：导出 ----------------
const exportScope = ref<ExportScope>('all')
const exportFormat = ref<ExportFormat>('csv')
const exporting = ref(false)

async function onExportMatches(): Promise<void> {
  if (selectedIds.value.length === 0) return
  exporting.value = true
  try {
    await adminApi.exportMatches(selectedIds.value, exportFormat.value, exportScope.value)
    ElMessage.success(`已导出（${exportScope.value} / ${exportFormat.value}）`)
  } catch (err) {
    // 后端未装 openpyxl 时 xlsx 返回 400 + code 9001，需要给出可操作提示
    const code = (err as { code?: number })?.code
    if (exportFormat.value === 'xlsx' && code === 9001) {
      ElMessage.error('服务器未安装 openpyxl，暂不支持 xlsx，请改用 CSV 或 Markdown')
    } else {
      ElMessage.error('导出失败，请确认后端已启动并具备管理员权限')
    }
  } finally {
    exporting.value = false
  }
}

async function onCleanup(): Promise<void> {
  cleaning.value = true
  try {
    const res = await adminApi.triggerCleanup()
    ElMessage.success(`清理完成：匹配 ${res.purged_matches} 条，物品 ${res.purged_items} 条`)
    loadMatches()
  } catch {
    ElMessage.error('清理失败，请确认后端已启动并具备管理员权限')
  } finally {
    cleaning.value = false
  }
}

// ---------------- v7：审计日志 ----------------
const loading = ref(false)
const logs = ref<AuditLog[]>([])
const backendMissing = ref(false)

async function onExport(format: 'csv' | 'json'): Promise<void> {
  exporting.value = true
  try {
    await adminApi.exportAudit(format)
  } catch {
    ElMessage.error('导出失败，请确认后端已启动并具备管理员权限')
  } finally {
    exporting.value = false
  }
}

function actionType(action: string): '' | 'success' | 'warning' | 'danger' | 'info' {
  if (action.startsWith('publish')) return ''
  if (action.includes('handover')) return 'warning'
  if (action === 'claim') return 'success'
  if (action === 'reject') return 'danger'
  if (action === 'ban') return 'danger'
  return 'info'
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + '…' : s
}

async function load(): Promise<void> {
  loading.value = true
  backendMissing.value = false
  try {
    const res = await matchApi.auditLogs({ page: 1, page_size: 100 })
    logs.value = (res as Page<AuditLog>).items
  } catch {
    // 后端未提供该接口（404 等）时给出提示，不阻断页面
    backendMissing.value = true
    logs.value = []
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadUsers(1)
  loadMatches()
  load()
})
</script>

<style scoped>
.admin-tabs {
  margin-top: 4px;
}
.lf-toolbar {
  margin-bottom: 14px;
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.export-bar {
  padding: 8px 10px;
  background: #f7f9fc;
  border-radius: 8px;
}
.lf-pager {
  margin-top: 12px;
  justify-content: flex-end;
}
.plain-phone {
  font-family: ui-monospace, Menlo, Consolas, monospace;
  color: #b45309;
}
.conv-title {
  margin: 18px 0 10px;
  font-size: 15px;
}
.conv-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.conv-item {
  border-radius: 8px;
  padding: 8px 10px;
  background: #f4f7fb;
  border-left: 3px solid #94a3b8;
}
.conv-item.conv-finder {
  background: #f2fbf5;
  border-left-color: #34d399;
}
.conv-meta {
  display: flex;
  gap: 10px;
  font-size: 12px;
  margin-bottom: 4px;
}
.conv-body {
  font-size: 13px;
  line-height: 1.55;
  word-break: break-word;
}
.audit-timeline {
  padding: 8px 4px;
}
.audit-item {
  padding: 12px 14px;
}
.audit-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.audit-target,
.audit-uid {
  font-size: 13px;
}
.audit-row {
  font-size: 13px;
  display: flex;
  gap: 6px;
  align-items: center;
}
.audit-detail {
  margin-top: 8px;
  font-size: 13px;
  line-height: 1.5;
  background: #f7f9fc;
  border-radius: 8px;
  padding: 8px 10px;
}
.audit-detail code {
  word-break: break-all;
  color: #334155;
}
.audit-ua {
  margin-top: 6px;
  font-size: 12px;
  word-break: break-all;
}
</style>
