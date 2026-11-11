import { join } from 'node:path'

import { defineConfig, devices } from '@playwright/test'

// The dev server proxies /api to :8000, and the backend runs with
// USE_SAMPLE_DATA so the suite needs no API keys and costs nothing.
const backendDir = join(import.meta.dirname, '..', 'backend')
const backendPython = join(
  backendDir,
  '.venv',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python'
)

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 20_000 },
  // One SQLite file and one browser: run in order, not in parallel.
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['list']] : [['list']],
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
    video: 'off'
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      // Quoted: the interpreter path can contain spaces.
      command: `"${backendPython}" -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000`,
      cwd: backendDir,
      url: 'http://127.0.0.1:8000/api/health',
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: {
        USE_SAMPLE_DATA: 'true',
        DATABASE_PATH: 'data/e2e.sqlite3'
      }
    },
    {
      // Build first, then serve the artefact: the dev server re-optimises
      // dependencies mid-run and reloads the page under the test's cursor.
      command: 'npm run build && npm run preview',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000
    }
  ]
})
