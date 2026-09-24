<template>
  <div class="lf-root">
    <!-- 顶部栏 -->
    <header class="lf-header">
      <div class="lf-brand">
        <span class="lf-logo-mark" />
        校园失物招领
      </div>

      <div class="lf-header-right">
        <el-dropdown trigger="click" @command="onCommand">
          <span class="lf-user">
            <el-avatar :size="28" class="lf-avatar">
              {{ userInitial }}
            </el-avatar>
            <span class="lf-user-name">{{ auth.user?.real_name || auth.user?.student_no || '我' }}</span>
            <el-icon><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout">
                <el-icon><SwitchButton /></el-icon> 退出登录
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <div class="lf-body">
      <!-- 桌面端侧边菜单 -->
      <aside class="lf-side">
        <el-menu :default-active="activePath" router class="lf-menu">
          <el-menu-item v-for="item in navItems" :key="item.path" :index="item.path">
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.title }}</span>
          </el-menu-item>
        </el-menu>
      </aside>

      <!-- 主内容区 -->
      <main class="lf-main lf-main-with-tabbar">
        <RouterView />
      </main>
    </div>

    <!-- 移动端底部标签栏 -->
    <nav class="lf-tabbar">
      <div
        v-for="item in navItems"
        :key="item.path"
        class="tab"
        :class="{ active: activePath === item.path }"
        @click="go(item.path)"
      >
        <el-icon><component :is="item.icon" /></el-icon>
        <span>{{ item.title }}</span>
      </div>
    </nav>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { NAV_ITEMS } from '@/router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

// v7：按角色过滤导航项（/admin 仅管理员 role===1 可见）
const navItems = computed(() =>
  NAV_ITEMS.filter((i) => !i.roles || i.roles.length === 0 || auth.user?.role === 1),
)

const activePath = computed(() => '/' + (route.path.split('/')[1] || 'board'))

const userInitial = computed(() => {
  const name = auth.user?.real_name || auth.user?.student_no || '我'
  return name.slice(0, 1)
})

function go(path: string) {
  router.push(path)
}

async function onCommand(command: string) {
  if (command === 'logout') {
    try {
      await ElMessageBox.confirm('确定退出登录吗？', '提示', {
        confirmButtonText: '退出',
        cancelButtonText: '取消',
        type: 'warning',
      })
    } catch {
      return
    }
    auth.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.lf-root {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}
.lf-header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}
.lf-user {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  outline: none;
}
.lf-user-name {
  font-size: 14px;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.lf-menu {
  border-right: none;
  border-radius: var(--lf-radius);
  box-shadow: var(--lf-shadow);
  height: 100%;
}
.lf-menu :deep(.el-menu-item) {
  border-radius: 8px;
  margin: 2px 0;
  transition: all 0.15s ease;
}
.lf-menu :deep(.el-menu-item.is-active) {
  background: var(--lf-primary-light-9);
  font-weight: 600;
}
.lf-avatar {
  background: var(--lf-gradient-brand);
  color: #fff;
  font-weight: 600;
}
</style>
