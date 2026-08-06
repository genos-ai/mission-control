import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'react-flow': ['@xyflow/react'],
        },
      },
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5174,
    // Bind all interfaces, not just [::1] — a container reaching the host via
    // host.docker.internal (and curl on 127.0.0.1) needs a non-IPv6-loopback
    // listener. Dev only; this exposes the dev server on the local network.
    host: true,
    // Vite's Host header check 403s anything not localhost or an IP literal.
    allowedHosts: ['host.docker.internal'],
    proxy: {
      '/api': {
        target: 'http://localhost:8100',
        changeOrigin: true,
        // SSE streams are long-lived. Disable all timeouts so the proxy
        // doesn't tear the connection down mid-stream.
        timeout: 0,
        proxyTimeout: 0,
        // Swallow benign disconnect noise from EventSource close/reconnect
        // so the dev log stays readable. Real backend errors still surface
        // as a 502 to the browser.
        configure: (proxy) => {
          proxy.on('error', (err, _req, res) => {
            const code = (err as NodeJS.ErrnoException).code
            if (code === 'ECONNRESET' || code === 'EPIPE') return
            // Surface everything else (ECONNREFUSED, timeouts, etc.)
            console.warn(`[vite proxy] ${code ?? 'error'}: ${err.message}`)
            if (res && 'writeHead' in res && !res.headersSent) {
              res.writeHead(502, { 'Content-Type': 'text/plain' })
              res.end('Bad gateway')
            }
          })
        },
      },
      '/health': {
        target: 'http://localhost:8100',
        changeOrigin: true,
      },
    },
  },
})
