<template>
  <div class="lf-container">
    <h2 class="lf-page-title">管理后台 · 审计日志</h2>

    <div class="audit-actions">
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
              <span v-if="log.user_id" class="lf-muted audit-uid">操作人 #{{ log.user_id }}</span>
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

    <!-- v7：未失效匹配记录（取证导出） -->
    <el-divider />
    <h2 class="lf-page-title">管理后台 · 未失效匹配记录</h2>

    <div class="match-actions">
      <el-select
        v-model="matchStatus"
        placeholder="状态筛选"
        clearable
        size="small"
        style="width: 150px"
        @change="loadMatches"
      >
        <el-option label="待认领" :value="0" />
        <el-option label="认领中" :value="1" />
        <el-option label="已完成" :value="2" />
        <el-option label="已拒绝" :value="3" />
        <el-option label="待自取" :value="4" />
        <el-option label="已放弃" :value="5" />
      </el-select>
      <el-button size="small" :loading="matchLoading" @click="loadMatches">刷新</el-button>
      <el-button
        type="primary"
        size="small"
        :disabled="selectedIds.length === 0"
        :loading="exporting"
        @click="onExportMatches"
      >
        一键导出（{{ selectedIds.length }}）
      </el-button>
      <el-button size="small" :loading="cleaning" @click="onCleanup">触发周期清理</el-button>
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
      <el-empty v-if="!matchLoading && matches.length === 0" description="暂无未失效匹配" />
      <el-table
        v-else
        :data="matches"
        border
        size="small"
        @selection-change="onSelectionChange"
      >
        <el-table-column type="selection" width="44" />
        <el-table-column prop="id" label="匹配ID" width="80" />
        <el-table-column label="失物" min-width="120">
          <template #default="{ row }">{{ row.lost_item?.title || '—' }}</template>
        </el-table-column>
        <el-table-column label="拾物" min-width="120">
          <template #default="{ row }">{{ row.found_item?.title || '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small">{{ matchStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="completed_at" label="完成时间" width="170">
          <template #default="{ row }">{{ row.completed_at || '—' }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="170" />
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { matchApi } from '@/api/match'
import { adminApi } from '@/api/admin'
import { auditActionLabel } from '@/api/constants'
import type { AuditLog, MatchOut, Page } from '@/types'

const loading = ref(false)
const logs = ref<AuditLog[]>([])
const backendMissing = ref(false)
const exporting = ref(false)

// v7：未失效匹配记录（取证导出）
const matches = ref<MatchOut[]>([])
const matchLoading = ref(false)
const matchBackendMissing = ref(false)
const matchStatus = ref<number | undefined>(undefined)
const selectedIds = ref<number[]>([])
const cleaning = ref(false)

function onSelectionChange(rows: MatchOut[]) {
  selectedIds.value = rows.map((r) => r.id)
}

function matchStatusLabel(s: number): string {
  return ['待认领', '认领中', '已完成', '已拒绝', '待自取', '已放弃'][s] ?? String(s)
}

async function loadMatches() {
  matchLoading.value = true
  matchBackendMissing.value = false
  try {
    const res = await adminApi.listAdminMatches({
      status: matchStatus.value,
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

async function onExportMatches() {
  if (selectedIds.value.length === 0) return
  exporting.value = true
  try {
    await adminApi.exportMatches(selectedIds.value)
    ElMessage.success('已导出取证 CSV')
  } catch {
    ElMessage.error('导出失败，请确认后端已启动并具备管理员权限')
  } finally {
    exporting.value = false
  }
}

async function onCleanup() {
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

async function onExport(format: 'csv' | 'json') {
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

async function load() {
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
  load()
  loadMatches()
})
</script>

<style scoped>
.audit-timeline {
  padding: 8px 4px;
}
.audit-actions {
  margin-bottom: 14px;
  display: flex;
  gap: 8px;
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
.audit-target {
  font-size: 13px;
}
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
