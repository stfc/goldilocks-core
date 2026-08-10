import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Development proxies Core HTTP routes to a locally running FastAPI server.
// Production serves the built Workbench from FastAPI under the same origin, so
// no CORS is configured here or there.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/health': 'http://localhost:8000',
      '/structure': 'http://localhost:8000',
      '/tasks': 'http://localhost:8000',
      '/recommend': 'http://localhost:8000',
      '/generate': 'http://localhost:8000',
      '/compute': 'http://localhost:8000',
    },
  },
});
