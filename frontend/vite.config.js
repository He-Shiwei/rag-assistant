//import { defineConfig } from 'vite'
//import vue from '@vitejs/plugin-vue'
//
//export default defineConfig({
//  plugins: [vue()],
//  server: {
//    port: 3000,
//    proxy: {
//      '/api': {
//        target: 'http://localhost:8000',
//        changeOrigin: true
//      }
//    }
//  }
//})

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: true,              // 允许外部访问（0.0.0.0）
    port: 3000,
    allowedHosts: [
      'e963f885.natappfree.cc',   // 允许这个具体的 natapp 域名
      '.natappfree.cc'            // 或允许所有 natapp 子域名（更灵活）
    ],
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  }
})