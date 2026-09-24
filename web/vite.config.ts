/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// Vite 配置：开发服务器默认 5173 端口；
// 配置 /api 与 /uploads 代理到后端 (http://localhost:8000)，
// 这样真实后端联调时无需处理 CORS。
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: true,
    port: 5173,
    // 允许任意 host（含 ngrok/cpolar 等内网穿透域名，每次地址会变，不能写死）
    allowedHosts: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/uploads': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1500,
  },
  // 审查 P1（2026-09-24）：前端最小测试门禁——vitest 单测（jsdom 环境，令牌存取/信封解包等纯逻辑）
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts'],
  },
})
