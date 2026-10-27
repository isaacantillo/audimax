import path from 'node:path'

import tailwindcss from '@tailwindcss/vite'
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  // The router plugin must come before react().
  plugins: [tanstackRouter({ target: 'react', autoCodeSplitting: true }), react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  server: {
    // Dev: Vite serves the UI and forwards /api to FastAPI. In Docker the web container's nginx does the same.
    proxy: { '/api': { target: 'http://localhost:8000', ws: true } }, // ws: the live subtitles socket
  },
})
