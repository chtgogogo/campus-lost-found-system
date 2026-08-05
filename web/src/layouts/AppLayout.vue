<template>
  <div class="lf-root">
    <!-- 顶部栏 -->
    <header class="lf-header">
      <div class="lf-brand">
        <span class="lf-logo-dot" />
        校园失物招领
      </div>

      <div class="lf-header-right">
        <div class="lf-demo-switch">
          <span class="lf-muted" style="font-size: 13px">演示数据</span>
          <el-switch
            :model-value="demo.enabled"
            @change="(v: any) => demo.setEnabled(Boolean(v))"
            inline-prompt
            active-text="开"
            inactive-text="关"
          />
        </div>

        <!-- v7：演示态身份切换（仅演示模式可见），用于进入管理后台 -->
        <div v-if="demo.enabled" class="lf-demo-role">
          <span class="lf-muted" style="font-size: 13px">身份</span>
          <el-radio-group
            :model-value="demo.demoRole"
            size="small"
            @change="(v: any) => onRoleChange(Number(v))"
          >
            <el-radio-button :value="0">普通</el-radio-button>
            <el-radio-button :value="1">管理员</el-radio-button>
          </el-radio-group>
        </div>

        <el-dropdown trigger="click" @command="onCommand">
          <span class="lf-user">
            <el-avatar :size="28" style="background: var(--lf-primary)">
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

    <!-- 自动开启演示模式的提示 -->
    <el-alert
      v-if="demo.autoDetected"
      type="warning"
      :closable="true"
      show-icon
      title="未检测到后端服务，已自动开启演示数据（本地静态数据）。开启右上角“演示数据”开关可随时切换。"
      style="border-radius: 0"
    />

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
        <RouterView :key="demo.dataVersion" />
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
import { useDemoStore } from '@/stores/demo'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const demo = useDemoStore()

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

// v7：演示态身份切换——同步更新当前登录用户的 role，使管理后台导航即时可见
function onRoleChange(role: number) {
  demo.setRole(role)
  if (auth.user) auth.user.role = role
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
.lf-demo-switch {
  display: flex;
  align-items: center;
  gap: 8px;
}
.lf-demo-role {
  display: flex;
  align-items: center;
  gap: 8px;
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
.lf-logo-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--lf-primary);
  display: inline-block;
}
</style>
