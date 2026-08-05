<template>
  <div class="login-wrap">
    <div class="login-card lf-card">
      <div class="login-brand">
        <span class="lf-logo-dot" />
        <h1>校园失物招领系统</h1>
        <p class="lf-muted">基于 YOLOv8 的智能匹配 · 毕业设计演示</p>
      </div>

      <el-tabs v-model="tab" class="login-tabs">
        <!-- 登录 -->
        <el-tab-pane label="登录" name="login">
          <el-form
            ref="loginFormRef"
            :model="loginForm"
            :rules="loginRules"
            label-position="top"
            @submit.prevent
          >
            <el-form-item label="学号" prop="student_no">
              <el-input
                v-model="loginForm.student_no"
                placeholder="请输入学号 / 工号"
                :prefix-icon="User"
              />
            </el-form-item>
            <el-form-item label="密码" prop="password">
              <el-input
                v-model="loginForm.password"
                type="password"
                show-password
                placeholder="请输入密码"
                :prefix-icon="Lock"
                @keyup.enter="onLogin"
              />
            </el-form-item>
            <el-button
              type="primary"
              size="large"
              class="login-btn"
              :loading="loading"
              @click="onLogin"
            >
              登录
            </el-button>
          </el-form>
          <p class="lf-muted login-tip">
            演示提示：可直接使用任意学号 + 密码登录；开启“演示数据”时无后端亦可登录。
          </p>
        </el-tab-pane>

        <!-- 注册 -->
        <el-tab-pane label="注册" name="register">
          <el-form
            ref="regFormRef"
            :model="regForm"
            :rules="regRules"
            label-position="top"
            @submit.prevent
          >
            <el-form-item label="学号" prop="student_no">
              <el-input v-model="regForm.student_no" placeholder="请输入学号" :prefix-icon="User" />
            </el-form-item>
            <el-form-item label="手机号" prop="phone">
              <el-input v-model="regForm.phone" placeholder="请输入手机号" :prefix-icon="Iphone" />
            </el-form-item>
            <el-form-item label="短信验证码" prop="sms_code">
              <div class="sms-row">
                <el-input v-model="regForm.sms_code" placeholder="6 位验证码" :prefix-icon="Message" />
                <el-button :disabled="smsCountdown > 0" @click="onSendSms">
                  {{ smsCountdown > 0 ? `${smsCountdown}s 后重发` : '获取验证码' }}
                </el-button>
              </div>
            </el-form-item>
            <el-alert
              v-if="devCode"
              type="success"
              :closable="false"
              show-icon
              :title="`演示验证码：${devCode}`"
              description="演示环境短信为桩，验证码固定为 123456，填写任意 6 位数字即可。"
            />
            <el-form-item label="密码" prop="password">
              <el-input
                v-model="regForm.password"
                type="password"
                show-password
                placeholder="至少 6 位"
                :prefix-icon="Lock"
              />
            </el-form-item>
            <el-form-item label="真实姓名（选填）" prop="real_name">
              <el-input v-model="regForm.real_name" placeholder="选填" :prefix-icon="EditPen" />
            </el-form-item>
            <!--
              v10 变更 C：管理员邀请码（选填）。
              ⚠️ AC-C9：错码与不填必须表现完全一致 —— 这里刻意**不加**任何校验规则、
              不做长度/格式提示、注册失败后也不单独提示"邀请码错误"，
              否则可由前端反馈差异探测出邀请码机制的存在。
            -->
            <el-form-item label="邀请码（选填）" prop="admin_code">
              <el-input
                v-model="regForm.admin_code"
                placeholder="如无邀请码请留空"
                :prefix-icon="Key"
              />
            </el-form-item>
            <el-button
              type="primary"
              size="large"
              class="login-btn"
              :loading="loading"
              @click="onRegister"
            >
              注册并登录
            </el-button>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import {
  EditPen,
  Iphone,
  Key,
  Lock,
  Message,
  User,
} from '@element-plus/icons-vue'
import { authApi } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import { useDemoStore } from '@/stores/demo'
import { MOCK_ME } from '@/api/mockAdapter'
import { decodeJwt } from '@/utils/jwt'
import type { UserOut } from '@/types'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const demo = useDemoStore()

const tab = ref<'login' | 'register'>('login')
const loading = ref(false)
const devCode = ref('')
const smsCountdown = ref(0)

const loginFormRef = ref<FormInstance>()
const loginForm = reactive({ student_no: '', password: '' })
const loginRules: FormRules = {
  student_no: [{ required: true, message: '请输入学号', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

const regFormRef = ref<FormInstance>()
const regForm = reactive({
  student_no: '',
  phone: '',
  sms_code: '',
  password: '',
  real_name: '',
  // v10：管理员邀请码（选填）。空串在提交时转为 null，与"未填写"完全等价。
  admin_code: '',
})
const regRules: FormRules = {
  student_no: [{ required: true, message: '请输入学号', trigger: 'blur' }],
  phone: [
    { required: true, message: '请输入手机号', trigger: 'blur' },
    { pattern: /^1\d{10}$/, message: '手机号格式不正确', trigger: 'blur' },
  ],
  sms_code: [
    { required: true, message: '请输入验证码', trigger: 'blur' },
    { pattern: /^\d{6}$/, message: '验证码为 6 位数字', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' },
  ],
}

function buildUserFromToken(token: string, studentNo: string): UserOut | null {
  const payload = decodeJwt(token)
  if (payload) {
    return {
      id: payload.sub,
      role: payload.role,
      student_no: studentNo,
      phone: '',
      real_name: null,
      credit_score: 100,
      status: 0,
      created_at: '',
    }
  }
  // 演示模式：mock token 非 JWT，使用内置演示用户 id
  if (demo.enabled) {
    return {
      id: MOCK_ME,
      role: 0,
      student_no: studentNo,
      phone: '',
      real_name: null,
      credit_score: 100,
      status: 0,
      created_at: '',
    }
  }
  return null
}

async function onLogin() {
  if (!loginFormRef.value) return
  await loginFormRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      const token = await authApi.login({
        student_no: loginForm.student_no,
        password: loginForm.password,
      })
      const user = buildUserFromToken(token.access_token, loginForm.student_no)
      auth.login(token, user)
      ElMessage.success('登录成功')
      const redirect = (route.query.redirect as string) || '/board'
      router.push(redirect)
    } catch {
      /* 错误已由拦截器提示 */
    } finally {
      loading.value = false
    }
  })
}

async function onSendSms() {
  if (!/^1\d{10}$/.test(regForm.phone)) {
    ElMessage.warning('请先填写正确的手机号')
    return
  }
  try {
    const res = await authApi.sendSms({ phone: regForm.phone, purpose: 'register' })
    devCode.value = res.dev_code || '123456'
    ElMessage.success('验证码已发送')
    smsCountdown.value = 60
    const timer = setInterval(() => {
      smsCountdown.value -= 1
      if (smsCountdown.value <= 0) clearInterval(timer)
    }, 1000)
  } catch {
    /* 忽略 */
  }
}

async function onRegister() {
  if (!regFormRef.value) return
  await regFormRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      const res = await authApi.register({
        student_no: regForm.student_no,
        phone: regForm.phone,
        sms_code: regForm.sms_code,
        password: regForm.password,
        real_name: regForm.real_name || null,
        // v10：空串归一为 null，保证"填了空格/没填"与"填错码"走同一条后端分支
        admin_code: regForm.admin_code.trim() || null,
      })
      auth.login(res.token, res.user)
      // ⚠️ AC-C9：邀请码错误时**不提示**任何与邀请码相关的信息，
      //    与未填写的表现完全一致（都只提示"注册成功"）。
      if (res.user && res.user.role === 1) {
        ElMessage.success('注册成功，已开通管理员权限')
      } else {
        ElMessage.success('注册成功，已自动登录')
      }
      router.push('/board')
    } catch {
      /* 忽略 */
    } finally {
      loading.value = false
    }
  })
}
</script>

<style scoped>
.login-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background: linear-gradient(135deg, #e8f0ff 0%, #f4f6fb 100%);
}
.login-card {
  width: 100%;
  max-width: 400px;
  padding: 28px 24px;
}
.login-brand {
  text-align: center;
  margin-bottom: 8px;
}
.login-brand h1 {
  font-size: 20px;
  margin: 8px 0 4px;
}
.lf-logo-dot {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--lf-primary);
  display: inline-block;
}
.login-btn {
  width: 100%;
  margin-top: 8px;
}
.sms-row {
  display: flex;
  gap: 8px;
}
.sms-row .el-input {
  flex: 1;
}
.login-tip {
  font-size: 12px;
  margin-top: 12px;
  text-align: center;
}
</style>
