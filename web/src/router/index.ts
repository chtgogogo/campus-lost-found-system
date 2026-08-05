import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import LoginView from '@/views/LoginView.vue'
import AppLayout from '@/layouts/AppLayout.vue'

// v7：扩展路由元信息（角色门控）
declare module 'vue-router' {
  interface RouteMeta {
    public?: boolean
    title?: string
    roles?: string[]
  }
}

// 导航菜单项（供布局侧边栏 / 底部标签栏复用）
export interface NavItem {
  path: string
  title: string
  icon: string
  roles?: string[] // v7：需要的角色（如 ['admin']）；空/缺省表示全员可见
}

export const NAV_ITEMS: NavItem[] = [
  { path: '/board', title: '公示栏', icon: 'HomeFilled' },
  { path: '/publish', title: '发布', icon: 'UploadFilled' },
  { path: '/matches', title: '我的匹配', icon: 'Connection' },
  { path: '/messages', title: '我的消息', icon: 'ChatDotRound' },
  { path: '/mypublish', title: '我的发布', icon: 'Files' },
  { path: '/handover', title: '交接确认', icon: 'Switch' },
  { path: '/admin', title: '管理后台', icon: 'Setting', roles: ['admin'] },
]

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: LoginView,
    meta: { public: true, title: '登录 / 注册' },
  },
  {
    path: '/',
    component: AppLayout,
    redirect: '/board',
    children: [
      {
        path: 'board',
        name: 'board',
        component: () => import('@/views/BoardView.vue'),
        meta: { title: '公示栏' },
      },
      {
        path: 'publish',
        name: 'publish',
        component: () => import('@/views/PublishView.vue'),
        meta: { title: '发布' },
      },
      {
        path: 'matches',
        name: 'matches',
        component: () => import('@/views/MatchesView.vue'),
        meta: { title: '我的匹配' },
      },
      {
        path: 'messages',
        name: 'messages',
        component: () => import('@/views/MessagesView.vue'),
        meta: { title: '我的消息' },
      },
      {
        path: 'mypublish',
        name: 'mypublish',
        component: () => import('@/views/MyPublishView.vue'),
        meta: { title: '我的发布' },
      },
      {
        path: 'handover',
        name: 'handover',
        component: () => import('@/views/HandoverView.vue'),
        meta: { title: '交接确认' },
      },
      {
        path: 'admin',
        name: 'admin',
        component: () => import('@/views/AdminView.vue'),
        meta: { title: '管理后台', roles: ['admin'] },
      },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/board' },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

// 登录态守卫：未登录访问受保护页面 → /login；已登录访问 /login → /board
router.beforeEach((to) => {
  const auth = useAuthStore()
  const isPublic = (to.meta?.public as boolean) || false
  if (!isPublic && !auth.isLoggedIn) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.path === '/login' && auth.isLoggedIn) {
    return { path: '/board' }
  }
  // v7：管理员门控（前端第二重；后端 require_admin 为最终门控）
  const roles = (to.meta?.roles as string[] | undefined) || []
  if (roles.includes('admin') && auth.user?.role !== 1) {
    return { path: '/board' }
  }
  return true
})

export default router
