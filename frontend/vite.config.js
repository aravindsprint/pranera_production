import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { VitePWA } from 'vite-plugin-pwa'
import path from 'path'
import { backendProxyPlugin } from './dev-backend-proxy.js'

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, __dirname, '')
  // Dev server only: /api, /assets, /files and /private go to the live site or
  // your local bench, picked per request on the Settings page (see
  // dev-backend-proxy.js), so switching never needs a restart. A production
  // build is served by Frappe from the same origin as the API — no proxy, and
  // __PP_BACKENDS__ is null so the switch doesn't exist there.
  const LIVE = env.VITE_LIVE_TARGET || 'https://erp.pranera.in'
  const LOCAL = env.VITE_LOCAL_TARGET || 'http://127.0.0.1:8001'
  const DEFAULT_BACKEND = env.VITE_DEFAULT_BACKEND === 'live' ? 'live' : 'local'
  const serving = command === 'serve'

  return {
  base: command === 'serve' ? '/' : '/assets/pranera_production/production_app/',

  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') }
  },

  server: {
    // 3002 so it runs beside pranera_knit (3000) and pranera_planning (3001).
    // Cookies are shared across localhost ports, so one login (and one backend
    // choice, the pp_backend cookie) covers all three dev apps.
    port: 3002,
  },

  build: {
    outDir: path.resolve(__dirname, '../pranera_production/public/production_app'),
    emptyOutDir: true,
    rollupOptions: {
      input: path.resolve(__dirname, 'index.html'),
      output: {
        // Content-hashed entry (index-<hash>.js). www/production_app.py reads
        // the built index.html to find it. Never load the entry with a ?v=
        // query: lazy chunks import the entry by plain URL, and a different URL
        // makes the browser run a second copy of the app.
        entryFileNames: 'index-[hash].js',
        chunkFileNames: 'chunks/[name]-[hash].js',
        assetFileNames: (info) => {
          if (info.name?.endsWith('.css')) return 'css/[name]-[hash].css'
          return 'assets/[name]-[hash][extname]'
        }
      }
    }
  },

  define: {
    __PP_BACKENDS__: serving
      ? JSON.stringify({ default: DEFAULT_BACKEND, targets: { live: LIVE, local: LOCAL } })
      : 'null',
  },

  plugins: [
    vue(),
    ...(serving ? [backendProxyPlugin({ targets: { live: LIVE, local: LOCAL }, defaultBackend: DEFAULT_BACKEND })] : []),
    VitePWA({
      base: '/assets/pranera_production/production_app/',
      registerType: 'autoUpdate',
      workbox: {
        skipWaiting: true,
        clientsClaim: true,
        globPatterns: ['**/*.{js,css,html,png,svg,woff2}'],
        // Serve the cached SPA shell for in-app navigations when offline,
        // so reloading /production-app/home works with no network. Exclude /api and
        // /files so those still hit the network (and their own caches below).
        navigateFallback: '/assets/pranera_production/production_app/index.html',
        // Only the offline-critical pages (home, create-roll, create-qi, rolls,
        // stock-entry, work-order — see router/index.js "eager" section) should
        // fall back to the cached shell so operators can reload them with no
        // network. The report/dashboard pages are online-only by design and
        // must always hit the server: only the server-rendered /production-app page
        // (www/production_app.py) injects window.csrf_token, and the cached static
        // index.html never has it — serving these from cache silently breaks
        // every POST call (call()/ensureCSRF()).
        navigateFallbackDenylist: [
          /^\/api/, /^\/files/, /^\/app/,
          /^\/production-app\/dashboard/,
          /^\/production-app\/pivot/,
          /^\/production-app\/lot-report/,
          /^\/production-app\/adopt-rolls/,
        ],
        runtimeCaching: [
          {
            // Cache read-only GET list/report data so it's available offline.
            urlPattern: ({ url, request }) =>
              request.method === 'GET' && url.pathname.startsWith('/api/'),
            handler: 'NetworkFirst',
            options: {
              cacheName: 'production-api-get',
              networkTimeoutSeconds: 5,
              expiration: { maxEntries: 200, maxAgeSeconds: 60 * 60 * 24 * 7 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
      },
      manifest: {
        name: 'Pranera Production App',
        short_name: 'Production',
        theme_color: '#1e3a5f',
        background_color: '#ffffff',
        display: 'standalone',
        orientation: 'portrait',
        start_url: '/production-app',
        scope: '/production-app',
        icons: [
          { src: '/assets/pranera_production/production_app/icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: '/assets/pranera_production/production_app/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: '/assets/pranera_production/production_app/icons/icon-192-maskable.png', sizes: '192x192', type: 'image/png', purpose: 'maskable' },
          { src: '/assets/pranera_production/production_app/icons/icon-512-maskable.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' }
        ]
      }
    })
  ]
}
})
