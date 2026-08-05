// 解析 JWT payload（仅 base64 解码，不做签名校验），用于从 access_token 取出 sub/role。
// 后端 JWT payload = { sub, role, jti, iat, exp }（见 app/core/security.py）。

export interface JwtPayload {
  sub: number
  role: number
}

export function decodeJwt(token: string): JwtPayload | null {
  try {
    const parts = token.split('.')
    if (parts.length < 2) return null
    const b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const json = decodeURIComponent(
      atob(b64)
        .split('')
        .map((c) => '%' + c.charCodeAt(0).toString(16).padStart(2, '0'))
        .join(''),
    )
    const payload = JSON.parse(json)
    return { sub: Number(payload.sub), role: Number(payload.role ?? 0) }
  } catch {
    return null
  }
}
