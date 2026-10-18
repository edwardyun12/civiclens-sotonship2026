import { existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The simulator engine is shared with the browser viewers (viewer/src/engine.js) so there is one copy to keep in
// step with simulator/engine.py. The repo root is found by looking upwards, so this works from frontend/.
const here = dirname(fileURLToPath(import.meta.url))
const root = [resolve(here, '..'), resolve(here, '../..')].find((p) => existsSync(resolve(p, 'viewer/src/engine.js')))
const engine = resolve(root, 'viewer/src/engine.js')

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@engine': engine } },
  server: {
    host: '127.0.0.1',
    port: 5173,
    fs: { allow: [root] },
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
