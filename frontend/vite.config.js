import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The built app is served by FastAPI from api/static, so there is one URL,
// one deploy and no CORS to configure. `npm run dev` proxies the API so the
// frontend can still be developed with hot reload.
export default defineConfig({
  plugins: [react()],
  build: { outDir: '../api/static', emptyOutDir: true },
  server: {
    proxy: Object.fromEntries(
      ['/inbox', '/stats', '/jobs', '/gmail', '/watch', '/review', '/health']
        .map((path) => [path, { target: 'http://localhost:8000', changeOrigin: true }])
    ),
  },
})
