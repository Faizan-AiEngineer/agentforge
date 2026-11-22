import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiPort = process.env.AGENTFORGE_API_PORT ?? '8000'
if (!/^\d{1,5}$/.test(apiPort)) throw new Error('AGENTFORGE_API_PORT must be a local port number')
const backend = 'http://127.0.0.1:' + apiPort

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: { manualChunks: { charts: ['recharts'], canvas: ['@xyflow/react'] } },
    },
  },
  server: {
    host: '127.0.0.1',
    strictPort: true,
    proxy: {
      '/api': backend,
      '/health': backend,
    },
  },
  preview: {
    host: '127.0.0.1',
    proxy: { '/api': backend },
  },
})
