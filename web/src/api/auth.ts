// 认证相关接口（对齐 app/routers/auth.py）
import { apiPost } from './request'
import type {
  LoginRequest,
  RegisterRequest,
  SendSmsRequest,
  Token,
  UserOut,
} from '@/types'

export interface RegisterResult {
  user: UserOut
  token: Token
}

export const authApi = {
  register(body: RegisterRequest): Promise<RegisterResult> {
    return apiPost<RegisterResult>('/auth/register', body)
  },
  login(body: LoginRequest): Promise<Token> {
    return apiPost<Token>('/auth/login', body)
  },
  refresh(refreshToken: string): Promise<Token> {
    return apiPost<Token>('/auth/refresh', { refresh_token: refreshToken })
  },
  sendSms(body: SendSmsRequest): Promise<{ sent: boolean; dev_code?: string }> {
    return apiPost<{ sent: boolean; dev_code?: string }>('/auth/send-sms', body)
  },
  bindPhone(body: { phone: string; sms_code: string }): Promise<UserOut> {
    return apiPost<UserOut>('/auth/bind-phone', body)
  },
  logout(refreshToken: string): Promise<{ ok: boolean }> {
    return apiPost<{ ok: boolean }>('/auth/logout', { refresh_token: refreshToken })
  },
}
