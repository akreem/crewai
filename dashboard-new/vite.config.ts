import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/auth': 'http://localhost:6000',
      '/chat': 'http://localhost:6000',
      '/agents': 'http://localhost:6000',
      '/status': 'http://localhost:6000',
      '/workspace': 'http://localhost:6000',
      '/ws': {
        target: 'ws://localhost:6000',
        ws: true,
      },
    },
  },
})
