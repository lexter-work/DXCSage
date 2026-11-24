import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  base: './',
  plugins: [vue()],
  server: { port: 29701, proxy: { '/api': 'http://localhost:29700' } },
  test: { environment: 'node' },
})
