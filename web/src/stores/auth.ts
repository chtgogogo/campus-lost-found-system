// 认证状态（Pinia）：保存当前用户与令牌，提供登录态判定。
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { Token, UserOut } from '@/types'
import { clearToken, getToken, setToken } from '@/api/request'

const USER_KEY = 'lf_user'

function loadUser(): UserOut | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as UserOut) : null
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(getToken())
  const user = ref<UserOut | null>(loadUser())

  const isLoggedIn = computed(() => !!token.value)
  const userId = computed(() => user.value?.id ?? null)
  const isAdmin = computed(() => user.value?.role === 1)

  function persist(userData: UserOut | null) {
    user.value = userData
    try {
      if (userData) localStorage.setItem(USER_KEY, JSON.stringify(userData))
      else localStorage.removeItem(USER_KEY)
    } catch {
      /* ignore */
    }
  }

  function login(tokenData: Token, userData: UserOut | null) {
    setToken(tokenData.access_token)
    token.value = tokenData.access_token
    persist(userData)
  }

  function logout() {
    clearToken()
    token.value = null
    user.value = null
  }

  function setUser(userData: UserOut) {
    persist(userData)
  }

  return { token, user, isLoggedIn, userId, isAdmin, login, logout, setUser }
})
