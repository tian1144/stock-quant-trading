import { defineConfig } from 'vite'
import uni from '@dcloudio/vite-plugin-uni'

export default defineConfig({
  plugins: [uni()],
  server: {
    port: 5173,
    host: '0.0.0.0',
    proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true, secure: false } }
  }
})
