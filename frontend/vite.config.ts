import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The built app is served by FastAPI from api/static, so there is one URL,
// one deploy and no CORS to configure. `npm run dev` proxies the API so the
// frontend can still be developed with hot reload.
//
// Tailwind v4 needs no config file and no PostCSS setup — the plugin below
// and the `@theme` block in index.css are the whole of it.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  build: { outDir: '../api/static', emptyOutDir: true },
  server: {
    proxy: Object.fromEntries(
      ['/inbox', '/stats', '/jobs', '/gmail', '/watch', '/review', '/health']
        .map((path) => [path, { target: 'http://localhost:8000', changeOrigin: true }])
    ),
  },
})
