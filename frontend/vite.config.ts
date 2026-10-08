import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  return {
    base: env.VITE_BASE_PATH || '/',
    plugins: [react()],
    server: {
      proxy: {
        '/v1': 'http://localhost:8000',
        '/health': 'http://localhost:8000',
        '/ready': 'http://localhost:8000',
      },
    },
  }
})
