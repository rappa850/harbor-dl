import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
const target = 'http://127.0.0.1:8765'
// 后端会校验 Origin 与 Host 同源；开发代理转发时把 Origin 改写成后端地址，登录等 POST 才不会被 403。
export default defineConfig({plugins: [vue()], server: {proxy: {'/api': {target, changeOrigin: true, configure: proxy => proxy.on('proxyReq', req => { if (req.getHeader('origin')) req.setHeader('origin', target) })}}}})
