/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
    // Allow importing CSS files from semi-ui dist/ directory bypassing package exports
    conditions: ['import', 'module', 'browser', 'default'],
  },
  css: {
    preprocessorOptions: {}
  },
  optimizeDeps: {
    include: ['@douyinfe/semi-ui'],
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': { target: 'ws://localhost:8000', ws: true },
    }
  },
  build: {
    rollupOptions: {
      external: [],
    }
  }
})
