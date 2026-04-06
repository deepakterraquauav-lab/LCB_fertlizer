import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 4000,
    proxy: {
      '/api': {
        target: 'http://localhost:6000',
        changeOrigin: true,
      },
      '/get_last_irrigation_calendar': {
        target: 'http://localhost:6000',
        changeOrigin: true,
      },
      '/get_daily_data': {
        target: 'http://localhost:6000',
        changeOrigin: true,
      },
      '/get_irrigation_calendar': {
        target: 'http://localhost:6000',
        changeOrigin: true,
      },
      '/get_land_cover_analysis': {
        target: 'http://localhost:6000',
        changeOrigin: true,
      },
      '/get_gee_tile': {
        target: 'http://localhost:6000',
        changeOrigin: true,
      },
      '/get_available_dates': {
        target: 'http://localhost:6000',
        changeOrigin: true,
      },
      '/generate_report': {
        target: 'http://localhost:6000',
        changeOrigin: true,
      },
      '/get_vra_map': {
        target: 'http://localhost:6000',
        changeOrigin: true,
      },
    },
  },
  publicDir: 'public',
})
