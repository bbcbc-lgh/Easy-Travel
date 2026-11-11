import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  // Needed so single-file components can be loaded at all: without it `.vue`
  // files are invisible to both the runner and the coverage report.
  plugins: [vue()],
  test: {
    include: ['tests/**/*.test.ts'],
    environment: 'node',
    coverage: {
      provider: 'v8',
      include: ['src/**/*.ts', 'src/**/*.vue'],
      // `all` reports files no test ever imports (at 0%) - without it the views,
      // which are most of the code, simply vanish from the report.
      all: true,
      // Reported, not gated. The point right now is to make the size of the gap
      // visible: the views have no tests at all.
      reporter: ['text-summary', 'text']
    }
  }
})
