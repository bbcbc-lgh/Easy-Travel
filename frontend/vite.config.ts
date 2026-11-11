import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173
  },
  build: {
    // Long-lived vendor chunks keep the app chunk small and cacheable.
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-vue': ['vue', 'vue-router'],
          'vendor-antd': ['ant-design-vue'],
          'vendor-map': ['@amap/amap-jsapi-loader']
        }
      }
    }
  }
})
