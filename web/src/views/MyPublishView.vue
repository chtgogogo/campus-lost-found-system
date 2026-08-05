<template>
  <div class="lf-container">
    <h2 class="lf-page-title">我的发布</h2>

    <el-tabs v-model="tab" class="lf-tabs">
      <el-tab-pane label="进行中" name="active" />
      <el-tab-pane label="已完成" name="done" />
    </el-tabs>

    <div v-loading="loading">
      <el-empty v-if="!loading && visibleItems.length === 0" :description="emptyText" />

      <div class="publish-grid">
        <ItemCard
          v-for="it in visibleItems"
          :key="it.kind + '-' + it.data.id"
          :item="it"
          :show-delete="true"
          @click="onOpen(it)"
          @delete="onDelete"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { itemsApi } from '@/api/items'
import ItemCard, { type BoardItem } from '@/components/ItemCard.vue'
import type { FoundItemOut, LostItemOut } from '@/types'

const tab = ref<'active' | 'done'>('active')
const loading = ref(false)
const lost = ref<LostItemOut[]>([])
const found = ref<FoundItemOut[]>([])

// Q10 状态映射：失物进行中={0,1,2}/已完成={3}；拾物进行中={0}/已完成={1}
function isActive(kind: 'lost' | 'found', status: number): boolean {
  if (kind === 'lost') return status === 0 || status === 1 || status === 2
  return status === 0
}

const allItems = computed<BoardItem[]>(() => {
  const lostItems: BoardItem[] = lost.value.map((d) => ({ kind: 'lost', data: d }))
  const foundItems: BoardItem[] = found.value.map((d) => ({ kind: 'found', data: d }))
  return [...lostItems, ...foundItems]
})

const visibleItems = computed<BoardItem[]>(() =>
  allItems.value.filter((it) => {
    const status = (it.data as LostItemOut | FoundItemOut).status
    return isActive(it.kind, status) === (tab.value === 'active')
  }),
)

const emptyText = computed(() =>
  tab.value === 'active' ? '暂无进行中的发布' : '暂无已完成的发布',
)

async function load() {
  loading.value = true
  try {
    const res = await itemsApi.myPublished()
    lost.value = res.lost
    found.value = res.found
  } catch {
    /* 忽略 */
  } finally {
    loading.value = false
  }
}

function onOpen(_it: BoardItem) {
  // 仅展示用，可后续扩展为详情抽屉；当前保持与公示栏一致的点击行为
}

// v7：删除发布（软删），确认后调用后端并乐观移除本地项
async function onDelete(it: BoardItem) {
  try {
    await ElMessageBox.confirm(
      '删除后仅你不可见，管理员留存 1 年。确定删除吗？',
      '删除发布',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  try {
    if (it.kind === 'lost') {
      await itemsApi.deleteLost(it.data.id)
    } else {
      await itemsApi.deleteFound(it.data.id)
    }
    if (it.kind === 'lost') {
      lost.value = lost.value.filter((d) => d.id !== it.data.id)
    } else {
      found.value = found.value.filter((d) => d.id !== it.data.id)
    }
    ElMessage.success('已删除')
  } catch {
    ElMessage.error('删除失败，请稍后重试')
  }
}

onMounted(load)
</script>

<style scoped>
.lf-tabs {
  margin-bottom: 12px;
}
.publish-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 14px;
}
</style>
