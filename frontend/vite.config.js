import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Ports and the API target are env-driven so parallel agent worktrees never
// collide on 5173/8000. Defaults preserve normal single-instance dev.
//   FRONTEND_PORT  -> vite dev server port                     (default 5173)
//   API_PORT       -> host port the backend API is published on (default 8000)
const frontendPort = Number(process.env.FRONTEND_PORT) || 5173
const apiPort = Number(process.env.API_PORT) || 8000

export default defineConfig({
  plugins: [react()],
  server: {
    port: frontendPort,
    strictPort: true,
    proxy: {
      '/api': {
        target: `http://localhost:${apiPort}`,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
