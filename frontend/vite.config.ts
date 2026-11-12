import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

const repoRoot = fileURLToPath(new URL('..', import.meta.url))

export default defineConfig({
  plugins: [vue()],
  // One `.env` for the whole project, shared with the backend. Vite only exposes
  // `VITE_`-prefixed keys to the bundle, so server secrets in that file stay out
  // of the browser build.
  envDir: repoRoot,
  optimizeDeps: {
    // Both are imported lazily on export. Left out, the dev server discovers them
    // on first use and reloads the page - which is a surprising thing to have
    // happen while you are reading a plan.
    include: ['html2canvas', 'jspdf']
  },
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
  // e2e runs against `vite preview`, not the dev server: the dev server
  // optimises dependencies lazily and force-reloads the page when it discovers a
  // new one, which detaches elements mid-test. Preview serves the real build.
  preview: {
    port: 5173,
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
