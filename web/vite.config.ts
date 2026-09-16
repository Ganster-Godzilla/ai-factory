import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// 构建产物输出到 Flask 的 static/web,由 dashboard 同源托管(无需单独前端服务器);
// dev 模式代理 /api 到本机 dashboard,前端开发可直连真实数据。
export default defineConfig({
  plugins: [vue()],
  base: '/static/web/',
  build: {
    outDir: '../orchestrator/dashboard/static/web',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': process.env.OFFICE_API_URL || 'http://127.0.0.1:8321',
      '/factory': {
        target: process.env.OFFICE_API_URL || 'http://127.0.0.1:8321',
        rewrite: path => path.replace(/^\/factory/, '') || '/',
      },
      '/ticket/': process.env.OFFICE_API_URL || 'http://127.0.0.1:8321',
    },
  },
})
