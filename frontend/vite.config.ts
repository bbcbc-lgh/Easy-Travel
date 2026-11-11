import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    // Playwright writes traces and results while the dev server is running; with
    // the root watched, every write triggered a full page reload and detached the
    // elements a test was about to click.
    watch: {
      ignored: ['**/test-results/**', '**/playwright-report/**', '**/coverage/**']
    },
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    }
  },
  build: {
    // Long-lived vendor chunks keep the app chunk small and cacheable.
    // Rolldown (Vite 8) only accepts the function form of manualChunks.
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('ant-design-vue') || id.includes('@ant-design')) return 'vendor-antd'
          if (id.includes('@amap')) return 'vendor-map'
          if (id.includes('vue-router') || id.includes('/vue/') || id.includes('@vue')) {
            return 'vendor-vue'
          }
          return undefined
        }
      }
    }
  }
})
