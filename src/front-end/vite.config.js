import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The simulator engine is shared with the browser viewers (viewer/src/engine.js) so there is one copy to keep in
// step with src/engine.py.
const engine = fileURLToPath(new URL('../../viewer/src/engine.js', import.meta.url))

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@engine': engine } },
  server: {
    host: '127.0.0.1',
    port: 5173,
    fs: { allow: ['../..'] },
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
