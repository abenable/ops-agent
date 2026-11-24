import tailwindcss from '@tailwindcss/vite'
import { tanstackStart } from '@tanstack/react-start/plugin/vite'
import viteReact from '@vitejs/plugin-react'
import { nitro } from 'nitro/vite'
import { defineConfig } from 'vite'

export default defineConfig({
  resolve: { tsconfigPaths: true },
  plugins: [
    tailwindcss(),
    tanstackStart(),
    nitro({
      routeRules: {
        // No framing: a hidden iframe could otherwise trick a click onto Approve.
        '/**': {
          headers: {
            'Content-Security-Policy': "frame-ancestors 'none'",
            'X-Frame-Options': 'DENY',
            'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'same-origin',
          },
        },
      },
    }),
    viteReact(),
  ],
})
